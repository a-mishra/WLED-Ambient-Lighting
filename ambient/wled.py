"""WLED UDP real-time output controller.

Supports two protocols:
  drgb  — [2, timeout, R0, G0, B0, R1, G1, B1, ...] (3 bytes/LED from LED 0)
  warls — [1, timeout, i0, R0, G0, B0, i1, R1, G1, B1, ...] (4 bytes/LED with index)

The UDP packet buffer is pre-allocated once at construction and updated in-place
each frame via np.copyto — avoids a malloc on every send call.

For a 268-LED strip:
  drgb  packet: 2 + 268×3 =  806 bytes
  warls packet: 2 + 268×4 = 1074 bytes
Both fit comfortably within the 1472-byte safe UDP MTU.
"""

import socket
import numpy as np
import logging

from .base import WLEDBase

logger = logging.getLogger(__name__)

_PROTOCOL_DRGB = 2
_PROTOCOL_WARLS = 1


class WLEDController(WLEDBase):
    """Sends LED colors to WLED over UDP real-time protocol."""

    def __init__(self, config: dict) -> None:
        wled_cfg = config["wled"]
        self._ip: str = wled_cfg["ip"]
        self._port: int = wled_cfg["port"]
        self._protocol: str = wled_cfg.get("protocol", "drgb").lower()
        self._timeout: int = int(wled_cfg.get("timeout", 255))

        led_layout = wled_cfg["led_layout"]
        self._n_leds: int = (
            led_layout["top"]
            + led_layout["right"]
            + led_layout["bottom"]
            + led_layout["left"]
        )

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # No socket timeout — UDP sendto is fire-and-forget; a send timeout can
        # spuriously raise "timed out" on slow/congested WiFi when the kernel
        # cannot immediately queue the datagram.

        # Pre-allocate the UDP packet buffer once
        if self._protocol == "drgb":
            self._packet = bytearray(2 + self._n_leds * 3)
            self._packet[0] = _PROTOCOL_DRGB
            self._packet[1] = self._timeout
            # numpy view into the color region for zero-copy updates
            self._color_buf = np.frombuffer(self._packet, dtype=np.uint8, offset=2).reshape(
                self._n_leds, 3
            )
        else:  # warls
            self._packet = bytearray(2 + self._n_leds * 4)
            self._packet[0] = _PROTOCOL_WARLS
            self._packet[1] = self._timeout
            # Pre-fill LED indices (0–255 max per WARLS spec; wraps for > 256 LEDs)
            for i in range(self._n_leds):
                self._packet[2 + i * 4] = i & 0xFF
            # Separate numpy array for staging — WARLS layout is non-contiguous
            self._color_staging = np.zeros((self._n_leds, 3), dtype=np.uint8)

        logger.info(
            "WLEDController ready: %s:%d protocol=%s n_leds=%d",
            self._ip,
            self._port,
            self._protocol,
            self._n_leds,
        )

    def send(self, colors: np.ndarray) -> None:
        """Write colors into the pre-allocated packet buffer and send via UDP.

        Args:
            colors: uint8 ndarray (n_leds, 3) RGB in physical wire order
                    (LED 0 = first pixel on the strip as configured).
        """
        try:
            if self._protocol == "drgb":
                np.copyto(self._color_buf, colors)
            else:  # warls — interleave index bytes (pre-filled) with color bytes
                np.copyto(self._color_staging, colors)
                for i in range(self._n_leds):
                    offset = 3 + i * 4
                    self._packet[offset : offset + 3] = self._color_staging[i].tobytes()

            self._sock.sendto(self._packet, (self._ip, self._port))

        except OSError as exc:
            logger.error("WLED send error: %s", exc)

    def close(self) -> None:
        self._sock.close()
        logger.info("WLEDController socket closed.")
