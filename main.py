import time
# import logging
# import cv2
from config import load_config
from camera import Camera
from color_processing import get_edge_colors, smooth_color
from wled import WLEDController
from log_config import setup_logging
from perspective import correct_perspective
from detect_perspective import detect_and_update_perspective
from draw_color_plot import set_colors  # Import the plot functions

def main():
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

    # Show the plot once
    # show_plot()
    # set_colors({})
    
    try:
        while True:
            frame = camera.capture_frame()

            # Apply perspective correction
            corrected_frame = correct_perspective(frame, config['PERSPECTIVE_POINTS'])

            # Get dominant colors for edge segments
            edge_colors = get_edge_colors(corrected_frame)

            # Apply smoothing
            # smoothed_colors = {key: smooth_color(key, color) for key, color in edge_colors.items()}
            smoothed_colors = edge_colors

            # Send colors to WLED
            wled.send_colors(smoothed_colors)
            logger.info(f"Sent colors to WLED: {smoothed_colors}")

            # Update the plot with the new colors
            # set_colors(smoothed_colors)

            time.sleep(0.1)  # Small delay to prevent overloading

    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        camera.close()
        wled.close()
        logger.info("Application closed.")

if __name__ == "__main__":
    main()
