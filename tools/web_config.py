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
import subprocess
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
from ambient.service_manager import AmbientServiceManager, ServiceControlError

logger = logging.getLogger(__name__)

CAPTURE_WARMUP_S = 1.5
JPEG_SOI = b"\xff\xd8"

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
  .img-wrap { position: relative; width: 100%; line-height: 0; }
  .img-wrap img { width: 100%; height: auto; display: block; border-radius: 4px; background: #000; min-height: 120px; }
  .img-wrap canvas { position: absolute; left: 0; top: 0; width: 100%; height: 100%; cursor: crosshair; touch-action: none; }
  .panel img { width: 100%; height: auto; border-radius: 4px; background: #000; min-height: 120px; }
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
  .cal-manual { background: #16213e; border-radius: 8px; padding: 12px; margin-top: 12px; }
  .cal-manual h3 { margin: 0 0 8px; font-size: 0.9rem; color: #aaa; }
  .cal-manual table { width: 100%; max-width: 420px; border-collapse: collapse; font-size: 0.85rem; }
  .cal-manual th, .cal-manual td { padding: 6px 8px; text-align: left; border-bottom: 1px solid #333; }
  .cal-manual input { width: 72px; padding: 6px; border-radius: 4px; border: 1px solid #444; background: #0f3460; color: #eee; }
  .cal-manual button { background: #533483; color: #fff; border: none; padding: 8px 14px; border-radius: 4px; cursor: pointer; margin-top: 8px; }
  .form-note { font-size: 0.85rem; color: #aaa; margin: 8px 0; }
  #service-bar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
    padding: 10px 16px; background: #0f3460; border-bottom: 1px solid #333;
    font-size: 0.9rem;
  }
  #service-bar .status-dot {
    width: 10px; height: 10px; border-radius: 50%; display: inline-block;
    background: #666; margin-right: 4px;
  }
  #service-bar .status-dot.on { background: #52b788; }
  #service-bar .status-dot.off { background: #e94560; }
  #service-bar button {
    background: #533483; color: #fff; border: none; padding: 6px 12px;
    border-radius: 4px; cursor: pointer; font-size: 0.85rem;
  }
  #service-bar button.primary { background: #e94560; }
  #service-bar button.danger { background: #6a040f; }
  #service-bar button:disabled { opacity: 0.45; cursor: not-allowed; }
  #confirm-modal {
    display: none; position: fixed; inset: 0; z-index: 1000;
    background: rgba(0,0,0,0.65); align-items: center; justify-content: center; padding: 16px;
  }
  #confirm-modal.open { display: flex; }
  #confirm-modal .dialog {
    background: #16213e; border-radius: 8px; max-width: 520px; width: 100%;
    padding: 16px; border: 1px solid #444; max-height: 85vh; display: flex; flex-direction: column;
  }
  #confirm-modal h2 { margin: 0 0 12px; font-size: 1rem; }
  #confirm-modal .body { overflow-y: auto; flex: 1; margin-bottom: 12px; font-size: 0.85rem; }
  #confirm-modal .diff-table { width: 100%; border-collapse: collapse; font-family: monospace; font-size: 0.8rem; }
  #confirm-modal .diff-table td { padding: 6px 8px; border-bottom: 1px solid #333; vertical-align: top; word-break: break-all; }
  #confirm-modal .diff-table .path { color: #52b788; white-space: nowrap; }
  #confirm-modal .actions { display: flex; gap: 8px; justify-content: flex-end; }
  #confirm-modal .actions button {
    border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 0.9rem;
  }
  #confirm-modal .actions .cancel { background: #533483; color: #fff; }
  #confirm-modal .actions .confirm { background: #e94560; color: #fff; }
  #confirm-modal .actions .confirm.danger { background: #6a040f; }
  #confirm-modal .warn-text { color: #f4a261; margin: 0 0 10px; }
</style>
</head>
<body>
<header><h1>WLED Ambient Lighting — Web Config</h1></header>
<div id="service-bar">
  <span><span id="svc-dot" class="status-dot off"></span><span id="svc-label">Ambient: checking…</span></span>
  <button id="svc-start" class="primary" onclick="startAmbient()">Start ambient</button>
  <button id="svc-stop" onclick="stopAmbient()">Stop ambient</button>
  <button id="svc-shutdown" class="danger" onclick="shutdownPi()">Shutdown Pi</button>
</div>
<nav id="tabs">
  <button class="active" data-tab="preview">Preview</button>
  <button data-tab="perspective">Perspective</button>
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
      <button class="secondary" onclick="clearPoints()">Clear points</button>
      <button class="secondary" onclick="loadSavedPoints()">Load saved</button>
      <button class="secondary" onclick="saveCalibration()">Save calibration</button>
    </div>
    <p style="font-size:0.85rem;color:#aaa">Click <strong>Capture</strong>, then click four corners on panel 1 in order: <strong>TL → TR → BR → BL</strong>. Use <strong>Clear points</strong> to start over.</p>
    <div class="panels">
      <div class="panel"><h3>1. Raw capture — click corners here</h3>
        <div class="img-wrap" id="raw-wrap">
          <img id="img-raw" alt="raw">
          <canvas id="raw-canvas"></canvas>
        </div>
      </div>
      <div class="panel"><h3 id="warped-panel-title">2. Perspective corrected — sampling bands</h3><img id="img-warped" class="no-click" alt="warped"></div>
      <div class="panel"><h3>3. LED colors</h3><img id="img-overlay" class="no-click" alt="overlay"></div>
    </div>
    <div class="meta" id="preview-meta">Click Capture to load preview.</div>
    <div class="cal-points" id="cal-clicked">Clicked (0/4): []</div>
    <div class="cal-points" id="cal-saved"></div>
    <div class="cal-manual">
      <h3>Manual corner coordinates (pixels in raw frame)</h3>
      <table>
        <tr><th>Corner</th><th>X</th><th>Y</th></tr>
        <tr><td>1 — Top-left</td><td><input type="number" id="cal-pt-0-x" min="0"></td><td><input type="number" id="cal-pt-0-y" min="0"></td></tr>
        <tr><td>2 — Top-right</td><td><input type="number" id="cal-pt-1-x" min="0"></td><td><input type="number" id="cal-pt-1-y" min="0"></td></tr>
        <tr><td>3 — Bottom-right</td><td><input type="number" id="cal-pt-2-x" min="0"></td><td><input type="number" id="cal-pt-2-y" min="0"></td></tr>
        <tr><td>4 — Bottom-left</td><td><input type="number" id="cal-pt-3-x" min="0"></td><td><input type="number" id="cal-pt-3-y" min="0"></td></tr>
      </table>
      <button type="button" onclick="applyManualPoints()">Apply to markers</button>
    </div>
  </div>
  <div id="tab-perspective" class="tab"><div class="form-section" id="form-perspective"></div></div>
  <div id="tab-camera" class="tab"><div class="form-section" id="form-camera"></div></div>
  <div id="tab-color" class="tab"><div class="form-section" id="form-color"></div></div>
  <div id="tab-wled" class="tab"><div class="form-section" id="form-wled"></div></div>
  <div id="tab-processing" class="tab"><div class="form-section" id="form-processing"></div></div>
</main>
<div id="confirm-modal" role="dialog" aria-modal="true">
  <div class="dialog">
    <h2 id="confirm-title">Confirm</h2>
    <div class="body" id="confirm-body"></div>
    <div class="actions">
      <button type="button" class="cancel" id="confirm-cancel">Cancel</button>
      <button type="button" class="confirm" id="confirm-ok">Confirm</button>
    </div>
  </div>
</div>
<script>
let config = {};
let clickPoints = [];
let svcPollTimer = null;
async function refreshServiceStatus() {
  try {
    const st = await api('GET', '/api/ambient/status');
    const dot = document.getElementById('svc-dot');
    const label = document.getElementById('svc-label');
    const startBtn = document.getElementById('svc-start');
    const stopBtn = document.getElementById('svc-stop');
    const running = !!st.running;
    dot.className = 'status-dot ' + (running ? 'on' : 'off');
    let text = running ? 'Ambient: running' : 'Ambient: stopped';
    if (st.backend) text += ' (' + st.backend + ')';
    if (st.pid) text += ' pid ' + st.pid;
    if (st.unit) text += ' [' + st.unit + ']';
    label.textContent = text;
    startBtn.disabled = running;
    stopBtn.disabled = !running;
  } catch (e) {
    document.getElementById('svc-label').textContent = 'Ambient: status unavailable';
  }
}
function startServicePoll() {
  refreshServiceStatus();
  if (svcPollTimer) clearInterval(svcPollTimer);
  svcPollTimer = setInterval(refreshServiceStatus, 5000);
}
async function startAmbient() {
  try {
    showBanner('Starting ambient…', 'warn');
    const res = await api('POST', '/api/ambient/start');
    await refreshServiceStatus();
    showBanner(res.already_running ? 'Ambient already running' : 'Ambient started');
  } catch (e) {
    showBanner(e.data?.message || 'Start failed', 'err');
    await refreshServiceStatus();
  }
}
async function stopAmbient() {
  try {
    showBanner('Stopping ambient…', 'warn');
    const res = await api('POST', '/api/ambient/stop');
    await refreshServiceStatus();
    showBanner(res.already_stopped ? 'Ambient already stopped' : 'Ambient stopped — camera free for Capture');
  } catch (e) {
    showBanner(e.data?.message || 'Stop failed', 'err');
    await refreshServiceStatus();
  }
}
function formatValue(v) {
  if (v === undefined) return '(unset)';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
function valuesEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
function diffConfig(oldObj, newObj, prefix) {
  const changes = [];
  const keys = new Set([...Object.keys(oldObj || {}), ...Object.keys(newObj || {})]);
  for (const key of [...keys].sort()) {
    const path = prefix ? prefix + '.' + key : key;
    const oldVal = oldObj ? oldObj[key] : undefined;
    const newVal = newObj ? newObj[key] : undefined;
    if (oldVal && newVal && typeof oldVal === 'object' && typeof newVal === 'object' && !Array.isArray(oldVal)) {
      changes.push(...diffConfig(oldVal, newVal, path));
    } else if (!valuesEqual(oldVal, newVal)) {
      changes.push({ path, from: oldVal, to: newVal });
    }
  }
  return changes;
}
function renderDiffTable(changes) {
  if (!changes.length) return '<p>No changes.</p>';
  let html = '<table class="diff-table"><tr><th>Setting</th><th>Current</th><th>New</th></tr>';
  for (const c of changes) {
    html += `<tr><td class="path">${c.path}</td><td>${formatValue(c.from)}</td><td>${formatValue(c.to)}</td></tr>`;
  }
  return html + '</table>';
}
let _confirmResolve = null;
function showConfirmModal(title, bodyHtml, confirmLabel, danger) {
  return new Promise((resolve) => {
    _confirmResolve = resolve;
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-body').innerHTML = bodyHtml;
    const okBtn = document.getElementById('confirm-ok');
    okBtn.textContent = confirmLabel || 'Confirm';
    okBtn.className = 'confirm' + (danger ? ' danger' : '');
    document.getElementById('confirm-modal').classList.add('open');
  });
}
function closeConfirmModal(result) {
  document.getElementById('confirm-modal').classList.remove('open');
  if (_confirmResolve) { _confirmResolve(result); _confirmResolve = null; }
}
document.getElementById('confirm-cancel').addEventListener('click', () => closeConfirmModal(false));
document.getElementById('confirm-ok').addEventListener('click', () => closeConfirmModal(true));
async function shutdownPi() {
  const body = '<p class="warn-text"><strong>Warning:</strong> This will power off the Raspberry Pi.</p>'
    + '<ul><li>Ambient lighting will be stopped first</li>'
    + '<li>The web UI will become unreachable</li>'
    + '<li>You must power the Pi on again manually</li></ul>';
  const ok = await showConfirmModal('Shutdown Raspberry Pi?', body, 'Shutdown Pi', true);
  if (!ok) return;
  try {
    showBanner('Shutting down Pi…', 'warn');
    await api('POST', '/api/server/shutdown');
    showBanner('Shutdown initiated — Pi is powering off', 'warn');
  } catch (e) {
    showBanner(e.data?.message || 'Shutdown failed (check sudoers for /sbin/shutdown)', 'err');
  }
}
const ts = () => Date.now();
function showBanner(text, kind='ok') {
  const el = document.getElementById('banner');
  el.className = 'msg ' + kind;
  el.textContent = text;
  if (kind === 'ok') setTimeout(() => { el.textContent = ''; el.className = ''; }, 4000);
}
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw { status: r.status, data };
  return data;
}
function refreshImages() {
  const q = '?t=' + ts();
  const img = document.getElementById('img-raw');
  img.onload = () => { syncCanvasSize(); drawMarkers(); };
  img.src = '/api/preview/raw.jpg' + q;
  document.getElementById('img-warped').src = '/api/preview/warped.jpg' + q;
  document.getElementById('img-overlay').src = '/api/preview/overlay.jpg' + q;
}
function syncCanvasSize() {
  const img = document.getElementById('img-raw');
  const canvas = document.getElementById('raw-canvas');
  const wrap = document.getElementById('raw-wrap');
  if (!img.naturalWidth) return;
  canvas.width = img.clientWidth;
  canvas.height = img.clientHeight;
  wrap.style.height = img.clientHeight + 'px';
}
function drawMarkers() {
  const canvas = document.getElementById('raw-canvas');
  const img = document.getElementById('img-raw');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!img.naturalWidth || clickPoints.length === 0) return;
  const sx = canvas.width / img.naturalWidth;
  const sy = canvas.height / img.naturalHeight;
  const toScreen = (p) => [p[0] * sx, p[1] * sy];
  if (clickPoints.length === 4) {
    ctx.strokeStyle = '#00ff00';
    ctx.lineWidth = 2;
    ctx.beginPath();
    const s0 = toScreen(clickPoints[0]);
    ctx.moveTo(s0[0], s0[1]);
    for (let i = 1; i < 4; i++) {
      const s = toScreen(clickPoints[i]);
      ctx.lineTo(s[0], s[1]);
    }
    ctx.closePath();
    ctx.stroke();
  }
  clickPoints.forEach((p, i) => {
    const [x, y] = toScreen(p);
    ctx.fillStyle = '#ff0000';
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 14px system-ui,sans-serif';
    ctx.fillText(String(i + 1), x + 10, y - 6);
  });
}
function updateCalLabels() {
  document.getElementById('cal-clicked').textContent =
    'Clicked (' + clickPoints.length + '/4): ' + JSON.stringify(clickPoints);
  const saved = config.perspective?.points || [];
  document.getElementById('cal-saved').textContent =
    'Saved in config: ' + JSON.stringify(saved);
  syncManualInputsFromPoints();
}
function syncManualInputsFromPoints() {
  const pts = clickPoints.length === 4 ? clickPoints : (config.perspective?.points || []);
  for (let i = 0; i < 4; i++) {
    const xEl = document.getElementById('cal-pt-' + i + '-x');
    const yEl = document.getElementById('cal-pt-' + i + '-y');
    if (!xEl || !yEl) continue;
    if (pts[i]) { xEl.value = pts[i][0]; yEl.value = pts[i][1]; }
    else { xEl.value = ''; yEl.value = ''; }
  }
}
function applyManualPoints() {
  const pts = [];
  const fw = config.camera?.resolution?.[0] || 320;
  const fh = config.camera?.resolution?.[1] || 240;
  for (let i = 0; i < 4; i++) {
    const x = parseInt(document.getElementById('cal-pt-' + i + '-x').value, 10);
    const y = parseInt(document.getElementById('cal-pt-' + i + '-y').value, 10);
    if (Number.isNaN(x) || Number.isNaN(y)) {
      showBanner('Enter valid X/Y for corner ' + (i + 1), 'err'); return;
    }
    if (x < 0 || x >= fw || y < 0 || y >= fh) {
      showBanner('Corner ' + (i + 1) + ' must be within 0..' + (fw - 1) + ', 0..' + (fh - 1), 'err'); return;
    }
    pts.push([x, y]);
  }
  clickPoints = pts;
  drawMarkers();
  updateCalLabels();
  showBanner('Manual points applied — click Save calibration');
}
function renderPreviewMeta(meta) {
  const el = document.getElementById('preview-meta');
  if (!meta.has_cache) { el.innerHTML = 'No preview cached. Click <strong>Capture</strong>.'; updateCalLabels(); return; }
  const t = meta.timing_ms || {};
  let html = '<table><tr><th>Stage</th><th>ms</th></tr>';
  for (const k of ['capture','warp','extract','post_process']) {
    if (t[k] !== undefined) html += `<tr><td>${k}</td><td>${t[k]}</td></tr>`;
  }
  html += `</table><p>LEDs: top ${meta.led_layout.top} + right ${meta.led_layout.right} + bottom ${meta.led_layout.bottom} + left ${meta.led_layout.left} = <strong>${meta.led_total}</strong></p>`;
  if (meta.strip_start) {
    html += `<p>Strip: start <strong>${meta.strip_start}</strong>, direction <strong>${meta.strip_direction || 'cw'}</strong></p>`;
  }
  if (meta.sampling) {
    const sm = meta.sampling;
    html += `<p>Sampling bands: <strong>${sm.depth_h_px}px</strong> (top/bottom) × <strong>${sm.depth_w_px}px</strong> (left/right)`;
    html += sm.show_bands ? ' — <span style="color:#52b788">shown on panel 2</span>' : ' — hidden on panel 2';
    html += '</p><table><tr><th>Side</th><th>LEDs</th><th>Mode</th></tr>';
    for (const side of ['top','right','bottom','left']) {
      const s = sm.sides[side] || {};
      const mode = s.mode === 'no_leds' ? '—' : (s.active ? 'sample' : s.mode);
      html += `<tr><td>${side}</td><td>${s.leds ?? 0}</td><td>${mode}</td></tr>`;
    }
    html += '</table>';
    const title = document.getElementById('warped-panel-title');
    if (title) title.textContent = sm.show_bands
      ? '2. Perspective corrected — cyan=sample, red=disabled fill'
      : '2. Perspective corrected';
  }
  html += '<details><summary>RGB per side</summary><pre>' + JSON.stringify(meta.colors, null, 2) + '</pre></details>';
  el.innerHTML = html;
  if (config.perspective) config.perspective.points = meta.points;
  updateCalLabels();
}
async function captureFrame() {
  try {
    showBanner('Capturing…', 'warn');
    clearPoints(false);
    const meta = await api('POST', '/api/preview/capture');
    refreshImages();
    renderPreviewMeta(meta);
    showBanner('Capture OK — click 4 TV corners on panel 1');
  } catch (e) {
    showBanner(e.data?.message || e.data?.error || 'Capture failed', e.status === 503 ? 'warn' : 'err');
  }
}
async function reprocess() {
  try {
    const meta = await api('POST', '/api/preview/reprocess');
    refreshImages();
    renderPreviewMeta(meta);
    showBanner('Reprocessed');
  } catch (e) { showBanner(e.data?.message || 'Reprocess failed', 'err'); }
}
function pointerToImageCoords(clientX, clientY) {
  const img = document.getElementById('img-raw');
  if (!img.naturalWidth) return null;
  const rect = img.getBoundingClientRect();
  const x = (clientX - rect.left) * (img.naturalWidth / rect.width);
  const y = (clientY - rect.top) * (img.naturalHeight / rect.height);
  return [Math.round(x), Math.round(y)];
}
function onRawPointer(ev) {
  if (clickPoints.length >= 4) {
    showBanner('Already have 4 points — Clear points to redo.', 'warn');
    return;
  }
  const coords = pointerToImageCoords(ev.clientX, ev.clientY);
  if (!coords) { showBanner('Wait for image to load.', 'warn'); return; }
  clickPoints.push(coords);
  drawMarkers();
  updateCalLabels();
  if (clickPoints.length === 4) showBanner('4 corners set — click Save calibration', 'ok');
}
function clearPoints(showMsg=true) {
  clickPoints = [];
  drawMarkers();
  updateCalLabels();
  if (showMsg) showBanner('Points cleared — click 4 corners on panel 1');
}
function loadSavedPoints() {
  clickPoints = (config.perspective?.points || []).map(p => [...p]);
  drawMarkers();
  updateCalLabels();
  showBanner('Loaded saved points — edit or Clear to redo');
}
async function saveCalibration() {
  if (clickPoints.length !== 4) { showBanner('Click exactly 4 corners first (' + clickPoints.length + '/4).', 'err'); return; }
  const oldPts = config.perspective?.points || [];
  const changes = [];
  for (let i = 0; i < 4; i++) {
    const oldP = oldPts[i];
    const newP = clickPoints[i];
    if (!valuesEqual(oldP, newP)) {
      changes.push({ path: 'perspective.points[' + i + ']', from: oldP, to: newP });
    }
  }
  if (!changes.length) { showBanner('No changes to save'); return; }
  const ok = await showConfirmModal(
    'Save calibration?',
    '<p>The following corner coordinates will be written to config.yaml:</p>' + renderDiffTable(changes),
    'Confirm save'
  );
  if (!ok) return;
  try {
    const meta = await api('POST', '/api/calibration', { points: clickPoints });
    refreshImages();
    renderPreviewMeta(meta);
    config.perspective.points = meta.points;
    updateCalLabels();
    showBanner('Calibration saved');
  } catch (e) { showBanner(JSON.stringify(e.data?.fields || e.data) || 'Save failed', 'err'); }
}
function fieldId(section, key) { return section + '-' + key.replace(/\./g, '-'); }
function fieldHtml(section, key, spec, value) {
  const id = fieldId(section, key);
  const label = spec.label || key;
  if (spec.type === 'bool') return `<div class="field"><label><input type="checkbox" id="${id}" ${value ? 'checked' : ''}> ${label}</label></div>`;
  if (spec.type === 'enum') return `<div class="field"><label>${label}</label><select id="${id}">${spec.options.map(o => `<option value="${o}" ${o===value?'selected':''}>${o}</option>`).join('')}</select></div>`;
  if (spec.type === 'resolution') { const v = value || [320, 240]; return `<div class="field row2"><div class="field"><label>${label} W</label><input type="number" id="${id}-w" value="${v[0]}"></div><div class="field"><label>H</label><input type="number" id="${id}-h" value="${v[1]}"></div></div>`; }
  if (spec.type === 'float' && spec.max !== undefined) return `<div class="field"><label>${label}: <span id="${id}-v">${value}</span></label><input type="range" id="${id}" min="${spec.min}" max="${spec.max}" step="${spec.step||0.1}" value="${value}" oninput="document.getElementById('${id}-v').textContent=this.value"></div>`;
  return `<div class="field"><label>${label}</label><input type="${spec.type === 'int' ? 'number' : 'text'}" id="${id}" value="${value ?? ''}"${spec.min !== undefined ? ` min="${spec.min}"` : ''}${spec.max !== undefined ? ` max="${spec.max}"` : ''}></div>`;
}
function readField(spec, id) {
  if (spec.type === 'bool') return document.getElementById(id).checked;
  if (spec.type === 'resolution') return [parseInt(document.getElementById(id + '-w').value, 10), parseInt(document.getElementById(id + '-h').value, 10)];
  if (spec.type === 'float') return parseFloat(document.getElementById(id).value);
  if (spec.type === 'int') return parseInt(document.getElementById(id).value, 10);
  return document.getElementById(id).value;
}
function updateWledTotal() {
  const el = document.getElementById('wled-total');
  if (!el) return;
  let sum = 0;
  for (const side of ['top', 'right', 'bottom', 'left']) {
    const input = document.getElementById(fieldId('wled', 'led_layout.' + side));
    if (input) sum += parseInt(input.value, 10) || 0;
  }
  el.textContent = 'Total LEDs: ' + sum + ' (must match WLED firmware LED count)';
}
function afterBuildForm(section) {
  if (section === 'wled') {
    updateWledTotal();
    for (const side of ['top', 'right', 'bottom', 'left']) {
      const input = document.getElementById(fieldId('wled', 'led_layout.' + side));
      if (input) input.addEventListener('input', updateWledTotal);
    }
  }
}
function buildForm(section, schema, data, containerId) {
  let html = `<h2>${section.charAt(0).toUpperCase() + section.slice(1)}</h2>`;
  if (section === 'perspective') {
    html += '<p class="form-note">TV corner points are set on the <strong>Preview</strong> tab (click or manual X/Y).</p>';
  }
  for (const [key, spec] of Object.entries(schema)) {
    if (spec.type) html += fieldHtml(section, key, spec, data[key]);
    else {
      html += `<h3>${key.replace(/_/g, ' ')}</h3>`;
      for (const [subkey, subspec] of Object.entries(spec)) {
        html += fieldHtml(section, key + '.' + subkey, subspec, (data[key] || {})[subkey]);
      }
    }
  }
  if (section === 'wled') html += '<p id="wled-total" class="form-note"></p>';
  html += `<button onclick="saveSection('${section}')">Save ${section}</button>`;
  document.getElementById(containerId).innerHTML = html;
  afterBuildForm(section);
}
function readSection(section, schema) {
  const out = {};
  for (const [key, spec] of Object.entries(schema)) {
    if (spec.type) out[key] = readField(spec, fieldId(section, key));
    else {
      out[key] = {};
      for (const [subkey, subspec] of Object.entries(spec)) {
        out[key][subkey] = readField(subspec, fieldId(section, key + '.' + subkey));
      }
    }
  }
  return out;
}
async function saveSection(section) {
  try {
    const res = await api('GET', '/api/config');
    const schema = res.schema[section];
    const newSection = readSection(section, schema);
    const oldSection = config[section] || {};
    const changes = diffConfig(oldSection, newSection, section);
    if (!changes.length) { showBanner('No changes to save'); return; }
    const ok = await showConfirmModal(
      'Save ' + section + ' settings?',
      '<p>The following changes will be written to config.yaml:</p>' + renderDiffTable(changes),
      'Confirm save'
    );
    if (!ok) return;
    const body = {}; body[section] = newSection;
    const patchRes = await api('PATCH', '/api/config', body);
    config = patchRes.config;
    if (patchRes.warnings?.length) showBanner(patchRes.warnings.join(' '), 'warn');
    else if (section === 'perspective' || section === 'camera' || section === 'color' || section === 'wled') {
      showBanner(section + ' saved — click Reprocess on Preview tab (restart main.py for live output)');
    } else showBanner(section + ' saved');
  } catch (e) { showBanner(JSON.stringify(e.data?.fields || e.data) || 'Save failed', 'err'); }
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
    clearPoints(false);
    buildForm('perspective', res.schema.perspective, config.perspective, 'form-perspective');
    buildForm('camera', res.schema.camera, config.camera, 'form-camera');
    buildForm('color', res.schema.color, config.color, 'form-color');
    buildForm('wled', res.schema.wled, config.wled, 'form-wled');
    buildForm('processing', res.schema.processing, config.processing, 'form-processing');
    syncManualInputsFromPoints();
    const meta = await api('GET', '/api/preview/meta');
    if (meta.has_cache) { refreshImages(); renderPreviewMeta(meta); }
    else { renderPreviewMeta(meta); updateCalLabels(); }
    const wrap = document.getElementById('raw-wrap');
    wrap.addEventListener('click', onRawPointer);
    wrap.addEventListener('touchstart', (e) => {
      e.preventDefault();
      if (e.touches.length) onRawPointer(e.touches[0]);
    }, { passive: false });
    window.addEventListener('resize', () => { syncCanvasSize(); drawMarkers(); });
    startServicePoll();
  } catch (e) { showBanner('Failed to load config', 'err'); }
}
init();
</script>
</body>
</html>"""


class ServerState:
  """Shared mutable state for the HTTP handler."""

  def __init__(
    self,
    config_path: Path,
    camera_factory: Callable[[dict], Any] | None = None,
    service_manager: AmbientServiceManager | None = None,
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
    self._subprocess_holder: dict[str, Any] = {"proc": None}
    project_root = config_path.resolve().parent.parent
    self.ambient_service = service_manager or AmbientServiceManager(
      project_root,
      self.config,
      config_path,
      self._subprocess_holder,
    )

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
    self.ambient_service.reload_config(self.config)

  def ambient_status(self) -> dict:
    with self.lock:
      self.reload_config()
      return self.ambient_service.status()

  def ambient_start(self) -> dict:
    with self.lock:
      self.reload_config()
      return self.ambient_service.start()

  def ambient_stop(self) -> dict:
    with self.lock:
      self.reload_config()
      return self.ambient_service.stop()

  def _run_shutdown_command(self) -> None:
    """Run sudo shutdown. Raises ServiceControlError on failure."""
    try:
      subprocess.run(
        ["sudo", "shutdown", "-h", "now"],
        timeout=10,
        check=True,
        capture_output=True,
        text=True,
      )
    except FileNotFoundError as exc:
      raise ServiceControlError("sudo or shutdown not found") from exc
    except subprocess.CalledProcessError as exc:
      detail = (exc.stderr or exc.stdout or "").strip() or str(exc)
      raise ServiceControlError(f"Shutdown failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
      raise ServiceControlError("Shutdown command timed out") from exc

  def shutdown_pi(self) -> dict:
    """Stop ambient if running, then schedule Pi power-off."""
    with self.lock:
      try:
        if self.ambient_service.status().get("running"):
          self.ambient_service.stop()
      except ServiceControlError:
        logger.warning("Could not stop ambient before Pi shutdown", exc_info=True)

    def _delayed_shutdown() -> None:
      time.sleep(0.5)
      try:
        self._run_shutdown_command()
      except ServiceControlError as exc:
        logger.error("%s", exc)

    threading.Thread(target=_delayed_shutdown, daemon=True, name="PiShutdown").start()
    return {"ok": True, "message": "Shutting down…"}

  def _store_preview(self, raw: np.ndarray, preview: PreviewResult, capture_ms: float = 0.0) -> None:
    self.raw_frame = raw
    self.preview = preview
    self.capture_ms = capture_ms
    # Plain raw frame for calibration clicks (no server-drawn quad)
    self.jpeg_raw = encode_jpeg(raw)
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
      "strip_start": self.config["wled"].get("strip_start", "top_left"),
      "strip_direction": self.config["wled"].get("strip_direction", "cw"),
      "timing_ms": timing,
      "colors": {"top": top, "right": right, "bottom": bottom, "left": left},
      "sampling": p.sampling_meta,
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
          "ambient": state.ambient_status(),
        })
      elif self.command == "GET" and path == "/api/ambient/status":
        _json_response(self, 200, state.ambient_status())
      elif self.command == "POST" and path == "/api/ambient/start":
        self._handle_ambient_start()
      elif self.command == "POST" and path == "/api/ambient/stop":
        self._handle_ambient_stop()
      elif self.command == "POST" and path == "/api/server/shutdown":
        self._handle_shutdown()
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

    def _handle_ambient_start(self) -> None:
      try:
        result = state.ambient_start()
        _json_response(self, 200, result)
      except ServiceControlError as exc:
        _json_response(self, 500, {"error": "service", "message": str(exc)})

    def _handle_ambient_stop(self) -> None:
      try:
        result = state.ambient_stop()
        _json_response(self, 200, result)
      except ServiceControlError as exc:
        _json_response(self, 500, {"error": "service", "message": str(exc)})

    def _handle_shutdown(self) -> None:
      result = state.shutdown_pi()
      _json_response(self, 200, result)

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
