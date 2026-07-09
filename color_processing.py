import cv2
import numpy as np
from collections import deque
import logging
from config import load_config

config = load_config()
H_SEGMENTS = config["H_SEGMENTS"]
V_SEGMENTS = config["V_SEGMENTS"]
SMOOTHING_WINDOW = config["SMOOTHING_WINDOW"]

# Color smoothing history
color_history = {}

# Logger
logger = logging.getLogger('WLED_ambient_lighting')

def initialize_color_history():
    """Initialize smoothing history for all segments."""
    global color_history
    color_history = {f"{edge}-{i}": deque(maxlen=SMOOTHING_WINDOW)
                     for edge in ["top", "bottom", "left", "right"]
                     for i in range(max(H_SEGMENTS, V_SEGMENTS))}

initialize_color_history()

def get_dominant_color(frame, k=1):
    """Extracts the dominant color from an image using k-means clustering."""
    try:
        pixels = frame.reshape(-1, 3)
        pixels = np.float32(pixels)

        _, labels, palette = cv2.kmeans(pixels, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0), 10, cv2.KMEANS_RANDOM_CENTERS)
        dominant = palette[np.argmax(np.bincount(labels.flatten()))]

        return tuple(map(int, dominant))
    except Exception as e:
        logger.error(f"Error extracting dominant color: {e}")
        raise

def get_edge_colors(frame):
    """Splits edges into dynamic segments and finds dominant colors."""
    h, w, _ = frame.shape
    seg_h = h // V_SEGMENTS  # Segment height for left and right edges
    seg_w = w // H_SEGMENTS  # Segment width for top and bottom edges

    edge_colors = {}

    # Top and bottom edges
    for i in range(H_SEGMENTS):
        edge_colors[f"top-{i}"] = get_dominant_color(frame[0:seg_h, i * seg_w:(i + 1) * seg_w])


    # Left and right edges
    for i in range(V_SEGMENTS):
        edge_colors[f"right-{i}"] = get_dominant_color(frame[i * seg_h:(i + 1) * seg_h, -seg_w:])


    # Top and bottom edges
    for i in range(H_SEGMENTS):
        edge_colors[f"bottom-{i}"] = get_dominant_color(frame[-seg_h:, i * seg_w:(i + 1) * seg_w])

    # Left and right edges
    for i in range(V_SEGMENTS):
        edge_colors[f"left-{i}"] = get_dominant_color(frame[i * seg_h:(i + 1) * seg_h, 0:seg_w])


    return edge_colors

def smooth_color(key, new_color):
    """Applies a moving average filter to smooth color transitions."""
    color_history[key].append(new_color)
    smoothed_color = np.mean(color_history[key], axis=0)
    return tuple(map(int, smoothed_color))
