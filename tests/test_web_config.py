"""Tests for web_config HTTP server (no real camera)."""

import json
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config_schema import CameraBusyError
from ambient.service_manager import AmbientServiceManager, ServiceControlError
from tools.web_config import JPEG_SOI, ServerState, make_handler
from http.server import ThreadingHTTPServer

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


class _FakeCamera:
  def __init__(self, config: dict, frame: np.ndarray | None = None, fail: bool = False) -> None:
    self._frame = frame
    self._fail = fail

  def get_latest_frame(self) -> np.ndarray | None:
    if self._fail:
      raise IndexError("list index out of range")
    return self._frame

  def close(self) -> None:
    pass


def _synthetic_frame(w: int = 320, h: int = 240) -> np.ndarray:
  return np.full((h, w, 3), 128, dtype=np.uint8)


@pytest.fixture
def frame():
  return _synthetic_frame()


class _FakeAmbientService:
  def __init__(self) -> None:
    self.running = False

  def reload_config(self, config: dict) -> None:
    pass

  def status(self) -> dict:
    return {
      "running": self.running,
      "backend": "test",
      "state": "active" if self.running else "inactive",
    }

  def start(self) -> dict:
    self.running = True
    return {"ok": True, **self.status()}

  def stop(self) -> dict:
    self.running = False
    return {"ok": True, **self.status()}


@pytest.fixture
def server_state(frame, tmp_path):
  import shutil
  cfg_copy = tmp_path / "config.yaml"
  shutil.copy(CONFIG_PATH, cfg_copy)
  fake_ambient = _FakeAmbientService()
  state = ServerState(
    cfg_copy,
    camera_factory=lambda c: _FakeCamera(c, frame=frame),
    service_manager=fake_ambient,  # type: ignore[arg-type]
  )
  return state


def test_server_starts_without_camera(server_state):
  assert server_state.raw_frame is None
  assert server_state.preview is None


def test_capture_and_reprocess(server_state, frame):
  meta = server_state.capture_and_process()
  assert meta["has_cache"] is True
  assert server_state.jpeg_raw is not None
  assert server_state.jpeg_raw[:2] == JPEG_SOI

  meta2 = server_state.reprocess()
  assert meta2["has_cache"] is True


def test_reprocess_without_cache_fails(server_state):
  with pytest.raises(RuntimeError, match="No cached frame"):
    server_state.reprocess()


def test_capture_camera_busy(server_state):
  busy_state = ServerState(
    server_state.config_path,
    camera_factory=lambda c: _FakeCamera(c, fail=True),
  )
  with pytest.raises(CameraBusyError):
    busy_state.capture_and_process()


def test_calibration_save(server_state):
  server_state.capture_and_process()
  meta = server_state.save_calibration([[10, 10], [200, 10], [200, 100], [10, 100]])
  assert len(meta["points"]) == 4


def test_patch_config(server_state):
  result = server_state.patch_config({"wled": {"ip": "10.0.0.5"}})
  assert result["config"]["wled"]["ip"] == "10.0.0.5"


def test_idle_release_cache(server_state, frame):
  server_state.capture_and_process()
  assert server_state.raw_frame is not None
  server_state.release_cache()
  assert server_state.raw_frame is None


def test_shutdown_pi_stops_ambient(server_state, monkeypatch):
  server_state.ambient_service.start()
  assert server_state.ambient_service.running is True
  called = []

  def fake_shutdown():
    called.append(True)

  monkeypatch.setattr(server_state, "_run_shutdown_command", fake_shutdown)
  result = server_state.shutdown_pi()
  assert result["ok"] is True
  assert server_state.ambient_service.running is False
  time.sleep(0.7)
  assert called == [True]


def test_run_shutdown_command_permission_denied(server_state, monkeypatch):
  import subprocess

  def fake_run(*args, **kwargs):
    raise subprocess.CalledProcessError(1, "sudo", stderr="permission denied")

  monkeypatch.setattr(subprocess, "run", fake_run)
  with pytest.raises(ServiceControlError, match="Shutdown failed"):
    server_state._run_shutdown_command()


def test_shutdown_endpoint(server_state, monkeypatch):
  port = 18766
  monkeypatch.setattr(server_state, "_run_shutdown_command", lambda: None)
  server = _start_test_server(server_state, port)
  base = f"http://127.0.0.1:{port}"
  try:
    req = Request(base + "/api/server/shutdown", method="POST", data=b"")
    with urlopen(req) as r:
      data = json.loads(r.read())
      assert data["ok"] is True
  finally:
    server.shutdown()
    server.server_close()


def _start_test_server(state, port: int) -> ThreadingHTTPServer:
  handler = make_handler(state)
  server = ThreadingHTTPServer(("127.0.0.1", port), handler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  time.sleep(0.1)
  return server


def test_http_endpoints(server_state, frame):
  port = 18765
  server = _start_test_server(server_state, port)
  base = f"http://127.0.0.1:{port}"

  try:
    with urlopen(base + "/api/status") as r:
      data = json.loads(r.read())
      assert data["has_cache"] is False
      assert data["ambient"]["running"] is False

    req = Request(base + "/api/ambient/start", method="POST", data=b"")
    with urlopen(req) as r:
      st = json.loads(r.read())
      assert st["running"] is True

    req = Request(base + "/api/ambient/stop", method="POST", data=b"")
    with urlopen(req) as r:
      st = json.loads(r.read())
      assert st["running"] is False

    req = Request(base + "/api/preview/capture", method="POST", data=b"")
    with urlopen(req) as r:
      meta = json.loads(r.read())
      assert meta["has_cache"] is True

    with urlopen(base + "/api/preview/raw.jpg") as r:
      assert r.read()[:2] == JPEG_SOI

    patch = json.dumps({"processing": {"benchmark_mode": True}}).encode()
    req = Request(
      base + "/api/config", data=patch, method="PATCH",
      headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as r:
      res = json.loads(r.read())
      assert res["ok"] is True

    with urlopen(base + "/api/config") as r:
      cfg = json.loads(r.read())
      assert "rgb_swap" in cfg["schema"]["camera"]
      assert "strip_start" in cfg["schema"]["wled"]
      assert "output_resolution" in cfg["schema"]["perspective"]

    patch = json.dumps({"perspective": {"output_resolution": [160, 90]}}).encode()
    req = Request(
      base + "/api/config", data=patch, method="PATCH",
      headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as r:
      res = json.loads(r.read())
      assert res["ok"] is True

    bad = json.dumps({"camera": {"analogue_gain": 999}}).encode()
    req = Request(
      base + "/api/config", data=bad, method="PATCH",
      headers={"Content-Type": "application/json"},
    )
    with pytest.raises(HTTPError) as exc:
      urlopen(req)
    assert exc.value.code == 400
  finally:
    server.shutdown()
    server.server_close()
