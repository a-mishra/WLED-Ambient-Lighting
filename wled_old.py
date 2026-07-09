import socket
import logging
from config import load_config

config = load_config()
WLED_IP = config["WLED_IP"]
WLED_PORT = config["WLED_PORT"]
H_SEGMENTS = config["H_SEGMENTS"]
V_SEGMENTS = config["V_SEGMENTS"]


class WLEDController:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.segments = self._generate_segments()
        self.logger = logging.getLogger('WLED_ambient_lighting')

    def _generate_segments(self):
        """Dynamically generate WLED segment mappings."""
        segments = {}
        index = 0
        for i in range(H_SEGMENTS):
            segments[f"top-{i}"] = index
            index += 1
        for i in range(H_SEGMENTS):
            segments[f"bottom-{i}"] = index
            index += 1
        for i in range(V_SEGMENTS):
            segments[f"left-{i}"] = index
            index += 1
        for i in range(V_SEGMENTS):
            segments[f"right-{i}"] = index
            index += 1
        return segments

    def send_colors(self, colors):
        """Sends different colors to different WLED segments over UDP."""
        packet = bytearray([2])  # "2" for real-time mode

        for key in self.segments:
            color = colors.get(key, (0, 0, 0))  # Default to black if no color detected
            packet.extend(color)

        try:
            self.sock.sendto(packet, (WLED_IP, WLED_PORT))
            self.logger.info(f"Sent colors to WLED: {colors}")
        except Exception as e:
            self.logger.error(f"Error sending data to WLED: {e}")

    def close(self):
        """Closes the socket."""
        self.sock.close()
