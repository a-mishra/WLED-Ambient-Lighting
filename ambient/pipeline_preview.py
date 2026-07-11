"""Single-frame pipeline preview for the web config UI.

Runs capture → warp → extract → post_process (no smooth/send) and renders
debug images: raw with quad, warped with edge bands, LED color overlay.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from .color import EdgeColorExtractor
from .edge_sampling import EdgeSamplingConfig, SIDES, parse_edge_sampling
from .perspective import PerspectiveCorrector

_BAND_COLOR_ENABLED = (0, 200, 255)
_BAND_COLOR_DISABLED = (180, 80, 80)
_BAND_ALPHA = 0.35


@dataclass
class PreviewResult:
  raw_annotated: np.ndarray
  warped_annotated: np.ndarray
  led_overlay: np.ndarray
  colors_extracted: np.ndarray
  colors_final: np.ndarray
  timing_ms: dict[str, float]
  led_layout: dict[str, int]
  sampling_meta: dict


def annotate_raw(frame: np.ndarray, points: list[list[int]]) -> np.ndarray:
  """Draw perspective quad and numbered corners on a copy of the raw frame."""
  out = frame.copy()
  if len(points) == 4:
    pts = np.array(points, dtype=np.int32)
    cv2.polylines(out, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
    for i, (x, y) in enumerate(points):
      cv2.circle(out, (int(x), int(y)), 6, (0, 0, 255), -1)
      cv2.putText(
        out, str(i + 1), (int(x) + 8, int(y) - 8),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
      )
  return out


def annotate_warped(
  warped: np.ndarray,
  sampling: EdgeSamplingConfig,
  led_layout: dict[str, int],
) -> np.ndarray:
  """Draw semi-transparent edge sampling bands on the warped frame."""
  out = warped.copy()
  if not sampling.show_sampling_bands:
    return out

  h, w = out.shape[:2]
  depth_h, depth_w = sampling.depth_pixels(w, h)
  overlay = out.copy()

  def _draw_band(rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    cv2.rectangle(overlay, rect[:2], rect[2:], color, -1)

  if led_layout.get("top", 0) > 0:
    color = _BAND_COLOR_ENABLED if sampling.enabled["top"] else _BAND_COLOR_DISABLED
    _draw_band((0, 0, w, depth_h), color)

  if led_layout.get("bottom", 0) > 0:
    color = _BAND_COLOR_ENABLED if sampling.enabled["bottom"] else _BAND_COLOR_DISABLED
    _draw_band((0, h - depth_h, w, h), color)

  if led_layout.get("left", 0) > 0:
    color = _BAND_COLOR_ENABLED if sampling.enabled["left"] else _BAND_COLOR_DISABLED
    _draw_band((0, 0, depth_w, h), color)

  if led_layout.get("right", 0) > 0:
    color = _BAND_COLOR_ENABLED if sampling.enabled["right"] else _BAND_COLOR_DISABLED
    _draw_band((w - depth_w, 0, w, h), color)

  cv2.addWeighted(overlay, _BAND_ALPHA, out, 1 - _BAND_ALPHA, 0, out)
  return out


def build_sampling_meta(
  sampling: EdgeSamplingConfig,
  led_layout: dict[str, int],
  out_w: int,
  out_h: int,
) -> dict:
  """Summary for web preview meta panel."""
  depth_h, depth_w = sampling.depth_pixels(out_w, out_h)
  sides: dict[str, dict] = {}
  for side in SIDES:
    n_leds = led_layout.get(side, 0)
    if n_leds <= 0:
      sides[side] = {"leds": 0, "active": False, "mode": "no_leds"}
      continue
    enabled = sampling.enabled.get(side, True)
    sides[side] = {
      "leds": n_leds,
      "active": enabled,
      "mode": "sample" if enabled else sampling.disabled_color.get(side, "black"),
    }
  return {
    "depth_h_px": depth_h,
    "depth_w_px": depth_w,
    "depth_h_frac": sampling.depth_h_frac,
    "depth_w_frac": sampling.depth_w_frac,
    "show_bands": sampling.show_sampling_bands,
    "sides": sides,
  }


def _split_colors(colors: np.ndarray, layout: dict[str, int]) -> tuple[np.ndarray, ...]:
  i = 0
  top = colors[i : i + layout["top"]]
  i += layout["top"]
  right = colors[i : i + layout["right"]]
  i += layout["right"]
  bottom = colors[i : i + layout["bottom"]]
  i += layout["bottom"]
  left = colors[i : i + layout["left"]]
  return top, right, bottom, left


def render_led_overlay(
  warped: np.ndarray,
  colors: np.ndarray,
  led_layout: dict[str, int],
  scale: int = 4,
) -> np.ndarray:
  """Scale warped frame and draw per-LED color blocks on each edge."""
  s = max(1, scale)
  out_h, out_w = warped.shape[:2]
  preview_w = out_w * s
  preview_h = out_h * s
  win_w = preview_w + 2 * s
  win_h = preview_h + 2 * s

  canvas = np.full((win_h, win_w, 3), 20, dtype=np.uint8)
  scaled = cv2.resize(warped, (preview_w, preview_h), interpolation=cv2.INTER_NEAREST)
  canvas[s : s + preview_h, s : s + preview_w] = scaled

  n_top = led_layout["top"]
  n_right = led_layout["right"]
  n_bottom = led_layout["bottom"]
  n_left = led_layout["left"]

  top_c, right_c, bottom_c, left_c = _split_colors(colors, led_layout)

  if n_top > 0:
    led_w_h = max(1, preview_w // n_top)
    for j, c in enumerate(top_c):
      x1 = s + j * led_w_h
      cv2.rectangle(canvas, (x1, 0), (x1 + led_w_h, s), c.tolist(), -1)

  if n_bottom > 0:
    led_w_h = max(1, preview_w // n_bottom)
    for j, c in enumerate(bottom_c):
      x1 = s + j * led_w_h
      cv2.rectangle(canvas, (x1, win_h - s), (x1 + led_w_h, win_h), c.tolist(), -1)

  if n_left > 0:
    led_h_v = max(1, preview_h // n_left)
    for j, c in enumerate(left_c):
      y1 = s + j * led_h_v
      cv2.rectangle(canvas, (0, y1), (s, y1 + led_h_v), c.tolist(), -1)

  if n_right > 0:
    led_h_v = max(1, preview_h // n_right)
    for j, c in enumerate(right_c):
      y1 = s + j * led_h_v
      cv2.rectangle(canvas, (win_w - s, y1), (win_w, y1 + led_h_v), c.tolist(), -1)

  return canvas


def process_frame(config: dict, raw_frame: np.ndarray) -> PreviewResult:
  """Run warp → extract → post_process and build preview images."""
  points = config["perspective"]["points"]
  led_layout = config["wled"]["led_layout"]
  out_w, out_h = config["perspective"]["output_resolution"]
  sampling = parse_edge_sampling(config["color"])

  t0 = time.perf_counter()
  corrector = PerspectiveCorrector(config)
  warped = corrector.correct(raw_frame)
  t_warp = (time.perf_counter() - t0) * 1000

  t0 = time.perf_counter()
  extractor = EdgeColorExtractor(
    config,
    perspective_matrix=corrector.matrix if config["color"].get("use_remap") else None,
  )
  source = raw_frame if config["color"].get("use_remap") else warped
  colors_extracted = extractor.extract(source)
  t_extract = (time.perf_counter() - t0) * 1000

  t0 = time.perf_counter()
  colors_final = extractor.post_process(colors_extracted)
  t_post = (time.perf_counter() - t0) * 1000

  raw_annotated = annotate_raw(raw_frame, points)
  warped_annotated = annotate_warped(warped, sampling, led_layout)
  led_overlay = render_led_overlay(warped, colors_final, led_layout)
  sampling_meta = build_sampling_meta(sampling, led_layout, out_w, out_h)

  return PreviewResult(
    raw_annotated=raw_annotated,
    warped_annotated=warped_annotated,
    led_overlay=led_overlay,
    colors_extracted=colors_extracted,
    colors_final=colors_final,
    timing_ms={
      "warp": round(t_warp, 2),
      "extract": round(t_extract, 2),
      "post_process": round(t_post, 2),
    },
    led_layout=dict(led_layout),
    sampling_meta=sampling_meta,
  )


def encode_jpeg(frame_rgb: np.ndarray, quality: int = 85) -> bytes:
  """Encode an RGB frame as JPEG bytes."""
  bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
  ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
  if not ok:
    raise RuntimeError("JPEG encode failed")
  return buf.tobytes()
