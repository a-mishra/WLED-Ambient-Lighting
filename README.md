# WLED TV Ambient Lighting

A TV ambient backlight system for Raspberry Pi Zero 2W. Captures the TV image
with a camera, extracts edge colours, and streams them to a WLED LED strip at
up to 24fps via UDP.

## Quick Start

```bash
# Install dependencies
pip install opencv-python numpy PyYAML scipy picamera2 pygame

# Edit your WLED IP, LED count, and strip routing (start corner + direction)
nano config/config.yaml

# Optional: autostart web UI on boot + Start/Stop ambient from browser
bash scripts/install-systemd.sh

# Calibrate camera perspective (point camera at TV)
# On Pi OS Lite (headless) — use the web UI from a phone or PC browser:
python -m tools.web_config --port 8080 --exit-on-idle
# Or with a display attached:
python -m tools.calibrate_manual

# Run
python main.py

# Run with full simulator (no Pi or WLED needed)
python main.py --sim
```

## Documentation

| Doc | Contents |
|---|---|
| [Overview & Design](docs/overview.md) | What it does, hardware setup, performance design, architecture decisions |
| [Program Structure](docs/structure.md) | Directory layout, data flow, per-module responsibilities |
| [Getting Started](docs/getting_started.md) | Installation, calibration, running, tuning |
| [Config Reference](docs/config_reference.md) | Every config key explained with types, defaults, and guidance |

## Running Tests

```bash
pytest tests/ -v   # all tests pass without real hardware
```
