import asyncio
import time
from config import load_config
from camera import Camera
from color_processing import get_edge_colors, smooth_color
from wled import WLEDController
from log_config import setup_logging
from perspective import correct_perspective
from detect_perspective import detect_and_update_perspective
from draw_color_plot import set_colors

async def update_graph(color_history, smoothing_window):
    """Update the Matplotlib graph asynchronously every second."""
    while True:
        if color_history:
            avg_colors = {}
            for key in color_history[0].keys():
                avg_colors[key] = tuple(
                    sum(c.get(key, (0, 0, 0))[i] for c in color_history[-smoothing_window:]) // smoothing_window
                    for i in range(3)
                )
            set_colors(avg_colors)  # Update the graph
        await asyncio.sleep(1)  # Update every second

async def main_loop(camera, wled, logger, color_history, smoothing_window):
    """Main loop for processing frames and updating WLED."""
    config = load_config()

    while True:
        frame = camera.capture_frame()

        # Apply perspective correction
        corrected_frame = correct_perspective(frame, config['PERSPECTIVE_POINTS'])

        # Get dominant colors for edge segments
        edge_colors = get_edge_colors(corrected_frame)

        # Store in history
        color_history.append(edge_colors)
        if len(color_history) > smoothing_window:
            color_history.pop(0)  # Maintain fixed history size

        # Compute smoothed colors (only if history is populated)
        if color_history:
            smoothed_colors = {}
            for key in edge_colors.keys():
                smoothed_colors[key] = tuple(
                    sum(c.get(key, (0, 0, 0))[i] for c in color_history[-smoothing_window:]) // smoothing_window
                    for i in range(3)
                )

            # Send colors to WLED
            wled.send_colors(smoothed_colors)
            logger.info(f"Sent colors to WLED: {smoothed_colors}")

        await asyncio.sleep(0.05)  # Short delay to prevent overloading

async def main():
    # Setup logging
    logger = setup_logging()

    # Load config
    config = load_config()
    logger.info("Configuration loaded successfully.")

    # Detect and update perspective points before starting
    # detect_and_update_perspective()
    
    # Reload updated config after detection
    config = load_config()

    # Initialize camera and WLED controller
    camera = Camera(resolution=tuple(config['RESOLUTION']))
    wled = WLEDController()

    # Initialize color history and smoothing window
    color_history = []
    smoothing_window = max(config.get("SMOOTHING_WINDOW", 1), 1)  # Ensure min 1

    # Show initial empty plot
    set_colors({})

    try:
        await asyncio.gather(
            main_loop(camera, wled, logger, color_history, smoothing_window),
            update_graph(color_history, smoothing_window)
        )
    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        camera.close()
        wled.close()
        logger.info("Application closed.")

if __name__ == "__main__":
    asyncio.run(main())
