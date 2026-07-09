import cv2
import json
import numpy as np
from camera import Camera
from config import load_config, save_config

# List to store selected points
selected_points = []

def mouse_callback(event, x, y, flags, param):
    """Handles mouse clicks to select four points."""
    global selected_points, frame

    if event == cv2.EVENT_LBUTTONDOWN:
        if len(selected_points) < 4:
            selected_points.append((x, y))
            print(f"Point {len(selected_points)} selected: {x, y}")

            # Draw a small circle on the frame where the user clicked
            cv2.circle(frame, (x, y), 5, (0, 0, 255), -1)
            cv2.imshow("Select Perspective Points", frame)

        if len(selected_points) == 4:
            print("All 4 points selected. Press any key to save and exit.")

def main():
    global frame, selected_points
    
    # Load current config
    config = load_config()
    
    # Load camera
    camera = Camera(resolution=tuple(config['RESOLUTION']))
    frame = camera.capture_frame()
    camera.close()

    if not frame.any():
        print("Error: Could not capture frame.")
        return
    
    # Display frame and collect points
    cv2.imshow("Select Perspective Points", frame)
    cv2.setMouseCallback("Select Perspective Points", mouse_callback)
    
    print("Click on the four corners of the TV screen in order (top-left, top-right, bottom-right, bottom-left).")
    
    cv2.waitKey(0)  # Wait until user presses a key
    cv2.destroyAllWindows()

    # Ensure exactly 4 points are selected
    if len(selected_points) != 4:
        print("Error: You must select exactly 4 points.")
        return
    
    # Save new perspective points
    config["PERSPECTIVE_POINTS"] = selected_points
    save_config(config)
    
    print("Perspective points saved to config.json:", selected_points)

if __name__ == "__main__":
    main()
