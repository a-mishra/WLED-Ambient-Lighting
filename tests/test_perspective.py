"""Tests for PerspectiveCorrector.

Uses a synthetic frame with known corner colors to validate that the warp
maps the expected pixels to the expected output positions.
"""

import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.perspective import PerspectiveCorrector


def _make_config(src_w=320, src_h=240, out_w=160, out_h=90):
    """Build a minimal config with the full frame as perspective points."""
    return {
        "perspective": {
            "output_resolution": [out_w, out_h],
            "points": [
                [0, 0],
                [src_w - 1, 0],
                [src_w - 1, src_h - 1],
                [0, src_h - 1],
            ],
        }
    }


def test_output_shape_matches_config():
    config = _make_config(out_w=160, out_h=90)
    corrector = PerspectiveCorrector(config)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    result = corrector.correct(frame)
    assert result.shape == (90, 160, 3)


def test_output_shape_custom_resolution():
    config = _make_config(out_w=80, out_h=45)
    corrector = PerspectiveCorrector(config)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    result = corrector.correct(frame)
    assert result.shape == (45, 80, 3)


def test_identity_transform_preserves_colors():
    """When points are the full frame corners the top-left pixel should survive."""
    config = _make_config(src_w=100, src_h=100, out_w=100, out_h=100)
    corrector = PerspectiveCorrector(config)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[0, 0] = [255, 0, 0]      # top-left red
    frame[0, 99] = [0, 255, 0]     # top-right green
    frame[99, 0] = [0, 0, 255]     # bottom-left blue
    result = corrector.correct(frame)
    # Top-left corner should be red (or very close with INTER_NEAREST)
    assert result[0, 0, 0] > 200, "Top-left should be red"
    assert result[0, 99, 1] > 200, "Top-right should be green"


def test_update_points_changes_output():
    config = _make_config(src_w=320, src_h=240, out_w=160, out_h=90)
    corrector = PerspectiveCorrector(config)
    frame = np.random.randint(0, 256, (240, 320, 3), dtype=np.uint8)
    result_before = corrector.correct(frame).copy()

    # Shift all points by 5 pixels — output should differ
    corrector.update_points([
        [5, 5], [315, 5], [315, 235], [5, 235]
    ])
    result_after = corrector.correct(frame)
    assert not np.array_equal(result_before, result_after)


def test_matrix_property_returns_3x3():
    config = _make_config()
    corrector = PerspectiveCorrector(config)
    assert corrector.matrix.shape == (3, 3)


def test_output_size_property():
    config = _make_config(out_w=200, out_h=100)
    corrector = PerspectiveCorrector(config)
    assert corrector.output_size == (200, 100)
