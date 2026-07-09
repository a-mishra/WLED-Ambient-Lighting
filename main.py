"""WLED TV Ambient Lighting — main entry point.

Pipeline per frame:
    capture → [warp] → extract → post_process → smooth → send

Performance notes (Pi Zero 2W):
  • cv2.setNumThreads(1) is called at startup — reduces synchronisation overhead
    for the small frame sizes used here.
  • The camera runs in a background thread; get_latest_frame() never blocks.
  • warpPerspective uses INTER_NEAREST (no bilinear, ~20% faster).
  • Edge colors are extracted via cv2.resize(INTER_AREA) — 4 C-level ops total.
  • The UDP packet buffer is pre-allocated; send() does a zero-copy in-place write.
  • Adaptive sleep with frame-drop guard prevents latency accumulation.

Usage:
    python main.py
    python main.py --config path/to/config.yaml
    python main.py --sim          # enable both camera and WLED simulators
    python main.py --sim-camera   # simulate camera only
    python main.py --sim-wled     # simulate WLED only
"""

import argparse
import logging
import time
import sys

import cv2
import numpy as np

from ambient.config import load_config
from ambient.perspective import PerspectiveCorrector
from ambient.color import EdgeColorExtractor
from ambient.smoother import EMASmoother
from ambient.factory import create_camera, create_wled


def setup_logging(config: dict) -> logging.Logger:
    proc = config["processing"]
    level = getattr(logging, proc.get("log_level", "INFO").upper(), logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = proc.get("log_file")
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
    )
    return logging.getLogger("ambient")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WLED TV Ambient Lighting")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--sim", action="store_true", help="Enable both camera and WLED simulators")
    parser.add_argument("--sim-camera", action="store_true", help="Enable camera simulator only")
    parser.add_argument("--sim-wled", action="store_true", help="Enable WLED simulator only")
    return parser.parse_args()


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> dict:
    """Override simulator flags from CLI arguments."""
    sim = config.setdefault("simulator", {})
    sim.setdefault("camera", {})
    sim.setdefault("wled", {})
    if args.sim or args.sim_camera:
        sim["camera"]["enabled"] = True
    if args.sim or args.sim_wled:
        sim["wled"]["enabled"] = True
    return config


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    config = apply_cli_overrides(config, args)

    logger = setup_logging(config)
    logger.info("Starting WLED ambient lighting.")

    proc = config["processing"]
    target_fps: float = float(proc.get("target_fps", 24))
    frame_period: float = 1.0 / target_fps
    benchmark: bool = bool(proc.get("benchmark_mode", False))
    use_remap: bool = bool(config["color"].get("use_remap", False))

    # Apply OpenCV thread count before any cv2 operations
    cv2.setNumThreads(int(proc.get("opencv_threads", 1)))

    # Build pipeline components
    corrector = PerspectiveCorrector(config)
    extractor = EdgeColorExtractor(
        config,
        perspective_matrix=corrector.matrix if use_remap else None,
    )
    smoother = EMASmoother(config, n_leds=extractor.n_total)
    camera = create_camera(config)
    wled = create_wled(config)

    # Check if wled is a SimWLED so we can feed it the preview frame
    from ambient.sim.sim_wled import SimWLED
    is_sim_wled = isinstance(wled, SimWLED)

    logger.info(
        "Pipeline ready. target_fps=%.1f use_remap=%s benchmark=%s",
        target_fps, use_remap, benchmark,
    )

    # Give the camera thread time to produce the first frame
    time.sleep(0.5)

    frame_count = 0
    loop_start = time.perf_counter()

    try:
        while True:
            t_frame_start = time.perf_counter()

            # --- Capture ---
            t0 = time.perf_counter()
            raw_frame = camera.get_latest_frame()
            if raw_frame is None:
                time.sleep(0.01)
                continue
            t_capture = time.perf_counter() - t0

            # --- Warp / remap ---
            t0 = time.perf_counter()
            if use_remap:
                warped = None  # extractor samples from raw_frame directly
            else:
                warped = corrector.correct(raw_frame)
            t_warp = time.perf_counter() - t0

            # Feed preview frame to SimWLED before send
            if is_sim_wled:
                preview = warped if warped is not None else raw_frame
                wled.set_preview_frame(preview)

            # --- Extract ---
            t0 = time.perf_counter()
            source_frame = raw_frame if use_remap else warped
            colors = extractor.extract(source_frame)
            t_extract = time.perf_counter() - t0

            # --- Post-process ---
            t0 = time.perf_counter()
            colors = extractor.post_process(colors)
            t_post = time.perf_counter() - t0

            # --- Smooth ---
            t0 = time.perf_counter()
            colors = smoother.smooth(colors)
            t_smooth = time.perf_counter() - t0

            # --- Send ---
            t0 = time.perf_counter()
            wled.send(colors)
            t_send = time.perf_counter() - t0

            frame_count += 1
            t_total = time.perf_counter() - t_frame_start

            if benchmark:
                logger.info(
                    "[BENCH] cap=%.1fms warp=%.1fms ext=%.1fms post=%.1fms "
                    "smo=%.1fms send=%.1fms total=%.1fms",
                    t_capture * 1000, t_warp * 1000, t_extract * 1000,
                    t_post * 1000, t_smooth * 1000, t_send * 1000,
                    t_total * 1000,
                )

            # --- Adaptive sleep with frame-drop guard ---
            # If this frame took longer than the period, skip sleep and process
            # the next frame immediately to avoid accumulating latency.
            remaining = frame_period - t_total
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        elapsed = time.perf_counter() - loop_start
        avg_fps = frame_count / elapsed if elapsed > 0 else 0
        logger.info(
            "Stopped after %d frames in %.1fs (avg %.1f fps).",
            frame_count, elapsed, avg_fps,
        )
    finally:
        camera.close()
        wled.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
