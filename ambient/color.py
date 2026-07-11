"""Edge color extraction and post-processing.

Two extraction modes:
  - Default (use_remap=false): receives the already-warped frame; uses cv2.resize
    with INTER_AREA to downsample each edge strip to exactly n_leds colors. Fast
    on a 160×90 output frame.

  - Remap mode (use_remap=true): bypasses full warpPerspective. Pre-computes
    cv2.remap maps at startup for the 4 edge strips only (~5x fewer pixels than a
    full warp). Operates directly on the raw camera frame each loop iteration.

Post-processing pipeline (applied to the LED array — negligible cost):
  1. Saturation boost   — vectorized HSV operation
  2. Combined uint8 LUT — gamma + brightness floor in a single index lookup
  3. Spatial blur       — gaussian_filter1d along the strip axis (optional)
"""

import cv2
import numpy as np
import logging
from scipy.ndimage import gaussian_filter1d

from .edge_sampling import (
  EdgeSamplingConfig,
  disabled_rgb,
  fill_disabled_colors,
  parse_edge_sampling,
)

logger = logging.getLogger(__name__)


class EdgeColorExtractor:
    """Extracts per-LED colors from the edge regions of the TV frame."""

    def __init__(self, config: dict, perspective_matrix: np.ndarray | None = None) -> None:
        color_cfg = config["color"]
        led_layout = config["wled"]["led_layout"]
        persp_cfg = config["perspective"]

        self._n_top: int = led_layout["top"]
        self._n_right: int = led_layout["right"]
        self._n_bottom: int = led_layout["bottom"]
        self._n_left: int = led_layout["left"]
        self._n_total: int = self._n_top + self._n_right + self._n_bottom + self._n_left

        self._out_w, self._out_h = persp_cfg["output_resolution"]
        self._sampling = parse_edge_sampling(color_cfg)
        self._depth_h, self._depth_w = self._sampling.depth_pixels(self._out_w, self._out_h)
        self._brightness_floor: int = int(color_cfg.get("brightness_floor", 0))

        self._use_remap: bool = color_cfg.get("use_remap", False)
        self._sat_boost: float = float(color_cfg.get("saturation_boost", 1.0))
        self._spatial_sigma: float = float(color_cfg.get("spatial_blur_sigma", 0.0))

        self._lut: np.ndarray = self._build_lut(
            float(color_cfg.get("gamma", 2.2)),
            self._brightness_floor,
        )

        if self._use_remap:
            if perspective_matrix is None:
                logger.warning(
                    "use_remap=true but no perspective_matrix provided — "
                    "falling back to warp mode."
                )
                self._use_remap = False
            else:
                self._build_remap_maps(perspective_matrix)

        en = self._sampling.enabled
        logger.info(
            "EdgeColorExtractor ready: %d LEDs, depth=%dpx×%dpx, "
            "enabled top=%s right=%s bottom=%s left=%s, remap=%s",
            self._n_total,
            self._depth_h,
            self._depth_w,
            en["top"],
            en["right"],
            en["bottom"],
            en["left"],
            self._use_remap,
        )

    @property
    def sampling_config(self) -> EdgeSamplingConfig:
        return self._sampling

    # ------------------------------------------------------------------
    # Startup computations
    # ------------------------------------------------------------------

    def _build_lut(self, gamma: float, brightness_floor: int) -> np.ndarray:
        """Pre-compute a 256-entry uint8 LUT encoding gamma + brightness floor."""
        x = np.arange(256, dtype=np.float32) / 255.0
        corrected = np.power(x, 1.0 / gamma) * 255.0
        corrected = np.maximum(corrected, brightness_floor)
        return corrected.clip(0, 255).astype(np.uint8)

    def _side_active(self, side: str, n_leds: int) -> bool:
        return n_leds > 0 and self._sampling.enabled.get(side, True)

    def _disabled_block(self, side: str, n_leds: int) -> np.ndarray:
        rgb = disabled_rgb(side, self._sampling, self._brightness_floor)
        return fill_disabled_colors(n_leds, rgb)

    def _build_remap_maps(self, forward_matrix: np.ndarray) -> None:
        """Pre-compute cv2.remap float32 maps for enabled edge strips."""
        M_inv = np.linalg.inv(forward_matrix)

        def _make_maps(col_coords: np.ndarray, row_coords: np.ndarray):
            gx, gy = np.meshgrid(col_coords, row_coords)
            pts = np.stack([gx.ravel(), gy.ravel(), np.ones(gx.size)], axis=0).astype(np.float64)
            raw = M_inv @ pts
            raw_x = (raw[0] / raw[2]).reshape(len(row_coords), len(col_coords)).astype(np.float32)
            raw_y = (raw[1] / raw[2]).reshape(len(row_coords), len(col_coords)).astype(np.float32)
            return raw_x, raw_y

        all_cols = np.arange(self._out_w, dtype=np.float64)
        all_rows = np.arange(self._out_h, dtype=np.float64)

        if self._side_active("top", self._n_top):
            top_rows = np.arange(self._depth_h, dtype=np.float64)
            self._remap_top = _make_maps(all_cols, top_rows)
        if self._side_active("bottom", self._n_bottom):
            bot_rows = np.arange(self._out_h - self._depth_h, self._out_h, dtype=np.float64)
            self._remap_bot = _make_maps(all_cols, bot_rows)
        if self._side_active("left", self._n_left):
            left_cols = np.arange(self._depth_w, dtype=np.float64)
            self._remap_left = _make_maps(left_cols, all_rows)
        if self._side_active("right", self._n_right):
            right_cols = np.arange(self._out_w - self._depth_w, self._out_w, dtype=np.float64)
            self._remap_right = _make_maps(right_cols, all_rows)

    # ------------------------------------------------------------------
    # Per-frame extraction
    # ------------------------------------------------------------------

    def extract(self, frame: np.ndarray) -> np.ndarray:
        """Extract edge colors and return ndarray of shape (n_total, 3) uint8.

        Strip order: top (L→R) → right (T→B) → bottom (R→L) → left (B→T).
        """
        if self._use_remap:
            return self._extract_remap(frame)
        return self._extract_warp(frame)

    def _extract_warp(self, warped: np.ndarray) -> np.ndarray:
        h, w = warped.shape[:2]
        parts: list[np.ndarray] = []

        if self._n_top > 0:
            if self._side_active("top", self._n_top):
                top_strip = warped[: self._depth_h, :, :]
                parts.append(
                    cv2.resize(top_strip, (self._n_top, 1), interpolation=cv2.INTER_AREA).reshape(
                        self._n_top, 3
                    )
                )
            else:
                parts.append(self._disabled_block("top", self._n_top))

        if self._n_right > 0:
            if self._side_active("right", self._n_right):
                right_strip = warped[:, w - self._depth_w :, :]
                parts.append(
                    cv2.resize(right_strip, (1, self._n_right), interpolation=cv2.INTER_AREA).reshape(
                        self._n_right, 3
                    )
                )
            else:
                parts.append(self._disabled_block("right", self._n_right))

        if self._n_bottom > 0:
            if self._side_active("bottom", self._n_bottom):
                bot_strip = warped[h - self._depth_h :, ::-1, :]
                parts.append(
                    cv2.resize(bot_strip, (self._n_bottom, 1), interpolation=cv2.INTER_AREA).reshape(
                        self._n_bottom, 3
                    )
                )
            else:
                parts.append(self._disabled_block("bottom", self._n_bottom))

        if self._n_left > 0:
            if self._side_active("left", self._n_left):
                left_strip = warped[::-1, : self._depth_w, :]
                parts.append(
                    cv2.resize(left_strip, (1, self._n_left), interpolation=cv2.INTER_AREA).reshape(
                        self._n_left, 3
                    )
                )
            else:
                parts.append(self._disabled_block("left", self._n_left))

        return np.concatenate(parts, axis=0)

    def _extract_remap(self, raw: np.ndarray) -> np.ndarray:
        def _remap_resize(maps, n_leds, dsize):
            strip = cv2.remap(raw, maps[0], maps[1], cv2.INTER_NEAREST)
            return cv2.resize(strip, dsize, interpolation=cv2.INTER_AREA).reshape(n_leds, 3)

        parts: list[np.ndarray] = []

        if self._n_top > 0:
            if self._side_active("top", self._n_top):
                parts.append(_remap_resize(self._remap_top, self._n_top, (self._n_top, 1)))
            else:
                parts.append(self._disabled_block("top", self._n_top))

        if self._n_right > 0:
            if self._side_active("right", self._n_right):
                parts.append(_remap_resize(self._remap_right, self._n_right, (1, self._n_right)))
            else:
                parts.append(self._disabled_block("right", self._n_right))

        if self._n_bottom > 0:
            if self._side_active("bottom", self._n_bottom):
                bot_strip = cv2.remap(raw, self._remap_bot[0], self._remap_bot[1], cv2.INTER_NEAREST)
                parts.append(
                    cv2.resize(bot_strip[:, ::-1, :], (self._n_bottom, 1), interpolation=cv2.INTER_AREA).reshape(
                        self._n_bottom, 3
                    )
                )
            else:
                parts.append(self._disabled_block("bottom", self._n_bottom))

        if self._n_left > 0:
            if self._side_active("left", self._n_left):
                left_strip = cv2.remap(raw, self._remap_left[0], self._remap_left[1], cv2.INTER_NEAREST)
                parts.append(
                    cv2.resize(left_strip[::-1, :, :], (1, self._n_left), interpolation=cv2.INTER_AREA).reshape(
                        self._n_left, 3
                    )
                )
            else:
                parts.append(self._disabled_block("left", self._n_left))

        return np.concatenate(parts, axis=0)

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def post_process(self, colors: np.ndarray) -> np.ndarray:
        result = colors.astype(np.uint8)

        if self._sat_boost != 1.0:
            result = self._apply_saturation(result, self._sat_boost)

        result = self._lut[result]

        if self._spatial_sigma > 0.0:
            result = gaussian_filter1d(
                result.astype(np.float32), self._spatial_sigma, axis=0
            ).clip(0, 255).astype(np.uint8)

        return result

    @staticmethod
    def _apply_saturation(colors: np.ndarray, boost: float) -> np.ndarray:
        img = colors.reshape(1, -1, 3)
        hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * boost, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).reshape(-1, 3)

    @property
    def n_total(self) -> int:
        return self._n_total
