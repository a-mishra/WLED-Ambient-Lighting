"""Manual perspective calibration tool.

Captures one frame at full camera resolution, displays it in a window, and lets
the user click the four corners of the TV screen. The selected points are written
back to config/config.yaml.

Usage:
    python -m tools.calibrate_manual
    python -m tools.calibrate_manual --config path/to/config.yaml
"""

import sys
import argparse
import logging
from pathlib import Path
import numpy as np
import cv2

# Allow running as a top-level script
sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config import load_config, save_config
from ambient.factory import create_camera

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_CLICK_COLOR = (0, 0, 255)
_LINE_COLOR = (0, 255, 0)
_INSTRUCTIONS = (
    "Click the FOUR CORNERS of the TV screen in order:\n"
    "  1. Top-left\n"
    "  2. Top-right\n"
    "  3. Bottom-right\n"
    "  4. Bottom-left\n"
    "Press ENTER to save, ESC to cancel, R to reset."
)


class _ClickCollector:
    def __init__(self) -> None:
        self.points: list[list[int]] = []
        self.frame_display: np.ndarray | None = None

    def callback(self, event: int, x: int, y: int, flags: int, param) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if len(self.points) >= 4:
            return
        self.points.append([x, y])
        logger.info("Point %d: (%d, %d)", len(self.points), x, y)
        if self.frame_display is not None:
            self._redraw()

    def _redraw(self) -> None:
        display = self.frame_display.copy()
        for i, (px, py) in enumerate(self.points):
            cv2.circle(display, (px, py), 6, _CLICK_COLOR, -1)
            cv2.putText(
                display, str(i + 1), (px + 8, py - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, _CLICK_COLOR, 2,
            )
        if len(self.points) == 4:
            pts = np.array(self.points, dtype=np.int32)
            cv2.polylines(display, [pts], isClosed=True, color=_LINE_COLOR, thickness=2)
        cv2.imshow(_WIN, display)

    def reset(self) -> None:
        self.points.clear()
        if self.frame_display is not None:
            cv2.imshow(_WIN, self.frame_display)


_WIN = "Select TV Corners — ENTER save, ESC cancel, R reset"


def run(config_path: str | None = None) -> None:
    config = load_config(config_path)
    camera = create_camera(config)

    logger.info("Warming up camera…")
    import time
    time.sleep(1.5)  # let AE/AWB settle

    frame = camera.get_latest_frame()
    camera.close()

    if frame is None:
        logger.error("No frame captured.")
        return

    print(_INSTRUCTIONS)

    collector = _ClickCollector()
    collector.frame_display = frame.copy()

    cv2.namedWindow(_WIN)
    cv2.setMouseCallback(_WIN, collector.callback)
    cv2.imshow(_WIN, frame)

    while True:
        key = cv2.waitKey(50) & 0xFF
        if key == 13:  # ENTER
            if len(collector.points) != 4:
                logger.warning("Need exactly 4 points, have %d.", len(collector.points))
                continue
            config["perspective"]["points"] = collector.points
            save_config(config, config_path)
            logger.info("Saved perspective points: %s", collector.points)
            break
        elif key == 27:  # ESC
            logger.info("Calibration cancelled.")
            break
        elif key == ord("r"):
            collector.reset()
            logger.info("Points reset.")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manual TV corner calibration")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args()
    run(args.config)
