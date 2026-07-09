"""Tests for SimCamera, SimWLED, and the factory.

These tests run entirely without real hardware, pygame, or picamera2.
"""

import time
import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.sim.sim_camera import SimCamera
from ambient.sim.sim_wled import SimWLED
from ambient.factory import create_camera, create_wled


def _cam_config(source="synthetic", pattern="solid", color=None, resolution=(160, 90)):
    if color is None:
        color = [255, 0, 0]
    return {
        "camera": {
            "resolution": list(resolution),
            "awb_enable": True,
            "ae_enable": True,
            "analogue_gain": 1.0,
            "exposure_time": 10000,
        },
        "simulator": {
            "camera": {
                "enabled": True,
                "source": source,
                "video_path": "tests/assets/sample.mp4",
                "image_path": "tests/assets/sample.jpg",
                "synthetic": {"pattern": pattern, "color": color},
                "loop": True,
                "fps": 30,
            }
        },
    }


def _wled_config(display="none"):
    return {
        "wled": {
            "led_layout": {"top": 10, "right": 6, "bottom": 10, "left": 6}
        },
        "perspective": {
            "output_resolution": [160, 90]
        },
        "simulator": {
            "wled": {
                "enabled": True,
                "display": display,
                "window_title": "Test",
                "window_scale": 2,
                "show_frame_preview": False,
            }
        },
    }


# ------------------------------------------------------------------
# SimCamera tests
# ------------------------------------------------------------------

class TestSimCamera:
    def _wait_for_frame(self, cam, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            f = cam.get_latest_frame()
            if f is not None:
                return f
            time.sleep(0.05)
        return None

    def test_synthetic_solid_frame_shape(self):
        cam = SimCamera(_cam_config(source="synthetic", pattern="solid"))
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None
        assert frame.shape == (90, 160, 3)
        assert frame.dtype == np.uint8

    def test_synthetic_gradient_frame_shape(self):
        cam = SimCamera(_cam_config(source="synthetic", pattern="gradient"))
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None
        assert frame.shape == (90, 160, 3)

    def test_synthetic_colorbar_frame_shape(self):
        cam = SimCamera(_cam_config(source="synthetic", pattern="colorbar"))
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None
        assert frame.shape == (90, 160, 3)

    def test_synthetic_noise_frame_shape(self):
        cam = SimCamera(_cam_config(source="synthetic", pattern="noise"))
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None
        assert frame.shape == (90, 160, 3)

    def test_solid_red_frame_is_red(self):
        cam = SimCamera(_cam_config(source="synthetic", pattern="solid", color=[200, 0, 0]))
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None
        assert frame[:, :, 0].mean() > 150, "R channel should dominate"
        assert frame[:, :, 1].mean() < 10
        assert frame[:, :, 2].mean() < 10

    def test_frames_change_over_time_for_gradient(self):
        cam = SimCamera(_cam_config(source="synthetic", pattern="gradient"))
        f1 = self._wait_for_frame(cam)
        time.sleep(0.2)
        f2 = cam.get_latest_frame()
        cam.close()
        # Gradient frame_index advances — frames should differ
        assert not np.array_equal(f1, f2), "Gradient frames should change over time"

    def test_missing_video_falls_back_to_synthetic(self):
        cfg = _cam_config(source="video")
        cfg["simulator"]["camera"]["video_path"] = "nonexistent.mp4"
        cam = SimCamera(cfg)
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None

    def test_missing_image_falls_back_to_synthetic(self):
        cfg = _cam_config(source="image")
        cfg["simulator"]["camera"]["image_path"] = "nonexistent.jpg"
        cam = SimCamera(cfg)
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None

    def test_custom_resolution(self):
        cam = SimCamera(_cam_config(resolution=(80, 60)))
        frame = self._wait_for_frame(cam)
        cam.close()
        assert frame is not None
        assert frame.shape == (60, 80, 3)


# ------------------------------------------------------------------
# SimWLED tests (display=none to avoid pygame)
# ------------------------------------------------------------------

class TestSimWLED:
    def _colors(self, n=32):
        return np.random.randint(0, 256, (n, 3), dtype=np.uint8)

    def test_none_display_accepts_send(self):
        wled = SimWLED(_wled_config(display="none"))
        colors = self._colors(32)
        wled.send(colors)  # should not raise
        wled.close()

    def test_console_display_prints(self, capsys):
        wled = SimWLED(_wled_config(display="console"))
        wled.send(self._colors(32))
        wled.close()
        out = capsys.readouterr().out
        assert "TOP:" in out

    def test_close_is_safe_to_call_multiple_times(self):
        wled = SimWLED(_wled_config(display="none"))
        wled.close()
        wled.close()  # should not raise


# ------------------------------------------------------------------
# Factory tests
# ------------------------------------------------------------------

class TestFactory:
    def test_factory_returns_sim_camera_when_enabled(self):
        config = _cam_config(source="synthetic")
        cam = create_camera(config)
        assert isinstance(cam, SimCamera)
        cam.close()

    def test_factory_returns_sim_wled_when_enabled(self):
        from ambient.sim.sim_wled import SimWLED as SW
        config = {**_wled_config(display="none")}
        wled = create_wled(config)
        assert isinstance(wled, SW)
        wled.close()

    def test_factory_raises_for_real_camera_without_picamera2(self):
        from ambient.camera import _PICAMERA2_AVAILABLE
        if _PICAMERA2_AVAILABLE:
            pytest.skip("picamera2 is available on this machine")

        from ambient.camera import PiCamera
        with pytest.raises(RuntimeError, match="picamera2"):
            PiCamera({"camera": {
                "resolution": [320, 240],
                "awb_enable": True, "ae_enable": True,
                "analogue_gain": 1.0, "exposure_time": 10000,
            }})
