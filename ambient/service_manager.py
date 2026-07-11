"""Start/stop the ambient lighting pipeline (main.py).

Prefers systemd when ``processing.ambient_service_unit`` is installed;
falls back to a child subprocess when no unit is available (dev / Windows).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ServiceControlError(RuntimeError):
  """Raised when start/stop fails."""


class AmbientServiceManager:
  """Control main.py via systemd or a managed subprocess."""

  def __init__(
    self,
    project_root: Path,
    config: dict,
    config_path: Path,
    subprocess_holder: dict[str, Any],
  ) -> None:
    proc = config.get("processing", {})
    self._unit: str = str(proc.get("ambient_service_unit", "wled-ambient.service")).strip()
    self._use_systemd_user: bool = bool(proc.get("ambient_use_systemd_user", True))
    self._project_root = project_root
    self._config_path = config_path
    self._holder = subprocess_holder
    self._systemd_checked: bool | None = None

  def reload_config(self, config: dict) -> None:
    proc = config.get("processing", {})
    self._unit = str(proc.get("ambient_service_unit", "wled-ambient.service")).strip()
    self._use_systemd_user = bool(proc.get("ambient_use_systemd_user", True))
    self._systemd_checked = None

  def _systemctl_cmd(self, *args: str) -> list[str]:
    cmd = ["systemctl"]
    if self._use_systemd_user:
      cmd.append("--user")
    cmd.extend(args)
    return cmd

  def _run_systemctl(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
      return subprocess.run(
        self._systemctl_cmd(*args),
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
      )
    except FileNotFoundError as exc:
      raise ServiceControlError("systemctl not found") from exc
    except subprocess.TimeoutExpired as exc:
      raise ServiceControlError("systemctl timed out") from exc
    except subprocess.CalledProcessError as exc:
      detail = (exc.stderr or exc.stdout or "").strip() or str(exc)
      raise ServiceControlError(detail) from exc

  def _systemd_available(self) -> bool:
    if not self._unit:
      return False
    if self._systemd_checked is not None:
      return self._systemd_checked
    try:
      result = self._run_systemctl("cat", self._unit, check=False)
      self._systemd_checked = result.returncode == 0
    except ServiceControlError:
      self._systemd_checked = False
    return self._systemd_checked

  def status(self) -> dict:
    if self._systemd_available():
      active = self._run_systemctl("is-active", self._unit, check=False)
      state = active.stdout.strip() or "inactive"
      running = state == "active"
      out: dict[str, Any] = {
        "running": running,
        "backend": "systemd",
        "unit": self._unit,
        "state": state,
      }
      if running:
        try:
          pid_res = self._run_systemctl("show", self._unit, "-p", "MainPID", "--value", check=False)
          pid = int(pid_res.stdout.strip() or "0")
          if pid > 0:
            out["pid"] = pid
        except ValueError:
          pass
      return out

    proc: subprocess.Popen | None = self._holder.get("proc")
    running = proc is not None and proc.poll() is None
    return {
      "running": running,
      "backend": "subprocess",
      "unit": None,
      "state": "active" if running else "inactive",
      "pid": proc.pid if running and proc else None,
    }

  def start(self) -> dict:
    current = self.status()
    if current["running"]:
      return {"ok": True, "already_running": True, **current}

    if self._systemd_available():
      self._run_systemctl("start", self._unit)
      time.sleep(0.3)
      result = self.status()
      if not result["running"]:
        raise ServiceControlError(f"Failed to start {self._unit}")
      logger.info("Started ambient service via systemd: %s", self._unit)
      return {"ok": True, **result}

    python = sys.executable
    main_py = self._project_root / "main.py"
    if not main_py.is_file():
      raise ServiceControlError(f"main.py not found at {main_py}")

    proc = subprocess.Popen(
      [python, str(main_py), "--config", str(self._config_path)],
      cwd=str(self._project_root),
      start_new_session=True,
    )
    self._holder["proc"] = proc
    time.sleep(0.5)
    if proc.poll() is not None:
      self._holder["proc"] = None
      raise ServiceControlError("main.py exited immediately after start")
    logger.info("Started ambient subprocess pid=%d", proc.pid)
    return {"ok": True, **self.status()}

  def stop(self) -> dict:
    current = self.status()
    if not current["running"]:
      return {"ok": True, "already_stopped": True, **current}

    if self._systemd_available():
      self._run_systemctl("stop", self._unit)
      time.sleep(0.3)
      result = self.status()
      if result["running"]:
        raise ServiceControlError(f"Failed to stop {self._unit}")
      logger.info("Stopped ambient service via systemd: %s", self._unit)
      return {"ok": True, **result}

    proc: subprocess.Popen | None = self._holder.get("proc")
    if proc is None or proc.poll() is not None:
      self._holder["proc"] = None
      return {"ok": True, **self.status()}

    if os.name == "nt":
      proc.terminate()
    else:
      os.killpg(proc.pid, signal.SIGINT)
    try:
      proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
      if os.name == "nt":
        proc.kill()
      else:
        os.killpg(proc.pid, signal.SIGKILL)
      proc.wait(timeout=5)
    self._holder["proc"] = None
    logger.info("Stopped ambient subprocess")
    return {"ok": True, **self.status()}
