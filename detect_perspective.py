import cv2
import numpy as np
import logging
from config import load_config, save_config
from camera import Camera

def find_brightest_area(frame):
    """Finds the brightest area in the frame (assumed to be a white TV screen)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Threshold the image to isolate bright areas
    _, thresholded = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # Find contours in the thresholded image
    contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours:
        # Find the largest contour (brightest area)
        largest_contour = max(contours, key=cv2.contourArea)

        # Get the bounding box of the largest contour
        x, y, w, h = cv2.boundingRect(largest_contour)

        # Define the perspective points based on the bounding box
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    return None

def detect_and_update_perspective():
    """Captures a frame, detects the TV screen, and updates perspective points in config."""
    logger = logging.getLogger(__name__)
    config = load_config()
    camera = Camera(resolution=tuple(config['RESOLUTION']))

    frame = camera.capture_frame()
    if frame is None:
        logger.error("Failed to capture frame for perspective detection.")
        return

    perspective_points = find_brightest_area(frame)

    if perspective_points:
        config['PERSPECTIVE_POINTS'] = perspective_points
        save_config(config)
        logger.info(f"Updated perspective points: {perspective_points}")
    else:
        logger.warning("No bright area detected, keeping existing perspective points.")

    camera.close()

if __name__ == "__main__":
    detect_and_update_perspective()
