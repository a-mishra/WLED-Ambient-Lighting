"""Tests for WLEDController.

Uses a mock socket so no real network is needed. Validates packet structure,
length, and byte positions for both DRGB and WARLS protocols.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.wled import WLEDController


def _make_config(protocol="drgb", n_top=84, n_right=50, n_bottom=84, n_left=50):
    return {
        "wled": {
            "ip": "127.0.0.1",
            "port": 21324,
            "protocol": protocol,
            "timeout": 255,
            "led_layout": {
                "top": n_top,
                "right": n_right,
                "bottom": n_bottom,
                "left": n_left,
            },
        }
    }


def _make_colors(n_leds: int, r=100, g=150, b=200) -> np.ndarray:
    return np.full((n_leds, 3), [r, g, b], dtype=np.uint8)


@pytest.fixture
def mock_socket():
    with patch("socket.socket") as mock_cls:
        mock_sock = MagicMock()
        mock_cls.return_value = mock_sock
        yield mock_sock


class TestDRGB:
    def test_packet_length(self, mock_socket):
        config = _make_config(protocol="drgb")
        ctrl = WLEDController(config)
        n = 268
        ctrl.send(_make_colors(n))
        args = mock_socket.sendto.call_args[0]
        assert len(args[0]) == 2 + n * 3

    def test_protocol_byte(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="drgb"))
        ctrl.send(_make_colors(268))
        pkt = mock_socket.sendto.call_args[0][0]
        assert pkt[0] == 2  # DRGB protocol byte

    def test_timeout_byte(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="drgb"))
        ctrl.send(_make_colors(268))
        pkt = mock_socket.sendto.call_args[0][0]
        assert pkt[1] == 255

    def test_first_led_color_correct(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="drgb"))
        colors = _make_colors(268, r=10, g=20, b=30)
        ctrl.send(colors)
        pkt = mock_socket.sendto.call_args[0][0]
        assert pkt[2] == 10  # R
        assert pkt[3] == 20  # G
        assert pkt[4] == 30  # B

    def test_last_led_color_correct(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="drgb"))
        n = 268
        colors = np.zeros((n, 3), dtype=np.uint8)
        colors[-1] = [77, 88, 99]
        ctrl.send(colors)
        pkt = mock_socket.sendto.call_args[0][0]
        offset = 2 + (n - 1) * 3
        assert pkt[offset] == 77
        assert pkt[offset + 1] == 88
        assert pkt[offset + 2] == 99

    def test_destination_address(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="drgb"))
        ctrl.send(_make_colors(268))
        addr = mock_socket.sendto.call_args[0][1]
        assert addr == ("127.0.0.1", 21324)

    def test_small_layout(self, mock_socket):
        config = _make_config(protocol="drgb", n_top=4, n_right=2, n_bottom=4, n_left=2)
        ctrl = WLEDController(config)
        n = 12
        ctrl.send(_make_colors(n))
        pkt = mock_socket.sendto.call_args[0][0]
        assert len(pkt) == 2 + n * 3


class TestWARLS:
    def test_packet_length(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="warls"))
        n = 268
        ctrl.send(_make_colors(n))
        pkt = mock_socket.sendto.call_args[0][0]
        assert len(pkt) == 2 + n * 4

    def test_protocol_byte(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="warls"))
        ctrl.send(_make_colors(268))
        pkt = mock_socket.sendto.call_args[0][0]
        assert pkt[0] == 1  # WARLS protocol byte

    def test_led_index_bytes(self, mock_socket):
        """WARLS packets should have sequential index bytes."""
        ctrl = WLEDController(_make_config(protocol="warls", n_top=4, n_right=2, n_bottom=4, n_left=2))
        ctrl.send(_make_colors(12))
        pkt = mock_socket.sendto.call_args[0][0]
        for i in range(12):
            assert pkt[2 + i * 4] == i, f"Wrong index at LED {i}"

    def test_first_led_color_correct(self, mock_socket):
        ctrl = WLEDController(_make_config(protocol="warls"))
        colors = _make_colors(268, r=55, g=66, b=77)
        ctrl.send(colors)
        pkt = mock_socket.sendto.call_args[0][0]
        # Format: [1, timeout, i0, R0, G0, B0, i1, R1, G1, B1, ...]
        assert pkt[3] == 55   # R of LED 0
        assert pkt[4] == 66   # G of LED 0
        assert pkt[5] == 77   # B of LED 0


class TestClose:
    def test_close_calls_sock_close(self, mock_socket):
        ctrl = WLEDController(_make_config())
        ctrl.close()
        mock_socket.close.assert_called_once()
