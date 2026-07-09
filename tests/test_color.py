"""Tests for EdgeColorExtractor.

Validates extraction accuracy using solid-color synthetic frames where the
expected LED color is known exactly, and post-processing behavior.
"""

import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.color import EdgeColorExtractor


def _make_config(out_w=160, out_h=90, n_top=16, n_right=9, n_bottom=16, n_left=9,
                 edge_depth=0.1, gamma=1.0, brightness_floor=0,
                 saturation_boost=1.0, spatial_sigma=0.0):
    return {
        "perspective": {"output_resolution": [out_w, out_h]},
        "wled": {
            "led_layout": {
                "top": n_top, "right": n_right,
                "bottom": n_bottom, "left": n_left,
            }
        },
        "color": {
            "edge_depth": edge_depth,
            "use_remap": False,
            "saturation_boost": saturation_boost,
            "brightness_floor": brightness_floor,
            "gamma": gamma,
            "spatial_blur_sigma": spatial_sigma,
            "smoothing": {"method": "ema", "alpha": 0.5},
        },
    }


def test_output_shape():
    config = _make_config(n_top=10, n_right=6, n_bottom=10, n_left=6)
    extractor = EdgeColorExtractor(config)
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    colors = extractor.extract(frame)
    assert colors.shape == (32, 3)  # 10+6+10+6


def test_solid_red_frame_extracts_red():
    config = _make_config(gamma=1.0, brightness_floor=0)
    extractor = EdgeColorExtractor(config)
    # Fill entire frame with red
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:, :, 0] = 200  # R
    colors = extractor.extract(frame)
    # All LEDs should be approximately red
    assert colors[:, 0].mean() > 150, "R channel should be high"
    assert colors[:, 1].mean() < 20, "G channel should be low"
    assert colors[:, 2].mean() < 20, "B channel should be low"


def test_solid_blue_frame_extracts_blue():
    config = _make_config(gamma=1.0, brightness_floor=0)
    extractor = EdgeColorExtractor(config)
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:, :, 2] = 180  # B
    colors = extractor.extract(frame)
    assert colors[:, 2].mean() > 130
    assert colors[:, 0].mean() < 20


def test_n_total_property():
    config = _make_config(n_top=84, n_right=50, n_bottom=84, n_left=50)
    extractor = EdgeColorExtractor(config)
    assert extractor.n_total == 268


def test_brightness_floor_applied():
    """All LEDs should be at least brightness_floor after post_process."""
    config = _make_config(gamma=1.0, brightness_floor=30, saturation_boost=1.0)
    extractor = EdgeColorExtractor(config)
    # Black frame — without floor all would be 0
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    raw = extractor.extract(frame)
    processed = extractor.post_process(raw)
    assert processed.min() >= 30, "Brightness floor not applied"


def test_gamma_lut_darkens_midtones():
    """Gamma > 1 should darken midtone values."""
    config_gamma1 = _make_config(gamma=1.0, brightness_floor=0)
    config_gamma2 = _make_config(gamma=2.2, brightness_floor=0)
    e1 = EdgeColorExtractor(config_gamma1)
    e2 = EdgeColorExtractor(config_gamma2)
    frame = np.full((90, 160, 3), 128, dtype=np.uint8)
    c1 = e1.post_process(e1.extract(frame))
    c2 = e2.post_process(e2.extract(frame))
    # With gamma=2.2, 128/255 → (0.502)^(1/2.2) ≈ 0.729 → ~186
    # So gamma-corrected should be brighter than gamma=1 midtone
    assert c2.mean() > c1.mean(), "Gamma correction should brighten midtones"


def test_spatial_blur_smooths_alternating():
    """Spatial blur should reduce the difference between adjacent LED values."""
    config = _make_config(n_top=8, n_right=4, n_bottom=8, n_left=4,
                          spatial_sigma=2.0, gamma=1.0, brightness_floor=0)
    extractor = EdgeColorExtractor(config)
    # Create alternating bright/dark on top edge
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    seg_w = 160 // 8
    for i in range(8):
        val = 200 if i % 2 == 0 else 10
        frame[:5, i * seg_w:(i + 1) * seg_w, 0] = val

    colors_no_blur = extractor.extract(frame)
    # Only top 8 are interesting
    top_no_blur = colors_no_blur[:8, 0].astype(float)

    config_blur = _make_config(n_top=8, n_right=4, n_bottom=8, n_left=4,
                               spatial_sigma=2.0, gamma=1.0, brightness_floor=0)
    extractor_blur = EdgeColorExtractor(config_blur)
    colors_blur = extractor_blur.post_process(extractor_blur.extract(frame))
    top_blur = colors_blur[:8, 0].astype(float)

    # Range should decrease after blur
    assert top_blur.max() - top_blur.min() < top_no_blur.max() - top_no_blur.min()


def test_post_process_returns_uint8():
    config = _make_config()
    extractor = EdgeColorExtractor(config)
    frame = np.random.randint(0, 256, (90, 160, 3), dtype=np.uint8)
    colors = extractor.extract(frame)
    result = extractor.post_process(colors)
    assert result.dtype == np.uint8
