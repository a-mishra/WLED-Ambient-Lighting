import cv2
from picamera2 import Picamera2
import logging

class Camera:
    def __init__(self, resolution=(320, 240)):
        self.picam2 = Picamera2()
        self.picam2.configure(self.picam2.create_preview_configuration(main={"format": "RGB888", "size": resolution}))
        self.picam2.set_controls({
            "AwbEnable": True,      # Enable auto white balance  
            "AeEnable": True,       # Enable auto exposure
            "AnalogueGain": 3.0,    # Increase gain for higher brightness (try values between 1.0 and 5.0)
            "ExposureTime": 10000,  # Increase exposure time (longer exposure time means more light capture)
        })
        self.picam2.start()
        self.logger = logging.getLogger('WLED_ambient_lighting')

    def capture_frame(self):
        """Captures a frame and converts it to RGB."""
        try:
            frame = self.picam2.capture_array()
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception as e:
            self.logger.error(f"Error capturing frame: {e}")
            raise

    def close(self):
        """Closes the camera."""
        self.picam2.close()
