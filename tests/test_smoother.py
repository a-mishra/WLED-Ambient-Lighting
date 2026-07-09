"""Tests for EMASmoother."""

import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.smoother import EMASmoother


def _make_config(alpha=0.5, method="ema"):
    return {
        "color": {
            "smoothing": {"method": method, "alpha": alpha}
        }
    }


def test_alpha_1_returns_exact_input():
    """With alpha=1, EMA state = new value instantly (no lag)."""
    smoother = EMASmoother(_make_config(alpha=1.0), n_leds=10)
    colors = np.full((10, 3), 200, dtype=np.uint8)
    result = smoother.smooth(colors)
    assert np.allclose(result, colors, atol=1)


def test_first_call_seeds_state():
    """The first smooth call should return exactly the input (no history)."""
    smoother = EMASmoother(_make_config(alpha=0.3), n_leds=5)
    colors = np.full((5, 3), 100, dtype=np.uint8)
    result = smoother.smooth(colors)
    assert np.allclose(result, colors, atol=1)


def test_ema_converges_to_target():
    """After many calls with the same value, state should converge close to it."""
    smoother = EMASmoother(_make_config(alpha=0.3), n_leds=4)
    target = np.full((4, 3), 200, dtype=np.uint8)
    # Seed with zeros
    smoother.smooth(np.zeros((4, 3), dtype=np.uint8))
    for _ in range(50):
        result = smoother.smooth(target)
    # Should be within 5 of target after 50 iterations
    assert np.abs(result.astype(int) - 200).max() < 5


def test_ema_lags_behind_step():
    """EMA output should lag behind a sudden step change."""
    smoother = EMASmoother(_make_config(alpha=0.1), n_leds=1)
    for _ in range(10):
        smoother.smooth(np.zeros((1, 3), dtype=np.uint8))
    result = smoother.smooth(np.full((1, 3), 255, dtype=np.uint8))
    # With alpha=0.1, one step from 0 → 255 gives 0.1*255 ≈ 25
    assert result[0, 0] < 50, "EMA should lag on sudden step"


def test_method_none_returns_input_unchanged():
    smoother = EMASmoother(_make_config(method="none"), n_leds=6)
    colors = np.array([[10, 20, 30]] * 6, dtype=np.uint8)
    result = smoother.smooth(colors)
    assert np.array_equal(result, colors)


def test_reset_clears_state():
    smoother = EMASmoother(_make_config(alpha=0.3), n_leds=3)
    # Run several frames to build state
    for _ in range(5):
        smoother.smooth(np.full((3, 3), 200, dtype=np.uint8))
    smoother.reset()
    # After reset, the next call should seed from input again
    colors = np.full((3, 3), 50, dtype=np.uint8)
    result = smoother.smooth(colors)
    assert np.allclose(result, colors, atol=1)


def test_output_shape_preserved():
    smoother = EMASmoother(_make_config(), n_leds=268)
    colors = np.random.randint(0, 256, (268, 3), dtype=np.uint8)
    result = smoother.smooth(colors)
    assert result.shape == (268, 3)


def test_output_dtype_is_uint8():
    smoother = EMASmoother(_make_config(), n_leds=10)
    colors = np.full((10, 3), 128, dtype=np.uint8)
    result = smoother.smooth(colors)
    assert result.dtype == np.uint8


def test_values_stay_in_range():
    smoother = EMASmoother(_make_config(alpha=0.5), n_leds=10)
    for _ in range(20):
        colors = np.random.randint(0, 256, (10, 3), dtype=np.uint8)
        result = smoother.smooth(colors)
        assert result.min() >= 0
        assert result.max() <= 255
