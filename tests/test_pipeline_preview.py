"""Tests for pipeline_preview module."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config import load_config
from ambient.pipeline_preview import (
  annotate_warped,
  process_frame,
  render_led_overlay,
)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


def _synthetic_frame(w: int = 320, h: int = 240) -> np.ndarray:
  y = np.linspace(0, 255, h, dtype=np.uint8)
  x = np.linspace(0, 255, w, dtype=np.uint8)
  yy, xx = np.meshgrid(y, x, indexing="ij")
  return np.stack([xx, yy, ((xx.astype(np.uint16) + yy) % 256).astype(np.uint8)], axis=-1)


def test_process_frame_shapes():
  config = load_config(CONFIG_PATH)
  frame = _synthetic_frame()
  result = process_frame(config, frame)

  assert result.raw_annotated.shape == frame.shape
  out_w, out_h = config["perspective"]["output_resolution"]
  assert result.warped_annotated.shape == (out_h, out_w, 3)
  layout = config["wled"]["led_layout"]
  n_total = sum(layout.values())
  assert result.colors_final.shape == (n_total, 3)
  assert result.led_overlay.shape[0] > out_h
  assert result.led_overlay.shape[1] > out_w


def test_render_led_overlay_larger_than_warped():
  config = load_config(CONFIG_PATH)
  out_w, out_h = config["perspective"]["output_resolution"]
  warped = _synthetic_frame(out_w, out_h)
  layout = config["wled"]["led_layout"]
  n = sum(layout.values())
  colors = np.random.randint(0, 256, (n, 3), dtype=np.uint8)
  overlay = render_led_overlay(warped, colors, layout, scale=4)
  assert overlay.shape[0] > out_h
  assert overlay.shape[1] > out_w


def test_annotate_warped_changes_pixels():
  warped = np.zeros((90, 160, 3), dtype=np.uint8)
  warped[:, :] = [50, 50, 50]
  annotated = annotate_warped(warped, edge_depth=0.05)
  assert not np.array_equal(annotated, warped)
  # Top band should differ from interior
  assert not np.array_equal(annotated[0, 80], warped[45, 80])


def test_timing_keys_present():
  config = load_config(CONFIG_PATH)
  result = process_frame(config, _synthetic_frame())
  assert "warp" in result.timing_ms
  assert "extract" in result.timing_ms
  assert "post_process" in result.timing_ms
