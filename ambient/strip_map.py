"""Map logical TV-edge LED order to physical strip wire order.

Logical order (from EdgeColorExtractor):
  top (L→R) → right (T→B) → bottom (R→L) → left (B→T)

Physical order is determined by strip_start (which corner is LED 0) and
strip_direction (cw or ccw around the TV, viewed from the front).
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

STRIP_STARTS = frozenset({"top_left", "top_right", "bottom_right", "bottom_left"})
STRIP_DIRECTIONS = frozenset({"cw", "ccw"})
SIDES = ("top", "right", "bottom", "left")
CORNERS_CW = ("top_left", "top_right", "bottom_right", "bottom_left")

# Logical forward traversal on each side (start_corner → end_corner).
SIDE_ENDPOINTS: dict[str, tuple[str, str]] = {
    "top": ("top_left", "top_right"),
    "right": ("top_right", "bottom_right"),
    "bottom": ("bottom_right", "bottom_left"),
    "left": ("bottom_left", "top_left"),
}


def _logical_offsets(layout: dict[str, int]) -> dict[str, tuple[int, int]]:
    offsets: dict[str, tuple[int, int]] = {}
    i = 0
    for side in SIDES:
        n = layout[side]
        offsets[side] = (i, i + n)
        i += n
    return offsets


def _side_traversals(strip_start: str, strip_direction: str) -> list[tuple[str, bool]]:
    """Return (side, reverse) pairs in physical visit order.

    reverse=False means logical indices 0..n-1; reverse=True means n-1..0.
    """
    start_idx = CORNERS_CW.index(strip_start)

    if strip_direction == "cw":
        first_side_idx = start_idx
        side_order = SIDES[first_side_idx:] + SIDES[:first_side_idx]
    else:
        first_side_idx = (start_idx - 1) % 4
        side_order = [SIDES[first_side_idx]]
        side_order += [SIDES[i] for i in range(first_side_idx - 1, -1, -1)]
        side_order += [SIDES[i] for i in range(3, first_side_idx, -1)]

    traversals: list[tuple[str, bool]] = []
    corner = strip_start

    for side in side_order:
        start_corner, end_corner = SIDE_ENDPOINTS[side]
        if corner == start_corner:
            traversals.append((side, False))
            corner = end_corner
        elif corner == end_corner:
            traversals.append((side, True))
            corner = start_corner
        else:
            raise ValueError(
                f"strip routing inconsistency at corner={corner} side={side}"
            )

    return traversals


def build_strip_permutation(
    layout: dict[str, int],
    strip_start: str = "top_left",
    strip_direction: str = "cw",
) -> np.ndarray:
    """Build index array where physical[i] = logical[perm[i]]."""
    if strip_start not in STRIP_STARTS:
        raise ValueError(f"invalid strip_start: {strip_start}")
    if strip_direction not in STRIP_DIRECTIONS:
        raise ValueError(f"invalid strip_direction: {strip_direction}")

    total = sum(layout[s] for s in SIDES)
    if total < 1:
        raise ValueError("led_layout total must be at least 1")

    offsets = _logical_offsets(layout)
    traversals = _side_traversals(strip_start, strip_direction)

    perm: list[int] = []
    for side, reverse in traversals:
        n = layout[side]
        if n == 0:
            continue
        base, end = offsets[side]
        indices = list(range(base, end))
        if reverse:
            indices.reverse()
        perm.extend(indices)

    if len(perm) != total:
        raise ValueError(f"permutation length {len(perm)} != total LEDs {total}")

    return np.array(perm, dtype=np.intp)


class StripMapper:
    """Remap logical LED colors to physical wire order."""

    def __init__(self, wled_config: dict) -> None:
        layout = wled_config["led_layout"]
        strip_start = wled_config.get("strip_start", "top_left")
        strip_direction = wled_config.get("strip_direction", "cw")

        self._perm = build_strip_permutation(layout, strip_start, strip_direction)
        self._inv_perm = np.empty_like(self._perm)
        self._inv_perm[self._perm] = np.arange(len(self._perm), dtype=np.intp)

        logger.info(
            "StripMapper: start=%s direction=%s n_leds=%d",
            strip_start,
            strip_direction,
            len(self._perm),
        )

    @property
    def n_physical(self) -> int:
        return len(self._perm)

    @property
    def permutation(self) -> np.ndarray:
        return self._perm

    def to_physical(self, logical: np.ndarray) -> np.ndarray:
        """Map logical (n, 3) colors to physical wire order."""
        return logical[self._perm]

    def to_logical(self, physical: np.ndarray) -> np.ndarray:
        """Map physical (n, 3) colors back to logical TV-edge order."""
        return physical[self._inv_perm]
