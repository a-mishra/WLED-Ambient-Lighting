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
from .perspective import PerspectiveCorrector


@dataclass
class PreviewResult:
  raw_annotated: np.ndarray
  warped_annotated: np.ndarray
  led_overlay: np.ndarray
  colors_extracted: np.ndarray
  colors_final: np.ndarray
  timing_ms: dict[str, float]
  led_layout: dict[str, int]


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


def annotate_warped(warped: np.ndarray, edge_depth: float) -> np.ndarray:
  """Draw semi-transparent edge sampling bands on the warped frame."""
  out = warped.copy()
  h, w = out.shape[:2]
  depth_h = max(1, int(h * edge_depth))
  depth_w = max(1, int(w * edge_depth))
  overlay = out.copy()
  alpha = 0.35
  color = (0, 200, 255)

  cv2.rectangle(overlay, (0, 0), (w, depth_h), color, -1)
  cv2.rectangle(overlay, (0, h - depth_h), (w, h), color, -1)
  cv2.rectangle(overlay, (0, 0), (depth_w, h), color, -1)
  cv2.rectangle(overlay, (w - depth_w, 0), (w, h), color, -1)
  cv2.addWeighted(overlay, alpha, out, 1 - alpha, 0, out)
  return out


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

  led_w_h = max(1, preview_w // n_top)
  led_h_v = max(1, preview_h // n_right)

  top_c, right_c, bottom_c, left_c = _split_colors(colors, led_layout)

  for j, c in enumerate(top_c):
    x1 = s + j * led_w_h
    cv2.rectangle(canvas, (x1, 0), (x1 + led_w_h, s), c.tolist(), -1)

  for j, c in enumerate(bottom_c):
    x1 = s + j * led_w_h
    cv2.rectangle(canvas, (x1, win_h - s), (x1 + led_w_h, win_h), c.tolist(), -1)

  for j, c in enumerate(left_c):
    y1 = s + j * led_h_v
    cv2.rectangle(canvas, (0, y1), (s, y1 + led_h_v), c.tolist(), -1)

  for j, c in enumerate(right_c):
    y1 = s + j * led_h_v
    cv2.rectangle(canvas, (win_w - s, y1), (win_w, y1 + led_h_v), c.tolist(), -1)

  return canvas


def process_frame(config: dict, raw_frame: np.ndarray) -> PreviewResult:
  """Run warp → extract → post_process and build preview images."""
  points = config["perspective"]["points"]
  edge_depth = float(config["color"]["edge_depth"])
  led_layout = config["wled"]["led_layout"]

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
  warped_annotated = annotate_warped(warped, edge_depth)
  led_overlay = render_led_overlay(warped, colors_final, led_layout)

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
  )


def encode_jpeg(frame_rgb: np.ndarray, quality: int = 85) -> bytes:
  """Encode an RGB frame as JPEG bytes."""
  bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
  ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
  if not ok:
    raise RuntimeError("JPEG encode failed")
  return buf.tobytes()
