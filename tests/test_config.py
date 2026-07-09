"""Tests for config loading and schema validation."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config import load_config

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

_REQUIRED_KEYS = {
    "camera": ["resolution", "awb_enable", "ae_enable", "analogue_gain", "exposure_time"],
    "perspective": ["output_resolution", "points"],
    "color": ["edge_depth", "saturation_boost", "brightness_floor", "gamma", "smoothing"],
    "wled": ["ip", "port", "protocol", "led_layout"],
    "processing": ["target_fps", "log_level"],
    "simulator": ["camera", "wled"],
}


def test_config_loads():
    cfg = load_config(CONFIG_PATH)
    assert isinstance(cfg, dict)


def test_required_top_level_keys():
    cfg = load_config(CONFIG_PATH)
    for key in _REQUIRED_KEYS:
        assert key in cfg, f"Missing top-level key: {key}"


def test_required_nested_keys():
    cfg = load_config(CONFIG_PATH)
    for section, keys in _REQUIRED_KEYS.items():
        for key in keys:
            assert key in cfg[section], f"Missing {section}.{key}"


def test_camera_resolution_is_two_ints():
    cfg = load_config(CONFIG_PATH)
    res = cfg["camera"]["resolution"]
    assert len(res) == 2
    assert all(isinstance(v, int) and v > 0 for v in res)


def test_perspective_points_are_four_pairs():
    cfg = load_config(CONFIG_PATH)
    pts = cfg["perspective"]["points"]
    assert len(pts) == 4
    for pt in pts:
        assert len(pt) == 2


def test_led_layout_all_positive():
    cfg = load_config(CONFIG_PATH)
    layout = cfg["wled"]["led_layout"]
    for side in ("top", "right", "bottom", "left"):
        assert side in layout
        assert layout[side] > 0


def test_output_resolution_is_two_ints():
    cfg = load_config(CONFIG_PATH)
    res = cfg["perspective"]["output_resolution"]
    assert len(res) == 2
    assert all(isinstance(v, int) and v > 0 for v in res)


def test_ema_alpha_in_range():
    cfg = load_config(CONFIG_PATH)
    alpha = cfg["color"]["smoothing"]["alpha"]
    assert 0.0 < alpha <= 1.0


def test_gamma_positive():
    cfg = load_config(CONFIG_PATH)
    assert cfg["color"]["gamma"] > 0


def test_target_fps_positive():
    cfg = load_config(CONFIG_PATH)
    assert cfg["processing"]["target_fps"] > 0
