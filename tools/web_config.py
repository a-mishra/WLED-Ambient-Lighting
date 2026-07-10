"""Web-based config server with pipeline preview and calibration UI.

Usage:
    python -m tools.web_config
    python -m tools.web_config --port 8080 --exit-on-idle --idle-timeout 300

No authentication — use only on trusted home networks.
Does not start automatically with main.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config import load_config
from ambient.config_schema import (
  CameraBusyError,
  ConfigValidationError,
  apply_patch,
  extract_editable_config,
  get_editable_schema,
  patch_warnings,
  save_config_atomic,
  validate_perspective_points,
)
from ambient.factory import create_camera
from ambient.pipeline_preview import PreviewResult, encode_jpeg, process_frame

logger = logging.getLogger(__name__)

CAPTURE_WARMUP_S = 1.5
JPEG_SOI = b"\xff\xd8"


class ServerState:
  """Shared mutable state for the HTTP handler."""

  def __init__(
    self,
    config_path: Path,
    camera_factory: Callable[[dict], Any] | None = None,
  ) -> None:
    self.config_path = config_path
    self.config = load_config(config_path)
    self.camera_factory = camera_factory or create_camera
    self.lock = threading.Lock()
    self.last_request_time = time.monotonic()
    self.raw_frame: np.ndarray | None = None
    self.preview: PreviewResult | None = None
    self.jpeg_raw: bytes | None = None
    self.jpeg_warped: bytes | None = None
    self.jpeg_overlay: bytes | None = None
    self.capture_ms: float = 0.0
    self._shutdown_server: Callable[[], None] | None = None

  def touch(self) -> None:
    self.last_request_time = time.monotonic()

  def set_shutdown(self, fn: Callable[[], None]) -> None:
    self._shutdown_server = fn

  def release_cache(self) -> None:
    with self.lock:
      self.raw_frame = None
      self.preview = None
      self.jpeg_raw = None
      self.jpeg_warped = None
      self.jpeg_overlay = None
      self.capture_ms = 0.0
    logger.info("Preview cache released (idle).")

  def reload_config(self) -> None:
    self.config = load_config(self.config_path)

  def _store_preview(self, raw: np.ndarray, preview: PreviewResult, capture_ms: float = 0.0) -> None:
    self.raw_frame = raw
    self.preview = preview
    self.capture_ms = capture_ms
    self.jpeg_raw = encode_jpeg(preview.raw_annotated)
    self.jpeg_warped = encode_jpeg(preview.warped_annotated)
    self.jpeg_overlay = encode_jpeg(preview.led_overlay)

  def capture_and_process(self) -> dict:
    with self.lock:
      self.reload_config()
      config = self.config
      t0 = time.perf_counter()
      camera = None
      try:
        camera = self.camera_factory(config)
        time.sleep(CAPTURE_WARMUP_S)
        raw = camera.get_latest_frame()
      except (IndexError, OSError, RuntimeError) as exc:
        msg = str(exc).lower()
        if "camera" in msg or "index" in msg or "device" in msg or "busy" in msg:
          raise CameraBusyError(
            "Stop main.py before capturing, or use Reprocess on a cached frame."
          ) from exc
        raise
      finally:
        if camera is not None:
          camera.close()

      if raw is None:
        raise RuntimeError("No frame captured from camera.")

      capture_ms = (time.perf_counter() - t0) * 1000
      preview = process_frame(config, raw)
      self._store_preview(raw, preview, capture_ms)
      return self.preview_meta()

  def reprocess(self) -> dict:
    with self.lock:
      self.reload_config()
      if self.raw_frame is None:
        raise RuntimeError("No cached frame — click Capture first.")
      preview = process_frame(self.config, self.raw_frame)
      self._store_preview(self.raw_frame, preview, self.capture_ms)
      return self.preview_meta()

  def save_calibration(self, points: list) -> dict:
    with self.lock:
      self.reload_config()
      w, h = self.config["camera"]["resolution"]
      validated = validate_perspective_points(points, w, h)
      self.config["perspective"]["points"] = validated
      save_config_atomic(self.config, self.config_path)
      if self.raw_frame is not None:
        preview = process_frame(self.config, self.raw_frame)
        self._store_preview(self.raw_frame, preview, self.capture_ms)
      return self.preview_meta()

  def patch_config(self, patch: dict) -> dict:
    with self.lock:
      self.reload_config()
      updated = apply_patch(self.config, patch)
      save_config_atomic(updated, self.config_path)
      self.config = updated
      warnings = patch_warnings(self.config, patch)
      return {"ok": True, "warnings": warnings, "config": extract_editable_config(self.config)}

  def preview_meta(self) -> dict:
    if self.preview is None:
      return {
        "has_cache": False,
        "points": self.config["perspective"]["points"],
        "frame_width": self.config["camera"]["resolution"][0],
        "frame_height": self.config["camera"]["resolution"][1],
      }

    p = self.preview
    layout = p.led_layout
    colors = p.colors_final
    i = 0
    top = colors[i : i + layout["top"]].tolist()
    i += layout["top"]
    right = colors[i : i + layout["right"]].tolist()
    i += layout["right"]
    bottom = colors[i : i + layout["bottom"]].tolist()
    i += layout["bottom"]
    left = colors[i : i + layout["left"]].tolist()
    total = sum(layout.values())

    timing = dict(p.timing_ms)
    if self.capture_ms:
      timing["capture"] = round(self.capture_ms, 2)

    return {
      "has_cache": True,
      "points": self.config["perspective"]["points"],
      "frame_width": self.config["camera"]["resolution"][0],
      "frame_height": self.config["camera"]["resolution"][1],
      "output_resolution": self.config["perspective"]["output_resolution"],
      "led_layout": layout,
      "led_total": total,
      "timing_ms": timing,
      "colors": {"top": top, "right": right, "bottom": bottom, "left": left},
    }


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
  body = json.dumps(payload).encode("utf-8")
  handler.send_response(code)
  handler.send_header("Content-Type", "application/json")
  handler.send_header("Content-Length", str(len(body)))
  handler.end_headers()
  handler.wfile.write(body)


def _jpeg_response(handler: BaseHTTPRequestHandler, data: bytes | None) -> None:
  if not data:
    _json_response(handler, 404, {"error": "no_preview", "message": "Capture a frame first."})
    return
  handler.send_response(200)
  handler.send_header("Content-Type", "image/jpeg")
  handler.send_header("Cache-Control", "no-cache")
  handler.send_header("Content-Length", str(len(data)))
  handler.end_headers()
  handler.wfile.write(data)


def make_handler(state: ServerState):
  class Handler(BaseHTTPRequestHandler):
    server_version = "WLEDWebConfig/1.0"

    def log_message(self, fmt: str, *args) -> None:
      logger.debug("%s - %s", self.address_string(), fmt % args)

    def _read_json_body(self) -> dict:
      length = int(self.headers.get("Content-Length", 0))
      raw = self.rfile.read(length) if length else b"{}"
      return json.loads(raw.decode("utf-8") or "{}")

    def _route(self) -> None:
      state.touch()
      path = urlparse(self.path).path

      if self.command == "GET" and path == "/":
        self._serve_html()
      elif self.command == "GET" and path == "/api/status":
        _json_response(self, 200, {
          "idle": True,
          "has_cache": state.preview is not None,
        })
      elif self.command == "GET" and path == "/api/config":
        _json_response(self, 200, {
          "config": extract_editable_config(state.config),
          "schema": get_editable_schema(),
        })
      elif self.command == "PATCH" and path == "/api/config":
        self._handle_patch()
      elif self.command == "POST" and path == "/api/preview/capture":
        self._handle_capture()
      elif self.command == "POST" and path == "/api/preview/reprocess":
        self._handle_reprocess()
      elif self.command == "POST" and path == "/api/calibration":
        self._handle_calibration()
      elif self.command == "GET" and path == "/api/preview/meta":
        _json_response(self, 200, state.preview_meta())
      elif self.command == "GET" and path == "/api/preview/raw.jpg":
        _jpeg_response(self, state.jpeg_raw)
      elif self.command == "GET" and path == "/api/preview/warped.jpg":
        _jpeg_response(self, state.jpeg_warped)
      elif self.command == "GET" and path == "/api/preview/overlay.jpg":
        _jpeg_response(self, state.jpeg_overlay)
      else:
        _json_response(self, 404, {"error": "not_found"})

    def do_GET(self) -> None:
      try:
        self._route()
      except Exception as exc:
        logger.exception("GET error")
        _json_response(self, 500, {"error": "internal", "message": str(exc)})

    def do_POST(self) -> None:
      try:
        self._route()
      except Exception as exc:
        logger.exception("POST error")
        _json_response(self, 500, {"error": "internal", "message": str(exc)})

    def do_PATCH(self) -> None:
      try:
        self._route()
      except Exception as exc:
        logger.exception("PATCH error")
        _json_response(self, 500, {"error": "internal", "message": str(exc)})

    def _serve_html(self) -> None:
      body = _HTML_PAGE.encode("utf-8")
      self.send_response(200)
      self.send_header("Content-Type", "text/html; charset=utf-8")
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)

    def _handle_patch(self) -> None:
      try:
        patch = self._read_json_body()
        result = state.patch_config(patch)
        _json_response(self, 200, result)
      except ConfigValidationError as exc:
        _json_response(self, 400, {"error": "validation", "fields": exc.errors})

    def _handle_capture(self) -> None:
      try:
        meta = state.capture_and_process()
        _json_response(self, 200, meta)
      except CameraBusyError as exc:
        _json_response(self, 503, {"error": "camera_busy", "message": str(exc)})

    def _handle_reprocess(self) -> None:
      try:
        meta = state.reprocess()
        _json_response(self, 200, meta)
      except RuntimeError as exc:
        _json_response(self, 400, {"error": "no_cache", "message": str(exc)})

    def _handle_calibration(self) -> None:
      try:
        body = self._read_json_body()
        points = body.get("points", [])
        meta = state.save_calibration(points)
        _json_response(self, 200, meta)
      except ConfigValidationError as exc:
        _json_response(self, 400, {"error": "validation", "fields": exc.errors})

  return Handler


def idle_watchdog(
  state: ServerState,
  idle_timeout: float,
  exit_on_idle: bool,
  poll_interval: float = 30.0,
) -> None:
  while True:
    time.sleep(poll_interval)
    idle_for = time.monotonic() - state.last_request_time
    if idle_for < idle_timeout:
      continue
    state.release_cache()
    if exit_on_idle and state._shutdown_server:
      logger.info("Idle timeout (%.0fs) — shutting down.", idle_timeout)
      state._shutdown_server()
      break


def run(
  config_path: str | None = None,
  host: str = "0.0.0.0",
  port: int = 8080,
  idle_timeout: float = 300.0,
  exit_on_idle: bool = False,
  camera_factory: Callable[[dict], Any] | None = None,
) -> None:
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
  logger.warning("No authentication — use only on trusted networks.")

  cfg_path = Path(config_path) if config_path else Path(__file__).parent.parent / "config" / "config.yaml"
  state = ServerState(cfg_path, camera_factory=camera_factory)
  handler = make_handler(state)

  server = ThreadingHTTPServer((host, port), handler)
  state.set_shutdown(server.shutdown)

  watchdog = threading.Thread(
    target=idle_watchdog,
    args=(state, idle_timeout, exit_on_idle),
    daemon=True,
    name="IdleWatchdog",
  )
  watchdog.start()

  logger.info("Web config server at http://%s:%d (idle_timeout=%ds exit_on_idle=%s)",
              host if host != "0.0.0.0" else "<pi-ip>", port, int(idle_timeout), exit_on_idle)
  logger.info("No camera access until client clicks Capture.")

  try:
    server.serve_forever()
  except KeyboardInterrupt:
    logger.info("Shutting down.")
  finally:
    server.server_close()


def main() -> None:
  parser = argparse.ArgumentParser(description="WLED ambient lighting web config UI")
  parser.add_argument("--config", default=None, help="Path to config.yaml")
  parser.add_argument("--host", default="0.0.0.0")
  parser.add_argument("--port", type=int, default=8080)
  parser.add_argument("--idle-timeout", type=float, default=300.0,
                      help="Seconds before idle cache release (default 300)")
  parser.add_argument("--exit-on-idle", action="store_true",
                      help="Exit server process after idle timeout")
  args = parser.parse_args()
  run(
    config_path=args.config,
    host=args.host,
    port=args.port,
    idle_timeout=args.idle_timeout,
    exit_on_idle=args.exit_on_idle,
  )


if __name__ == "__main__":
  main()


_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WLED Ambient Config</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 0; background: #1a1a2e; color: #eee; }
  header { background: #16213e; padding: 12px 16px; border-bottom: 1px solid #333; }
  header h1 { margin: 0; font-size: 1.2rem; }
  nav { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 16px; background: #0f3460; }
  nav button { background: #333; color: #eee; border: none; padding: 8px 14px; cursor: pointer; border-radius: 4px; }
  nav button.active { background: #e94560; }
  main { padding: 16px; max-width: 1400px; margin: 0 auto; }
  .tab { display: none; }
  .tab.active { display: block; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .toolbar button, .form-section button {
    background: #e94560; color: #fff; border: none; padding: 10px 16px;
    border-radius: 4px; cursor: pointer; font-size: 0.95rem;
  }
  .toolbar button.secondary { background: #533483; }
  .panels { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
  .panel { background: #16213e; border-radius: 8px; padding: 10px; }
  .panel h3 { margin: 0 0 8px; font-size: 0.9rem; color: #aaa; }
  .panel img { width: 100%; height: auto; border-radius: 4px; cursor: crosshair; background: #000; min-height: 120px; }
  .panel img.no-click { cursor: default; }
  .meta { background: #16213e; border-radius: 8px; padding: 12px; margin-top: 12px; font-size: 0.85rem; }
  .meta table { width: 100%; border-collapse: collapse; }
  .meta td { padding: 4px 8px; border-bottom: 1px solid #333; }
  .msg { padding: 10px; border-radius: 4px; margin: 8px 0; }
  .msg.ok { background: #1b4332; }
  .msg.err { background: #6a040f; }
  .msg.warn { background: #5c4d00; }
  .form-section { background: #16213e; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
  .form-section h2 { margin-top: 0; font-size: 1rem; }
  .field { margin-bottom: 12px; }
  .field label { display: block; font-size: 0.85rem; color: #aaa; margin-bottom: 4px; }
  .field input, .field select { width: 100%; max-width: 320px; padding: 8px; border-radius: 4px; border: 1px solid #444; background: #0f3460; color: #eee; }
  .field input[type=range] { max-width: 100%; }
  .row2 { display: flex; gap: 8px; flex-wrap: wrap; }
  .row2 .field { flex: 1; min-width: 120px; }
  details { margin-top: 8px; }
  .cal-points { font-family: monospace; font-size: 0.8rem; }
</style>
</head>
<body>
<header><h1>WLED Ambient Lighting — Web Config</h1></header>
<nav id="tabs">
  <button class="active" data-tab="preview">Preview</button>
  <button data-tab="camera">Camera</button>
  <button data-tab="color">Color</button>
  <button data-tab="wled">WLED</button>
  <button data-tab="processing">Processing</button>
</nav>
<main>
  <div id="banner"></div>

  <div id="tab-preview" class="tab active">
    <div class="toolbar">
      <button onclick="captureFrame()">Capture</button>
      <button onclick="captureFrame()">Retake</button>
      <button class="secondary" onclick="reprocess()">Reprocess</button>
      <button class="secondary" onclick="resetPoints()">Reset points</button>
      <button class="secondary" onclick="saveCalibration()">Save calibration</button>
    </div>
    <p style="font-size:0.85rem;color:#aaa">Click the <strong>raw capture</strong> image: corners in order TL → TR → BR → BL. EMA smoothing applies at runtime only.</p>
    <div class="panels">
      <div class="panel"><h3>1. Raw capture</h3><img id="img-raw" alt="raw" onclick="onRawClick(event)"></div>
      <div class="panel"><h3>2. Perspective corrected</h3><img id="img-warped" class="no-click" alt="warped"></div>
      <div class="panel"><h3>3. LED colors</h3><img id="img-overlay" class="no-click" alt="overlay"></div>
    </div>
    <div class="meta" id="preview-meta">Click Capture to load preview.</div>
    <div class="cal-points" id="cal-points"></div>
  </div>

  <div id="tab-camera" class="tab"><div class="form-section" id="form-camera"></div></div>
  <div id="tab-color" class="tab"><div class="form-section" id="form-color"></div></div>
  <div id="tab-wled" class="tab"><div class="form-section" id="form-wled"></div></div>
  <div id="tab-processing" class="tab"><div class="form-section" id="form-processing"></div></div>
</main>
<script>
let config = {};
let clickPoints = [];
const ts = () => Date.now();

function showBanner(text, kind='ok') {
  const el = document.getElementById('banner');
  el.className = 'msg ' + kind;
  el.textContent = text;
  if (kind === 'ok') setTimeout(() => { el.textContent = ''; el.className = ''; }, 4000);
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw { status: r.status, data };
  return data;
}

function refreshImages() {
  const q = '?t=' + ts();
  document.getElementById('img-raw').src = '/api/preview/raw.jpg' + q;
  document.getElementById('img-warped').src = '/api/preview/warped.jpg' + q;
  document.getElementById('img-overlay').src = '/api/preview/overlay.jpg' + q;
}

function renderPreviewMeta(meta) {
  const el = document.getElementById('preview-meta');
  if (!meta.has_cache) {
    el.innerHTML = 'No preview cached. Click <strong>Capture</strong>.';
    return;
  }
  const t = meta.timing_ms || {};
  let html = '<table><tr><th>Stage</th><th>ms</th></tr>';
  for (const k of ['capture','warp','extract','post_process']) {
    if (t[k] !== undefined) html += `<tr><td>${k}</td><td>${t[k]}</td></tr>`;
  }
  html += `</table><p>LEDs: top ${meta.led_layout.top} + right ${meta.led_layout.right} + bottom ${meta.led_layout.bottom} + left ${meta.led_layout.left} = <strong>${meta.led_total}</strong></p>`;
  html += '<details><summary>RGB per side</summary><pre>' + JSON.stringify(meta.colors, null, 2) + '</pre></details>';
  el.innerHTML = html;
  document.getElementById('cal-points').textContent = 'Saved points: ' + JSON.stringify(meta.points);
  clickPoints = meta.points.map(p => [...p]);
}

async function captureFrame() {
  try {
    showBanner('Capturing…', 'warn');
    const meta = await api('POST', '/api/preview/capture');
    refreshImages();
    renderPreviewMeta(meta);
    showBanner('Capture OK');
  } catch (e) {
    const msg = e.data?.message || e.data?.error || 'Capture failed';
    showBanner(msg, e.status === 503 ? 'warn' : 'err');
  }
}

async function reprocess() {
  try {
    const meta = await api('POST', '/api/preview/reprocess');
    refreshImages();
    renderPreviewMeta(meta);
    showBanner('Reprocessed');
  } catch (e) {
    showBanner(e.data?.message || 'Reprocess failed', 'err');
  }
}

function onRawClick(ev) {
  if (clickPoints.length >= 4) return;
  const img = ev.target;
  const rect = img.getBoundingClientRect();
  const x = (ev.clientX - rect.left) * (img.naturalWidth / rect.width);
  const y = (ev.clientY - rect.top) * (img.naturalHeight / rect.height);
  clickPoints.push([Math.round(x), Math.round(y)]);
  document.getElementById('cal-points').textContent = 'Clicked: ' + JSON.stringify(clickPoints);
}

function resetPoints() {
  clickPoints = (config.perspective?.points || []).map(p => [...p]);
  document.getElementById('cal-points').textContent = 'Points reset to saved: ' + JSON.stringify(clickPoints);
}

async function saveCalibration() {
  if (clickPoints.length !== 4) {
    showBanner('Click exactly 4 corners first.', 'err');
    return;
  }
  try {
    const meta = await api('POST', '/api/calibration', { points: clickPoints });
    refreshImages();
    renderPreviewMeta(meta);
    config.perspective.points = meta.points;
    showBanner('Calibration saved');
  } catch (e) {
    const fields = e.data?.fields;
    showBanner(fields ? JSON.stringify(fields) : 'Save failed', 'err');
  }
}

function fieldHtml(section, key, spec, value) {
  const id = section + '-' + key.replace('.', '-');
  const label = spec.label || key;
  if (spec.type === 'bool') {
    return `<div class="field"><label><input type="checkbox" id="${id}" ${value ? 'checked' : ''}> ${label}</label></div>`;
  }
  if (spec.type === 'enum') {
    const opts = spec.options.map(o => `<option value="${o}" ${o===value?'selected':''}>${o}</option>`).join('');
    return `<div class="field"><label>${label}</label><select id="${id}">${opts}</select></div>`;
  }
  if (spec.type === 'resolution') {
    const v = value || [320, 240];
    return `<div class="field row2"><div class="field"><label>${label} W</label><input type="number" id="${id}-w" value="${v[0]}"></div><div class="field"><label>H</label><input type="number" id="${id}-h" value="${v[1]}"></div></div>`;
  }
  if (spec.type === 'float' && spec.max !== undefined) {
    return `<div class="field"><label>${label}: <span id="${id}-v">${value}</span></label><input type="range" id="${id}" min="${spec.min}" max="${spec.max}" step="${spec.step||0.1}" value="${value}" oninput="document.getElementById('${id}-v').textContent=this.value"></div>`;
  }
  const inputType = spec.type === 'int' ? 'number' : 'text';
  return `<div class="field"><label>${label}</label><input type="${inputType}" id="${id}" value="${value ?? ''}"></div>`;
}

function buildForm(section, schema, data, containerId) {
  let html = `<h2>${section.charAt(0).toUpperCase() + section.slice(1)}</h2>`;
  for (const [key, spec] of Object.entries(schema)) {
    if (spec.type) {
      html += fieldHtml(section, key, spec, data[key]);
    } else {
      html += `<h3>${key}</h3>`;
      for (const [subkey, subspec] of Object.entries(spec)) {
        const val = (data[key] || {})[subkey];
        html += fieldHtml(section, key + '.' + subkey, subspec, val);
      }
    }
  }
  html += `<button onclick="saveSection('${section}')">Save ${section}</button>`;
  document.getElementById(containerId).innerHTML = html;
}

function readSection(section, schema) {
  const out = {};
  for (const [key, spec] of Object.entries(schema)) {
    if (spec.type) {
      const id = section + '-' + key.replace('.', '-');
      if (spec.type === 'bool') out[key] = document.getElementById(id).checked;
      else if (spec.type === 'resolution') {
        out[key] = [parseInt(document.getElementById(id + '-w').value), parseInt(document.getElementById(id + '-h').value)];
      } else if (spec.type === 'float') out[key] = parseFloat(document.getElementById(id).value);
      else if (spec.type === 'int') out[key] = parseInt(document.getElementById(id).value);
      else out[key] = document.getElementById(id).value;
    } else {
      out[key] = {};
      for (const subkey of Object.keys(spec)) {
        const id = section + '-' + key + '.' + subkey;
        const subspec = spec[subkey];
        if (subspec.type === 'int') out[key][subkey] = parseInt(document.getElementById(id.replace('.', '-')).value);
        else out[key][subkey] = document.getElementById(id.replace('.', '-')).value;
      }
    }
  }
  return out;
}

async function saveSection(section) {
  try {
    const schema = (await api('GET', '/api/config')).schema[section];
    const body = {};
    body[section] = readSection(section, schema);
    const res = await api('PATCH', '/api/config', body);
    config = res.config;
    if (res.warnings?.length) showBanner(res.warnings.join(' '), 'warn');
    else showBanner(section + ' saved — click Reprocess on Preview tab to update images');
  } catch (e) {
    showBanner(JSON.stringify(e.data?.fields || e.data) || 'Save failed', 'err');
  }
}

document.getElementById('tabs').addEventListener('click', (ev) => {
  if (ev.target.tagName !== 'BUTTON') return;
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  ev.target.classList.add('active');
  document.getElementById('tab-' + ev.target.dataset.tab).classList.add('active');
});

async function init() {
  try {
    const res = await api('GET', '/api/config');
    config = res.config;
    clickPoints = (config.perspective?.points || []).map(p => [...p]);
    buildForm('camera', res.schema.camera, config.camera, 'form-camera');
    buildForm('color', res.schema.color, config.color, 'form-color');
    buildForm('wled', res.schema.wled, config.wled, 'form-wled');
    buildForm('processing', res.schema.processing, config.processing, 'form-processing');
    const meta = await api('GET', '/api/preview/meta');
    if (meta.has_cache) { refreshImages(); renderPreviewMeta(meta); }
    else renderPreviewMeta(meta);
  } catch (e) {
    showBanner('Failed to load config', 'err');
  }
}
init();
</script>
</body>
</html>"""
