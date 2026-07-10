"""Edge color extraction and post-processing.

Two extraction modes:
  - Default (use_remap=false): receives the already-warped frame; uses cv2.resize
    with INTER_AREA to downsample each edge strip to exactly n_leds colors. Fast
    on a 160×90 output frame.

  - Remap mode (use_remap=true): bypasses full warpPerspective. Pre-computes
    cv2.remap maps at startup for the 4 edge strips only (~5x fewer pixels than a
    full warp). Operates directly on the raw camera frame each loop iteration.

Post-processing pipeline (applied to the 268-value LED array — negligible cost):
  1. Saturation boost   — vectorized HSV operation
  2. Combined uint8 LUT — gamma + brightness floor in a single index lookup
  3. Spatial blur       — gaussian_filter1d along the strip axis (optional)
"""

import cv2
import numpy as np
import logging
from scipy.ndimage import gaussian_filter1d

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
        self._edge_depth: float = color_cfg["edge_depth"]

        # Depth in pixels for each axis
        self._depth_h: int = max(1, int(self._out_h * self._edge_depth))
        self._depth_w: int = max(1, int(self._out_w * self._edge_depth))

        self._use_remap: bool = color_cfg.get("use_remap", False)
        self._sat_boost: float = float(color_cfg.get("saturation_boost", 1.0))
        self._spatial_sigma: float = float(color_cfg.get("spatial_blur_sigma", 0.0))

        # Combined uint8 LUT: gamma + brightness floor applied in one index lookup
        self._lut: np.ndarray = self._build_lut(
            float(color_cfg.get("gamma", 2.2)),
            int(color_cfg.get("brightness_floor", 0)),
        )

        # Remap maps are built once at construction if use_remap is enabled
        if self._use_remap:
            if perspective_matrix is None:
                logger.warning(
                    "use_remap=true but no perspective_matrix provided — "
                    "falling back to warp mode."
                )
                self._use_remap = False
            else:
                self._build_remap_maps(perspective_matrix)

        logger.info(
            "EdgeColorExtractor ready: %d LEDs, depth=%dpx×%dpx, remap=%s",
            self._n_total,
            self._depth_h,
            self._depth_w,
            self._use_remap,
        )

    # ------------------------------------------------------------------
    # Startup computations
    # ------------------------------------------------------------------

    def _build_lut(self, gamma: float, brightness_floor: int) -> np.ndarray:
        """Pre-compute a 256-entry uint8 LUT encoding gamma + brightness floor.

        Applied per-frame as a single numpy index operation: lut[colors].
        """
        x = np.arange(256, dtype=np.float32) / 255.0
        corrected = np.power(x, 1.0 / gamma) * 255.0
        corrected = np.maximum(corrected, brightness_floor)
        return corrected.clip(0, 255).astype(np.uint8)

    def _build_remap_maps(self, forward_matrix: np.ndarray) -> None:
        """Pre-compute cv2.remap float32 maps for the 4 edge strips.

        For each output-space edge pixel, the inverse perspective transform gives
        the corresponding raw-frame coordinate. cv2.remap uses these maps to
        sample the raw frame directly — bypassing warpPerspective on the interior.
        """
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
        top_rows = np.arange(self._depth_h, dtype=np.float64)
        bot_rows = np.arange(self._out_h - self._depth_h, self._out_h, dtype=np.float64)
        left_cols = np.arange(self._depth_w, dtype=np.float64)
        right_cols = np.arange(self._out_w - self._depth_w, self._out_w, dtype=np.float64)

        self._remap_top = _make_maps(all_cols, top_rows)
        self._remap_bot = _make_maps(all_cols, bot_rows)
        self._remap_left = _make_maps(left_cols, all_rows)
        self._remap_right = _make_maps(right_cols, all_rows)

    # ------------------------------------------------------------------
    # Per-frame extraction
    # ------------------------------------------------------------------

    def extract(self, frame: np.ndarray) -> np.ndarray:
        """Extract edge colors and return ndarray of shape (n_total, 3) uint8.

        Strip order: top (L→R) → right (T→B) → bottom (R→L) → left (B→T).

        Args:
            frame: warped output frame when use_remap=False;
                   raw camera frame when use_remap=True.
        """
        if self._use_remap:
            return self._extract_remap(frame)
        return self._extract_warp(frame)

    def _extract_warp(self, warped: np.ndarray) -> np.ndarray:
        """Extract from the already-warped frame using cv2.resize(INTER_AREA).

        cv2.resize with INTER_AREA performs proper area averaging — equivalent to
        the mean of each segment's pixels — and handles non-integer ratios cleanly.
        """
        h, w = warped.shape[:2]

        parts: list[np.ndarray] = []

        if self._n_top > 0:
            top_strip = warped[: self._depth_h, :, :]
            parts.append(
                cv2.resize(top_strip, (self._n_top, 1), interpolation=cv2.INTER_AREA).reshape(
                    self._n_top, 3
                )
            )

        if self._n_right > 0:
            right_strip = warped[:, w - self._depth_w :, :]
            parts.append(
                cv2.resize(right_strip, (1, self._n_right), interpolation=cv2.INTER_AREA).reshape(
                    self._n_right, 3
                )
            )

        if self._n_bottom > 0:
            bot_strip = warped[h - self._depth_h :, ::-1, :]
            parts.append(
                cv2.resize(bot_strip, (self._n_bottom, 1), interpolation=cv2.INTER_AREA).reshape(
                    self._n_bottom, 3
                )
            )

        if self._n_left > 0:
            left_strip = warped[::-1, : self._depth_w, :]
            parts.append(
                cv2.resize(left_strip, (1, self._n_left), interpolation=cv2.INTER_AREA).reshape(
                    self._n_left, 3
                )
            )

        return np.concatenate(parts, axis=0)

    def _extract_remap(self, raw: np.ndarray) -> np.ndarray:
        """Extract from the raw camera frame using pre-computed remap maps."""

        def _remap_resize(maps, n_leds, dsize):
            strip = cv2.remap(raw, maps[0], maps[1], cv2.INTER_NEAREST)
            return cv2.resize(strip, dsize, interpolation=cv2.INTER_AREA).reshape(n_leds, 3)

        parts: list[np.ndarray] = []

        if self._n_top > 0:
            parts.append(_remap_resize(self._remap_top, self._n_top, (self._n_top, 1)))
        if self._n_right > 0:
            parts.append(_remap_resize(self._remap_right, self._n_right, (1, self._n_right)))
        if self._n_bottom > 0:
            bot_strip = cv2.remap(raw, self._remap_bot[0], self._remap_bot[1], cv2.INTER_NEAREST)
            parts.append(
                cv2.resize(bot_strip[:, ::-1, :], (self._n_bottom, 1), interpolation=cv2.INTER_AREA).reshape(
                    self._n_bottom, 3
                )
            )
        if self._n_left > 0:
            left_strip = cv2.remap(raw, self._remap_left[0], self._remap_left[1], cv2.INTER_NEAREST)
            parts.append(
                cv2.resize(left_strip[::-1, :, :], (1, self._n_left), interpolation=cv2.INTER_AREA).reshape(
                    self._n_left, 3
                )
            )

        return np.concatenate(parts, axis=0)

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def post_process(self, colors: np.ndarray) -> np.ndarray:
        """Apply saturation boost → combined LUT → spatial blur.

        All operations act on the (n_total, 3) LED array — negligible compute cost.

        Args:
            colors: uint8 ndarray (n_total, 3).

        Returns:
            Processed uint8 ndarray (n_total, 3).
        """
        result = colors.astype(np.uint8)

        # 1. Saturation boost (cross-channel — cannot be folded into per-channel LUT)
        if self._sat_boost != 1.0:
            result = self._apply_saturation(result, self._sat_boost)

        # 2. Gamma + brightness floor via pre-computed LUT
        result = self._lut[result]

        # 3. Spatial blur along strip axis
        if self._spatial_sigma > 0.0:
            result = gaussian_filter1d(
                result.astype(np.float32), self._spatial_sigma, axis=0
            ).clip(0, 255).astype(np.uint8)

        return result

    @staticmethod
    def _apply_saturation(colors: np.ndarray, boost: float) -> np.ndarray:
        """Boost HSV saturation of the LED color array.

        Works in-place on a reshaped (1, n, 3) image to keep OpenCV happy.
        """
        img = colors.reshape(1, -1, 3)
        hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * boost, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).reshape(-1, 3)

    @property
    def n_total(self) -> int:
        """Total number of LEDs in the strip."""
        return self._n_total
