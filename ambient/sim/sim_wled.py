"""Simulated WLED output — renders LED colors in a pygame window.

Display modes (simulator.wled.display):
  window  — pygame window showing the LED ring around a TV frame preview
  console — prints a compact ANSI color table to stdout (headless Pi / SSH)
  none    — no-op; useful in unit tests

Window layout (window mode):
  Each LED is a square of window_scale × window_scale pixels.
  The strip runs: top (L→R) → right (T→B) → bottom (R→L) → left (B→T).
  If show_frame_preview is true, the corrected TV frame is drawn in the center.

Pygame is imported lazily so that 'console' and 'none' modes work without it.
"""

import logging
import numpy as np

from ..base import WLEDBase
from ..strip_map import StripMapper

logger = logging.getLogger(__name__)

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False


class SimWLED(WLEDBase):
    """Config-driven simulated WLED output."""

    def __init__(self, config: dict) -> None:
        wled_cfg = config["wled"]
        led_layout = wled_cfg["led_layout"]
        sim_cfg = config["simulator"]["wled"]
        persp_cfg = config["perspective"]

        self._n_top: int = led_layout["top"]
        self._n_right: int = led_layout["right"]
        self._n_bottom: int = led_layout["bottom"]
        self._n_left: int = led_layout["left"]
        self._mapper = StripMapper(wled_cfg)

        self._display: str = sim_cfg.get("display", "none")
        self._scale: int = int(sim_cfg.get("window_scale", 4))
        self._show_preview: bool = sim_cfg.get("show_frame_preview", True)
        self._title: str = sim_cfg.get("window_title", "WLED Simulator")

        # Preview frame storage (set by main loop via set_preview_frame)
        self._preview_frame: np.ndarray | None = None

        # Output resolution (used to size the preview area)
        self._out_w, self._out_h = persp_cfg["output_resolution"]

        self._surface = None
        self._screen = None

        if self._display == "window":
            self._init_pygame()

        logger.info("SimWLED started: display=%s scale=%d", self._display, self._scale)

    # ------------------------------------------------------------------
    # Pygame setup
    # ------------------------------------------------------------------

    def _init_pygame(self) -> None:
        if not _PYGAME_AVAILABLE:
            raise RuntimeError(
                "pygame is not installed. Install it with: pip install pygame\n"
                "Or set simulator.wled.display=console or none."
            )
        pygame.init()
        s = self._scale

        # Inner preview area sized to match output_resolution × scale
        self._preview_w = self._out_w * s
        self._preview_h = self._out_h * s

        # Window dimensions: preview + LED border (1 LED thick on each side)
        self._win_w = self._preview_w + 2 * s
        self._win_h = self._preview_h + 2 * s

        # Compute per-LED display sizes
        # Horizontal LEDs (top/bottom): width = preview_w / n_top, height = s
        self._led_w_h = max(1, self._preview_w // self._n_top)   # horiz LED pixel width
        self._led_h_v = max(1, self._preview_h // self._n_right)  # vert LED pixel height

        self._screen = pygame.display.set_mode((self._win_w, self._win_h))
        pygame.display.set_caption(self._title)
        self._clock = pygame.time.Clock()
        logger.info("Pygame window: %dx%d", self._win_w, self._win_h)

    # ------------------------------------------------------------------
    # WLEDBase interface
    # ------------------------------------------------------------------

    def send(self, colors: np.ndarray) -> None:
        """Render LED colors to the selected display mode.

        Args:
            colors: uint8 (n_leds, 3) RGB array in physical wire order.
        """
        logical = self._mapper.to_logical(colors)
        if self._display == "window":
            self._render_window(logical)
        elif self._display == "console":
            self._render_console(logical)
        # none: no-op

    def set_preview_frame(self, frame: np.ndarray) -> None:
        """Provide the corrected TV frame to display in the center of the window.

        Call this from the main loop after perspective correction, before send().
        """
        self._preview_frame = frame

    def close(self) -> None:
        if self._display == "window" and _PYGAME_AVAILABLE:
            pygame.quit()
        logger.info("SimWLED closed.")

    # ------------------------------------------------------------------
    # Window rendering
    # ------------------------------------------------------------------

    def _render_window(self, colors: np.ndarray) -> None:
        # Pump events so the window stays responsive
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise KeyboardInterrupt("SimWLED window closed by user.")

        s = self._scale
        self._screen.fill((20, 20, 20))

        # Split flat color array into per-side slices
        i = 0
        top_colors = colors[i : i + self._n_top]; i += self._n_top
        right_colors = colors[i : i + self._n_right]; i += self._n_right
        bot_colors = colors[i : i + self._n_bottom]; i += self._n_bottom
        left_colors = colors[i : i + self._n_left]

        # --- Top LEDs ---
        for j, c in enumerate(top_colors):
            rect = pygame.Rect(s + j * self._led_w_h, 0, self._led_w_h, s)
            pygame.draw.rect(self._screen, c.tolist(), rect)

        # --- Bottom LEDs ---
        for j, c in enumerate(bot_colors):
            rect = pygame.Rect(s + j * self._led_w_h, self._win_h - s, self._led_w_h, s)
            pygame.draw.rect(self._screen, c.tolist(), rect)

        # --- Left LEDs ---
        for j, c in enumerate(left_colors):
            rect = pygame.Rect(0, s + j * self._led_h_v, s, self._led_h_v)
            pygame.draw.rect(self._screen, c.tolist(), rect)

        # --- Right LEDs ---
        for j, c in enumerate(right_colors):
            rect = pygame.Rect(self._win_w - s, s + j * self._led_h_v, s, self._led_h_v)
            pygame.draw.rect(self._screen, c.tolist(), rect)

        # --- TV frame preview (center) ---
        if self._show_preview and self._preview_frame is not None:
            frame_rgb = self._preview_frame
            # Scale to preview area
            scaled = cv2_resize_to_surface(frame_rgb, self._preview_w, self._preview_h)
            surf = pygame.surfarray.make_surface(scaled.swapaxes(0, 1))
            self._screen.blit(surf, (s, s))
        else:
            # Dark placeholder rectangle
            pygame.draw.rect(
                self._screen, (10, 10, 10),
                pygame.Rect(s, s, self._preview_w, self._preview_h),
            )

        pygame.display.flip()

    # ------------------------------------------------------------------
    # Console rendering (headless / SSH)
    # ------------------------------------------------------------------

    def _render_console(self, colors: np.ndarray) -> None:
        """Print a compact ANSI-colored representation of the LED strip."""
        def ansi_block(r: int, g: int, b: int) -> str:
            return f"\x1b[48;2;{r};{g};{b}m  \x1b[0m"

        i = 0
        top = colors[i : i + self._n_top]; i += self._n_top
        right = colors[i : i + self._n_right]; i += self._n_right
        bot = colors[i : i + self._n_bottom]; i += self._n_bottom
        left = colors[i : i + self._n_left]

        # Print a thin strip sampling every Nth LED to fit console width
        sample = 40
        print("TOP:    " + "".join(ansi_block(*c) for c in top[::max(1, len(top)//sample)]))
        print("RIGHT:  " + "".join(ansi_block(*c) for c in right[::max(1, len(right)//sample)]))
        print("BOTTOM: " + "".join(ansi_block(*c) for c in bot[::max(1, len(bot)//sample)]))
        print("LEFT:   " + "".join(ansi_block(*c) for c in left[::max(1, len(left)//sample)]))
        print()


def cv2_resize_to_surface(frame_rgb: np.ndarray, w: int, h: int) -> np.ndarray:
    """Resize an RGB frame to (h, w) using cv2 (avoids importing cv2 at module level
    in a way that would break on systems where it is absent when display=none)."""
    import cv2
    return cv2.resize(frame_rgb, (w, h), interpolation=cv2.INTER_NEAREST)
