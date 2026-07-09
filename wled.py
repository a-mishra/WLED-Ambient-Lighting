import socket
import logging
from config import load_config

config = load_config()
WLED_IP = config["WLED_IP"]
WLED_PORT = config["WLED_PORT"]
H_SEGMENTS = config["H_SEGMENTS"]
V_SEGMENTS = config["V_SEGMENTS"]
TOTAL_LEDS = 280  # Default WLED installation has 100 LEDs


class WLEDController:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.logger = logging.getLogger('WLED_ambient_lighting')

    def send_colors(self, colors):
        """Sends colors to WLED in a single contiguous strip since no segments are configured."""
        packet = bytearray([2, 255])  # "2" for real-time mode
        
        led_colors = [(0, 0, 0)] * TOTAL_LEDS  # Default all LEDs to black
        
        # Distribute colors across the LED strip
        color_keys = list(colors.keys())
        num_colors = len(color_keys)
        
        if num_colors > 0:
            leds_per_section = TOTAL_LEDS // num_colors
            remainder = TOTAL_LEDS % num_colors
            
            index = 0
            for i, key in enumerate(color_keys):
                color = colors[key]
                count = leds_per_section + (1 if i < remainder else 0)  # Distribute remainder evenly
                for _ in range(count):
                    if index < TOTAL_LEDS:
                        led_colors[index] = color
                        index += 1
        
        # Convert to packet format
        for color in led_colors:
            packet.extend(color)

        try:
            self.sock.sendto(packet, (WLED_IP, WLED_PORT))
            self.logger.info(f"Sent colors to WLED: {colors}")
        except Exception as e:
            self.logger.error(f"Error sending data to WLED: {e}")

    def close(self):
        """Closes the socket."""
        self.sock.close()
