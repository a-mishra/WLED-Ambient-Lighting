"""Automatic perspective calibration tool.

Points the camera at the TV while showing a solid white screen (or in a bright
room). Finds the largest bright rectangular region via thresholding + contour
analysis and writes the four corners to config/config.yaml.

Usage:
    python -m tools.calibrate_auto
    python -m tools.calibrate_auto --config path/to/config.yaml --threshold 200 --preview
"""

import sys
import argparse
import logging
import time
from pathlib import Path

import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config import load_config, save_config
from ambient.factory import create_camera

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def find_tv_corners(
    frame: np.ndarray, threshold: int = 200
) -> list[list[int]] | None:
    """Detect the largest bright rectangular region in the frame.

    Returns four corners as [[x,y], ...] in TL, TR, BR, BL order, or None.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    # Morphological close to fill gaps in the TV outline
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Keep only contours that are at least 10% of frame area
    min_area = frame.shape[0] * frame.shape[1] * 0.10
    large = [c for c in contours if cv2.contourArea(c) >= min_area]
    if not large:
        logger.warning("No contour large enough (min %.0f px²). Lower --threshold?", min_area)
        return None

    largest = max(large, key=cv2.contourArea)

    # Approximate to a polygon and look for a quadrilateral
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.04 * peri, True)

    if len(approx) == 4:
        pts = approx.reshape(4, 2).tolist()
    else:
        # Fall back to bounding box corners
        x, y, w, h = cv2.boundingRect(largest)
        pts = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    # Re-order to TL, TR, BR, BL
    pts_arr = np.array(pts, dtype=np.float32)
    center = pts_arr.mean(axis=0)
    angles = np.arctan2(pts_arr[:, 1] - center[1], pts_arr[:, 0] - center[0])
    order = np.argsort(angles)
    # arctan2 order is: right, bottom, left, top → map to TL, TR, BR, BL
    tl = pts_arr[order[3]].astype(int).tolist()
    tr = pts_arr[order[0]].astype(int).tolist()
    br = pts_arr[order[1]].astype(int).tolist()
    bl = pts_arr[order[2]].astype(int).tolist()

    return [tl, tr, br, bl]


def run(config_path: str | None = None, threshold: int = 200, preview: bool = False) -> None:
    config = load_config(config_path)
    camera = create_camera(config)

    logger.info("Warming up camera (2s)…")
    time.sleep(2.0)

    frame = camera.get_latest_frame()
    camera.close()

    if frame is None:
        logger.error("No frame captured.")
        return

    corners = find_tv_corners(frame, threshold)

    if corners is None:
        logger.error(
            "Could not detect TV corners. Try:\n"
            "  • Display a solid white image on the TV\n"
            "  • Reduce --threshold (currently %d)\n"
            "  • Use calibrate_manual.py for manual selection",
            threshold,
        )
        return

    logger.info("Detected corners: %s", corners)

    if preview:
        display = frame.copy()
        pts = np.array(corners, dtype=np.int32)
        cv2.polylines(display, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        for i, (x, y) in enumerate(corners):
            cv2.circle(display, (x, y), 6, (0, 0, 255), -1)
            cv2.putText(
                display, str(i + 1), (x + 8, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
            )
        cv2.imshow("Detected corners — any key to accept, ESC to cancel", display)
        key = cv2.waitKey(0) & 0xFF
        cv2.destroyAllWindows()
        if key == 27:
            logger.info("Calibration cancelled by user.")
            return

    config["perspective"]["points"] = corners
    save_config(config, config_path)
    logger.info("Perspective points saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automatic TV corner detection")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument(
        "--threshold", type=int, default=200,
        help="Brightness threshold for TV detection (0–255, default 200)",
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Show detected corners before saving",
    )
    args = parser.parse_args()
    run(args.config, args.threshold, args.preview)
