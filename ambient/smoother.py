"""Exponential Moving Average (EMA) smoother for LED colors.

A single vectorized update per frame: state = α·new + (1−α)·state
This avoids any Python-level loops and runs on the entire LED array at once.

α (alpha) controls the trade-off:
  - α = 1.0 → instant response, no smoothing
  - α = 0.3 → moderate smoothing, good for typical TV content
  - α = 0.1 → slow, dreamy transitions
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)


class EMASmoother:
    """Per-LED exponential moving average color smoother."""

    def __init__(self, config: dict, n_leds: int) -> None:
        smoothing = config["color"]["smoothing"]
        self._method: str = smoothing.get("method", "ema")
        self._alpha = np.float32(smoothing.get("alpha", 0.3))
        self._n_leds = n_leds
        self._state: np.ndarray | None = None  # float32 (n_leds, 3)
        logger.info(
            "EMASmoother: method=%s alpha=%.2f n_leds=%d",
            self._method,
            self._alpha,
            n_leds,
        )

    def smooth(self, colors: np.ndarray) -> np.ndarray:
        """Apply smoothing and return a uint8 (n_leds, 3) array.

        If method is 'none', returns the input unchanged.
        On the first call the state is seeded from the input with no blending.
        """
        if self._method == "none":
            return colors.astype(np.uint8)

        new = colors.astype(np.float32)
        if self._state is None:
            self._state = new.copy()
        else:
            # In-place update avoids allocating a new array each frame
            self._state *= 1.0 - self._alpha
            self._state += self._alpha * new

        return self._state.clip(0, 255).astype(np.uint8)

    def reset(self) -> None:
        """Clear the smoothing state (e.g. after a scene cut)."""
        self._state = None
