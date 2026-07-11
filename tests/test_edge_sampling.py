"""Tests for edge_sampling module and per-side sampling in EdgeColorExtractor."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.color import EdgeColorExtractor
from ambient.edge_sampling import (
  disabled_rgb,
  fill_disabled_colors,
  parse_edge_sampling,
)
from ambient.pipeline_preview import annotate_warped, build_sampling_meta


def _make_config(**color_overrides):
  color = {
    "edge_depth": {"horizontal": 0.1, "vertical": 0.1},
    "use_remap": False,
    "saturation_boost": 1.0,
    "brightness_floor": 20,
    "gamma": 1.0,
    "spatial_blur_sigma": 0.0,
    "smoothing": {"method": "ema", "alpha": 0.5},
    "sampling_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "sampling_disabled_color": {
      "top": "black",
      "right": "black",
      "bottom": "black",
      "left": "black",
    },
    "show_sampling_bands": True,
  }
  color.update(color_overrides)
  return {
    "perspective": {"output_resolution": [160, 90]},
    "wled": {
      "led_layout": {"top": 8, "right": 4, "bottom": 8, "left": 4},
    },
    "color": color,
  }


def test_parse_legacy_flat_edge_depth():
  cfg = parse_edge_sampling({"edge_depth": 0.08})
  assert cfg.depth_h_frac == pytest.approx(0.08)
  assert cfg.depth_w_frac == pytest.approx(0.08)


def test_parse_split_edge_depth():
  cfg = parse_edge_sampling({"edge_depth": {"horizontal": 0.06, "vertical": 0.04}})
  assert cfg.depth_h_frac == pytest.approx(0.06)
  assert cfg.depth_w_frac == pytest.approx(0.04)
  assert cfg.depth_pixels(160, 90) == (5, 6)


def test_disabled_rgb_modes():
  cfg = parse_edge_sampling({
    "sampling_disabled_color": {"top": "brightness_floor", "right": "invalid"},
  })
  assert disabled_rgb("top", cfg, 15).tolist() == [15, 15, 15]
  assert disabled_rgb("right", cfg, 15).tolist() == [0, 0, 0]


def test_fill_disabled_colors_shape():
  rgb = np.array([10, 20, 30], dtype=np.uint8)
  out = fill_disabled_colors(5, rgb)
  assert out.shape == (5, 3)
  assert np.all(out == rgb)


def test_disabled_side_fills_black():
  config = _make_config(
    sampling_enabled={"top": False, "right": True, "bottom": True, "left": True},
    sampling_disabled_color={"top": "black"},
  )
  extractor = EdgeColorExtractor(config)
  frame = np.full((90, 160, 3), 200, dtype=np.uint8)
  colors = extractor.extract(frame)
  top = colors[:8]
  assert np.all(top == 0)


def test_disabled_side_fills_brightness_floor():
  config = _make_config(
    sampling_enabled={"top": False, "right": True, "bottom": True, "left": True},
    sampling_disabled_color={"top": "brightness_floor"},
    brightness_floor=25,
  )
  extractor = EdgeColorExtractor(config)
  frame = np.zeros((90, 160, 3), dtype=np.uint8)
  colors = extractor.extract(frame)
  top = colors[:8]
  assert np.all(top == 25)


def test_different_h_v_depth_uses_correct_strips():
  config = _make_config(edge_depth={"horizontal": 0.2, "vertical": 0.05})
  extractor = EdgeColorExtractor(config)
  assert extractor._depth_h == 18  # 90 * 0.2
  assert extractor._depth_w == 8   # 160 * 0.05


def test_annotate_warped_respects_show_bands_flag():
  warped = np.zeros((90, 160, 3), dtype=np.uint8)
  warped[:, :] = [50, 50, 50]
  sampling = parse_edge_sampling({"edge_depth": 0.1, "show_sampling_bands": False})
  layout = {"top": 8, "right": 4, "bottom": 8, "left": 4}
  out = annotate_warped(warped, sampling, layout)
  assert np.array_equal(out, warped)


def test_annotate_warped_skips_zero_led_sides():
  warped = np.zeros((90, 160, 3), dtype=np.uint8)
  warped[:, :] = [50, 50, 50]
  sampling = parse_edge_sampling({"edge_depth": 0.1, "show_sampling_bands": True})
  layout = {"top": 8, "right": 4, "bottom": 0, "left": 4}
  out = annotate_warped(warped, sampling, layout)
  # Bottom band should not be drawn (0 LEDs)
  assert np.array_equal(out[80, 80], warped[80, 80])


def test_build_sampling_meta():
  sampling = parse_edge_sampling({
    "edge_depth": {"horizontal": 0.05, "vertical": 0.05},
    "sampling_enabled": {"top": True, "bottom": False},
  })
  layout = {"top": 10, "right": 5, "bottom": 0, "left": 5}
  meta = build_sampling_meta(sampling, layout, 160, 90)
  assert meta["depth_h_px"] == 4
  assert meta["depth_w_px"] == 8
  assert meta["sides"]["top"]["active"] is True
  assert meta["sides"]["bottom"]["mode"] == "no_leds"
  assert meta["sides"]["left"]["active"] is True
