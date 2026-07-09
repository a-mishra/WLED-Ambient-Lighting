"""Simulated camera source — no Picamera2 or Raspberry Pi required.

Three source modes (configured via simulator.camera.source):
  video     — plays an MP4/AVI file; loops when it reaches the end
  image     — loads a single JPEG/PNG and returns it every frame
  synthetic — generates frames algorithmically:
                gradient  : slow hue rotation across the frame
                colorbar  : six solid color bands (R, Y, G, C, B, M)
                solid     : single flat color from simulator.camera.synthetic.color
                noise     : random RGB noise

A background thread updates _frame at the configured simulator.camera.fps rate
so the interface is identical to PiCamera (get_latest_frame() never blocks).
"""

import threading
import time
import logging
import numpy as np
import cv2
from pathlib import Path

from ..base import CameraBase

logger = logging.getLogger(__name__)


class SimCamera(CameraBase):
    """Config-driven simulated camera source."""

    def __init__(self, config: dict) -> None:
        cam_cfg = config["camera"]
        sim_cfg = config["simulator"]["camera"]

        self._resolution: tuple[int, int] = tuple(cam_cfg["resolution"])  # (W, H)
        self._w, self._h = self._resolution
        self._source: str = sim_cfg.get("source", "synthetic")
        self._loop: bool = sim_cfg.get("loop", True)
        self._fps: float = float(sim_cfg.get("fps", 24))
        self._period: float = 1.0 / self._fps

        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = True
        self._frame_index: int = 0  # used by synthetic generators

        # Source-specific setup
        self._cap: cv2.VideoCapture | None = None
        self._static_frame: np.ndarray | None = None

        if self._source == "video":
            path = sim_cfg.get("video_path", "")
            if not Path(path).exists():
                logger.warning("Video file not found: %s — falling back to gradient", path)
                self._source = "synthetic"
            else:
                self._cap = cv2.VideoCapture(path)

        elif self._source == "image":
            path = sim_cfg.get("image_path", "")
            img = cv2.imread(path)
            if img is None:
                logger.warning("Image file not found: %s — falling back to gradient", path)
                self._source = "synthetic"
            else:
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                self._static_frame = cv2.resize(img_rgb, self._resolution)

        self._synthetic_cfg = sim_cfg.get("synthetic", {})
        self._pattern: str = self._synthetic_cfg.get("pattern", "gradient")
        _solid = self._synthetic_cfg.get("color", [255, 255, 255])
        self._solid_color: tuple[int, int, int] = tuple(int(c) for c in _solid)

        self._thread = threading.Thread(
            target=self._generate_loop, daemon=True, name="SimCameraThread"
        )
        self._thread.start()
        logger.info("SimCamera started: source=%s %dx%d @ %.1ffps", self._source, self._w, self._h, self._fps)

    # ------------------------------------------------------------------
    # Background generation loop
    # ------------------------------------------------------------------

    def _generate_loop(self) -> None:
        while self._running:
            t0 = time.perf_counter()
            frame = self._next_frame()
            if frame is not None:
                with self._lock:
                    self._frame = frame
                    self._frame_index += 1
            elapsed = time.perf_counter() - t0
            time.sleep(max(0.0, self._period - elapsed))

    def _next_frame(self) -> np.ndarray | None:
        if self._source == "video":
            return self._read_video_frame()
        if self._source == "image":
            return self._static_frame
        return self._generate_synthetic()

    def _read_video_frame(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            if self._loop:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self._cap.read()
            if not ret:
                return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return cv2.resize(rgb, self._resolution)

    def _generate_synthetic(self) -> np.ndarray:
        if self._pattern == "gradient":
            return self._gradient_frame()
        if self._pattern == "colorbar":
            return self._colorbar_frame()
        if self._pattern == "solid":
            frame = np.full((self._h, self._w, 3), self._solid_color, dtype=np.uint8)
            return frame
        # noise
        return np.random.randint(0, 256, (self._h, self._w, 3), dtype=np.uint8)

    def _gradient_frame(self) -> np.ndarray:
        """Slowly rotating full-hue gradient — good for visualizing edge extraction."""
        hue_offset = (self._frame_index * 0.5) % 180  # degrees, slow rotation
        # Horizontal hue gradient
        hue_row = np.linspace(hue_offset, hue_offset + 180, self._w, dtype=np.float32) % 180
        hue = np.tile(hue_row, (self._h, 1)).astype(np.uint8)
        sat = np.full((self._h, self._w), 220, dtype=np.uint8)
        val = np.full((self._h, self._w), 200, dtype=np.uint8)
        hsv = np.stack([hue, sat, val], axis=2)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

    def _colorbar_frame(self) -> np.ndarray:
        """Six-color SMPTE-style bars — useful for testing color accuracy."""
        colors = [
            (192, 192, 192),  # white
            (192, 192,   0),  # yellow
            (  0, 192, 192),  # cyan
            (  0, 192,   0),  # green
            (192,   0, 192),  # magenta
            (192,   0,   0),  # red
            (  0,   0, 192),  # blue
        ]
        frame = np.zeros((self._h, self._w, 3), dtype=np.uint8)
        seg_w = self._w // len(colors)
        for i, c in enumerate(colors):
            frame[:, i * seg_w : (i + 1) * seg_w] = c
        return frame

    # ------------------------------------------------------------------
    # CameraBase interface
    # ------------------------------------------------------------------

    def get_latest_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._frame

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
        logger.info("SimCamera closed.")
