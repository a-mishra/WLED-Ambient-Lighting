"""Picamera2 camera source with threaded double-buffer capture.

The background thread captures frames continuously so get_latest_frame() never
blocks the main processing loop waiting for a camera I/O round-trip.
"""

import threading
import logging

import cv2
import numpy as np

try:
    from picamera2 import Picamera2
    _PICAMERA2_AVAILABLE = True
except ImportError:
    _PICAMERA2_AVAILABLE = False

from .base import CameraBase

logger = logging.getLogger(__name__)


class PiCamera(CameraBase):
    """Picamera2 wrapper with a continuous background capture thread."""

    def __init__(self, config: dict) -> None:
        if not _PICAMERA2_AVAILABLE:
            raise RuntimeError(
                "picamera2 is not installed or not running on Raspberry Pi. "
                "Set simulator.camera.enabled=true to use SimCamera instead."
            )

        cam_cfg = config["camera"]
        resolution = tuple(cam_cfg["resolution"])
        self._rgb_swap: bool = bool(cam_cfg.get("rgb_swap", False))

        self._picam2 = Picamera2()
        preview_cfg = self._picam2.create_preview_configuration(
            main={"format": "RGB888", "size": resolution}
        )
        self._picam2.configure(preview_cfg)
        self._picam2.set_controls(
            {
                "AwbEnable": cam_cfg["awb_enable"],
                "AeEnable": cam_cfg["ae_enable"],
                "AnalogueGain": float(cam_cfg["analogue_gain"]),
                "ExposureTime": int(cam_cfg["exposure_time"]),
            }
        )
        self._picam2.start()
        logger.info("PiCamera started at %s rgb_swap=%s", resolution, self._rgb_swap)

        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="CameraThread")
        self._thread.start()

    def _capture_loop(self) -> None:
        while self._running:
            try:
                frame = self._picam2.capture_array()
                if self._rgb_swap:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self._lock:
                    self._frame = frame
            except Exception as exc:
                logger.error("Camera capture error: %s", exc)

    def get_latest_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._frame

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)
        self._picam2.close()
        logger.info("PiCamera closed.")
