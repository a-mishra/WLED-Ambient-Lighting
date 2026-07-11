"""Edge sampling configuration — band depth, per-side enable, disabled fill."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SIDES = ("top", "right", "bottom", "left")
DISABLED_COLOR_MODES = frozenset({"black", "brightness_floor"})


@dataclass(frozen=True)
class EdgeSamplingConfig:
  """Parsed edge sampling settings from color config."""

  depth_h_frac: float
  depth_w_frac: float
  enabled: dict[str, bool]
  disabled_color: dict[str, str]
  show_sampling_bands: bool

  def depth_pixels(self, out_w: int, out_h: int) -> tuple[int, int]:
    """Return (depth_h, depth_w) in warped-frame pixels."""
    depth_h = max(1, int(out_h * self.depth_h_frac))
    depth_w = max(1, int(out_w * self.depth_w_frac))
    return depth_h, depth_w


def parse_edge_sampling(color_cfg: dict) -> EdgeSamplingConfig:
  """Parse color config into EdgeSamplingConfig (supports legacy flat edge_depth)."""
  raw_depth = color_cfg.get("edge_depth", 0.05)
  if isinstance(raw_depth, dict):
    depth_h_frac = float(raw_depth.get("horizontal", 0.05))
    depth_w_frac = float(raw_depth.get("vertical", 0.05))
  else:
    depth_h_frac = depth_w_frac = float(raw_depth)

  enabled_raw = color_cfg.get("sampling_enabled", {})
  enabled = {side: bool(enabled_raw.get(side, True)) for side in SIDES}

  disabled_raw = color_cfg.get("sampling_disabled_color", {})
  disabled_color: dict[str, str] = {}
  for side in SIDES:
    mode = str(disabled_raw.get(side, "black")).lower()
    disabled_color[side] = mode if mode in DISABLED_COLOR_MODES else "black"

  show_bands = bool(color_cfg.get("show_sampling_bands", True))

  return EdgeSamplingConfig(
    depth_h_frac=depth_h_frac,
    depth_w_frac=depth_w_frac,
    enabled=enabled,
    disabled_color=disabled_color,
    show_sampling_bands=show_bands,
  )


def disabled_rgb(side: str, cfg: EdgeSamplingConfig, brightness_floor: int) -> np.ndarray:
  """RGB uint8 triple for a disabled side's LEDs."""
  mode = cfg.disabled_color.get(side, "black")
  if mode == "brightness_floor":
    v = int(brightness_floor)
    return np.array([v, v, v], dtype=np.uint8)
  return np.array([0, 0, 0], dtype=np.uint8)


def fill_disabled_colors(n: int, rgb: np.ndarray) -> np.ndarray:
  """Return (n, 3) array filled with rgb."""
  return np.tile(rgb, (n, 1)).astype(np.uint8)
