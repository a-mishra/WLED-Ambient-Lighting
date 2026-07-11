"""Tests for ambient service start/stop control."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config import load_config
from ambient.service_manager import AmbientServiceManager

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


@pytest.fixture
def manager():
  cfg = load_config(CONFIG_PATH)
  cfg["processing"]["ambient_service_unit"] = "wled-ambient.service"
  holder: dict = {"proc": None}
  return AmbientServiceManager(
    Path(__file__).parent.parent,
    cfg,
    CONFIG_PATH,
    holder,
  ), holder


def test_status_systemd_inactive(manager):
  mgr, _ = manager

  def fake_run(cmd, **kwargs):
    result = MagicMock()
    result.returncode = 0
    if "is-active" in cmd:
      result.stdout = "inactive\n"
    elif "cat" in cmd:
      result.stdout = "[Unit]\n"
    else:
      result.stdout = ""
    return result

  with patch("ambient.service_manager.subprocess.run", side_effect=fake_run):
    st = mgr.status()
  assert st["running"] is False
  assert st["backend"] == "systemd"
  assert st["unit"] == "wled-ambient.service"


def test_start_systemd(manager):
  mgr, _ = manager
  calls: list[list[str]] = []

  def fake_run(cmd, **kwargs):
    calls.append(cmd)
    result = MagicMock()
    result.returncode = 0
    if "is-active" in cmd:
      result.stdout = "active\n" if len(calls) > 2 else "inactive\n"
    elif "cat" in cmd:
      result.stdout = "[Unit]\n"
    elif "show" in cmd:
      result.stdout = "1234\n"
    else:
      result.stdout = ""
    return result

  with patch("ambient.service_manager.subprocess.run", side_effect=fake_run):
    with patch("ambient.service_manager.time.sleep"):
      res = mgr.start()
  assert res["ok"] is True
  assert res["running"] is True
  assert any("start" in c for c in calls)


def test_stop_systemd_when_inactive(manager):
  mgr, _ = manager

  def fake_run(cmd, **kwargs):
    result = MagicMock()
    result.returncode = 0
    result.stdout = "inactive\n" if "is-active" in cmd else "[Unit]\n"
    return result

  with patch("ambient.service_manager.subprocess.run", side_effect=fake_run):
    res = mgr.stop()
  assert res["ok"] is True
  assert res["already_stopped"] is True


def test_subprocess_start_and_stop():
  cfg = load_config(CONFIG_PATH)
  cfg["processing"]["ambient_service_unit"] = ""
  holder: dict = {"proc": None}
  mgr = AmbientServiceManager(
    Path(__file__).parent.parent,
    cfg,
    CONFIG_PATH,
    holder,
  )

  fake_proc = MagicMock()
  fake_proc.poll.return_value = None
  fake_proc.pid = 4242

  with patch("ambient.service_manager.subprocess.Popen", return_value=fake_proc) as popen:
    with patch("ambient.service_manager.time.sleep"):
      res = mgr.start()

  assert res["running"] is True
  assert res["backend"] == "subprocess"
  popen.assert_called_once()

  with patch("ambient.service_manager.os.name", "posix"):
    with patch("ambient.service_manager.os.killpg", create=True):
      with patch.object(fake_proc, "wait"):
        fake_proc.poll.return_value = None
        res = mgr.stop()
  assert res["running"] is False
  assert holder["proc"] is None
