"""Perspective correction with a one-time matrix computation.

The transform matrix is computed once at construction from the four TV corner
points in config. cv2.INTER_NEAREST is used for the warp — bilinear
interpolation is unnecessary for color sampling and costs ~20% more on ARM.
"""

import cv2
import numpy as np
import logging
from typing import List

logger = logging.getLogger(__name__)


class PerspectiveCorrector:
    """Warps the TV region of the raw camera frame to a rectangular output."""

    def __init__(self, config: dict) -> None:
        persp_cfg = config["perspective"]
        self._output_size: tuple[int, int] = tuple(persp_cfg["output_resolution"])  # (W, H)
        self._matrix: np.ndarray | None = None
        self.update_points(persp_cfg["points"])

    def update_points(self, points: List[List[int]]) -> None:
        """Recompute the transform from 4 corners (TL, TR, BR, BL).

        Call this after recalibration without restarting the pipeline.
        """
        w, h = self._output_size
        src = np.array(points, dtype=np.float32)
        dst = np.array(
            [[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]],
            dtype=np.float32,
        )
        self._matrix = cv2.getPerspectiveTransform(src, dst)
        logger.info("Perspective matrix updated. Output size: %s", self._output_size)

    @property
    def matrix(self) -> np.ndarray:
        """The forward transform matrix (raw frame → output frame)."""
        return self._matrix

    @property
    def output_size(self) -> tuple[int, int]:
        """Output resolution as (width, height)."""
        return self._output_size

    def correct(self, frame: np.ndarray) -> np.ndarray:
        """Warp the raw frame to the output resolution using the stored matrix.

        Uses INTER_NEAREST — sufficient for color sampling, ~20% faster than
        bilinear on Pi Zero 2W ARM core.
        """
        return cv2.warpPerspective(
            frame,
            self._matrix,
            self._output_size,
            flags=cv2.INTER_NEAREST,
        )
