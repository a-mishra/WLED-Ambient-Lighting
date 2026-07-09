"""Factory functions for creating camera and WLED instances.

Reads the simulator flags from config and returns either the real hardware
implementation or the corresponding simulator. main.py never imports hardware
classes directly — it always goes through this factory.
"""

import logging

from .base import CameraBase, WLEDBase

logger = logging.getLogger(__name__)


def create_camera(config: dict) -> CameraBase:
    """Return a CameraBase instance based on config.

    If simulator.camera.enabled is true, returns SimCamera.
    Otherwise returns PiCamera (requires picamera2 on Raspberry Pi).
    """
    sim_cfg = config.get("simulator", {}).get("camera", {})
    if sim_cfg.get("enabled", False):
        from .sim.sim_camera import SimCamera

        logger.info("Camera: using SimCamera (simulator.camera.enabled=true)")
        return SimCamera(config)

    from .camera import PiCamera

    logger.info("Camera: using PiCamera (real hardware)")
    return PiCamera(config)


def create_wled(config: dict) -> WLEDBase:
    """Return a WLEDBase instance based on config.

    If simulator.wled.enabled is true, returns SimWLED.
    Otherwise returns WLEDController (real UDP output).
    """
    sim_cfg = config.get("simulator", {}).get("wled", {})
    if sim_cfg.get("enabled", False):
        from .sim.sim_wled import SimWLED

        logger.info("WLED: using SimWLED (simulator.wled.enabled=true)")
        return SimWLED(config)

    from .wled import WLEDController

    logger.info("WLED: using WLEDController (real hardware at %s)", config["wled"]["ip"])
    return WLEDController(config)
