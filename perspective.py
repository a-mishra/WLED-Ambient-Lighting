import cv2
import numpy as np
from config import load_config

def correct_perspective(frame, src_points):
    """
    Applies a perspective transformation to warp the selected area to a 16:9 frame.
    
    :param frame: The original frame from the camera.
    :param src_points: The four corner points of the TV screen in the frame.
    :return: The transformed frame.
    """
    config = load_config()
    width, height = config['OUTPUT_RESOLUTION']  # Target resolution (16:9)

    if not src_points or len(src_points) != 4:
        raise ValueError("Invalid perspective points. Expected 4 corner points.")

    # Define destination points for the 16:9 output
    dst_points = np.array([
        [0, 0], [width - 1, 0],
        [width - 1, height - 1], [0, height - 1]
    ], dtype=np.float32)

    # Compute the perspective transform matrix
    matrix = cv2.getPerspectiveTransform(np.array(src_points, dtype=np.float32), dst_points)

    # Apply the transformation
    corrected_frame = cv2.warpPerspective(frame, matrix, (width, height))
    return corrected_frame
