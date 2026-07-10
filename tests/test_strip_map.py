"""Tests for physical strip routing permutation."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.strip_map import StripMapper, build_strip_permutation


def _wled_cfg(
    top=84,
    right=50,
    bottom=84,
    left=50,
    strip_start="top_left",
    strip_direction="cw",
):
    return {
        "led_layout": {
            "top": top,
            "right": right,
            "bottom": bottom,
            "left": left,
        },
        "strip_start": strip_start,
        "strip_direction": strip_direction,
    }


def test_top_left_cw_is_identity():
    layout = {"top": 10, "right": 6, "bottom": 10, "left": 6}
    perm = build_strip_permutation(layout, "top_left", "cw")
    assert np.array_equal(perm, np.arange(32))


def test_bottom_right_ccw_user_layout():
    layout = {"top": 72, "right": 40, "bottom": 0, "left": 40}
    perm = build_strip_permutation(layout, "bottom_right", "ccw")
    assert len(perm) == 152

    # right reversed: logical 111..72
    assert np.array_equal(perm[0:40], np.arange(111, 71, -1))
    # top reversed: logical 71..0
    assert np.array_equal(perm[40:112], np.arange(71, -1, -1))
    # left reversed: logical 151..112
    assert np.array_equal(perm[112:152], np.arange(151, 111, -1))


def test_round_trip():
    cfg = _wled_cfg(top=8, right=4, bottom=0, left=4, strip_start="bottom_right", strip_direction="ccw")
    mapper = StripMapper(cfg)
    logical = np.arange(mapper.n_physical * 3, dtype=np.uint8).reshape(-1, 3)
    physical = mapper.to_physical(logical)
    restored = mapper.to_logical(physical)
    assert np.array_equal(restored, logical)


def test_strip_mapper_n_physical():
    cfg = _wled_cfg(top=72, right=40, bottom=0, left=40, strip_start="bottom_right", strip_direction="ccw")
    mapper = StripMapper(cfg)
    assert mapper.n_physical == 152


def test_invalid_strip_start_raises():
    layout = {"top": 10, "right": 6, "bottom": 10, "left": 6}
    with pytest.raises(ValueError, match="strip_start"):
        build_strip_permutation(layout, "invalid", "cw")


def test_zero_total_raises():
    layout = {"top": 0, "right": 0, "bottom": 0, "left": 0}
    with pytest.raises(ValueError, match="at least 1"):
        build_strip_permutation(layout, "top_left", "cw")
