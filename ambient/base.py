"""Abstract base classes for camera and WLED output.

Both real hardware and simulator implementations share this interface, allowing
main.py to remain hardware-agnostic and enabling easy unit testing with mocks.
"""

from abc import ABC, abstractmethod
import numpy as np


class CameraBase(ABC):
    """Base class for all camera sources (real or simulated)."""

    @abstractmethod
    def get_latest_frame(self) -> np.ndarray | None:
        """Return the most recently captured frame as a uint8 RGB ndarray (H, W, 3),
        or None if no frame is available yet."""

    @abstractmethod
    def close(self) -> None:
        """Release camera resources and stop any background threads."""


class WLEDBase(ABC):
    """Base class for all WLED output targets (real or simulated)."""

    @abstractmethod
    def send(self, colors: np.ndarray) -> None:
        """Send LED colors to the output target.

        Args:
            colors: uint8 ndarray of shape (n_leds, 3) in RGB order,
                    ordered by physical strip position (top→right→bottom→left).
        """

    @abstractmethod
    def close(self) -> None:
        """Release output resources (close socket, destroy window, etc.)."""
