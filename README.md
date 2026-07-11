# WLED TV Ambient Lighting

A TV ambient backlight system for Raspberry Pi Zero 2W. A camera captures the TV image, edge colours are extracted, and the result is streamed to a WLED LED strip at up to ~24 fps over UDP.

**Typical hardware:** Pi Zero 2W, Pi Camera v1.3/v2, ESP8266/ESP32 running WLED, WS2812B/SK6812 strip around the TV.

---

## First-time setup (Raspberry Pi)

```bash
# Clone and enter project
cd ~/projects
git clone <your-repo-url> WLED-Ambient-Lighting
cd WLED-Ambient-Lighting

# System packages (Pi OS Lite)
sudo apt update
sudo apt install -y python3-pip python3-venv python3-picamera2 libatlas-base-dev

# Python venv (reuse system picamera2)
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
```

### WLED firmware

1. Flash [WLED](https://kno.wled.ge) on your controller.
2. WLED web UI → **Config → LED Preferences:** set total LED count to match your strip.
3. WLED web UI → **Config → Sync Interfaces:** enable **UDP Realtime**, port **21324**.
4. Note the WLED IP address (e.g. `192.168.1.210`).

### Edit `config/config.yaml`

Minimum settings before first run:

```yaml
wled:
  ip: "192.168.1.210"        # your WLED IP
  strip_start: bottom_right    # where physical LED 0 sits
  strip_direction: ccw         # cw or ccw around the TV
  led_layout:
    top: 72
    right: 40
    bottom: 0                  # 0 = no LEDs on that side
    left: 40                   # total must match WLED LED count (152 here)

camera:
  rgb_swap: true               # fix red/blue swap on Pi Camera (toggle if colours wrong)

color:
  edge_depth:
    horizontal: 0.05
    vertical: 0.05
  sampling_enabled:
    top: true
    right: true
    bottom: true
    left: true
  show_sampling_bands: true
```

All of these can also be changed in the **web UI** after install (see below).

---

## Recommended: systemd services + web UI

The easiest way to run and manage the project on a headless Pi is to install the included **user systemd units**. The web config server autostarts on boot; the ambient pipeline is started and stopped from the browser.

### Install (one time)

```bash
cd ~/projects/WLED-Ambient-Lighting
source .venv/bin/activate
git pull
bash scripts/install-systemd.sh
```

This installs:

| Service | Autostart on boot? | What it runs |
|---------|-------------------|--------------|
| `wled-web-config.service` | **Yes** | Web UI at `http://<pi-ip>:8080` |
| `wled-ambient.service` | **No** | `main.py` — live camera → WLED pipeline |

The script also runs `loginctl enable-linger` so services keep running after you disconnect SSH.

### Open the web UI

From any device on your LAN:

```
http://192.168.1.200:8080
```

(Replace with your Pi’s IP.)

### Web UI — what you can do

| Area | Tabs / controls |
|------|-----------------|
| **Service bar** (top) | **Start ambient** / **Stop ambient**, **Shutdown Pi**, live status |
| **Preview** | Capture frame, click or type TV corners, save calibration, reprocess preview |
| **Perspective** | Warp output resolution |
| **Camera** | Resolution, rgb_swap, exposure, gain |
| **Color** | Band depth (horizontal/vertical), per-side sampling on/off, disabled fill, saturation, gamma, smoothing |
| **WLED** | IP, port, strip start/direction, LEDs per side |
| **Processing** | FPS, logging, benchmark, systemd unit name |

Saving any tab or calibration shows a **confirmation dialog** listing exactly what will change in `config.yaml` before writing.

**Shutdown Pi** stops ambient first, then runs `sudo shutdown -h now`. The Pi user needs passwordless sudo for `/sbin/shutdown` (see Troubleshooting).

### Typical workflow

1. **Stop ambient** (frees the camera).
2. **Preview** → **Capture** → set four corners (click or manual X/Y) → **Save calibration**.
3. Tune **Camera**, **Color**, **WLED** tabs as needed; click **Reprocess** on Preview to refresh debug images.
   - Panel 2 shows sampling bands: **cyan** = active sampling, **red** = side disabled (filled with black or brightness floor).
4. **Start ambient** — LEDs follow the TV.

After changing WLED IP, strip routing, or camera settings: **Stop** → **Start** ambient to reload config.

> Only one process can use the camera at a time. If Capture fails with “camera busy”, stop ambient first.

### Manage services from SSH

```bash
# Web UI
systemctl --user status wled-web-config.service
systemctl --user restart wled-web-config.service
journalctl --user -u wled-web-config.service -f

# Ambient pipeline (main.py)
systemctl --user status wled-ambient.service
systemctl --user start wled-ambient.service
systemctl --user stop wled-ambient.service
journalctl --user -u wled-ambient.service -f

# Disable autostart (web UI only)
systemctl --user disable wled-web-config.service
```

### Re-install after moving the project

If you clone to a different path, re-run `bash scripts/install-systemd.sh` so unit files point at the correct directory and venv.

---

## Manual run (without systemd)

Useful for development or one-off testing.

```bash
source .venv/bin/activate

# Web config only (manual start; exits after idle if --exit-on-idle is set)
python -m tools.web_config --port 8080 --host 0.0.0.0

# Ambient pipeline only
python main.py

# Full simulator on PC (no Pi camera, no WLED)
python main.py --sim
```

Other flags: `--sim-camera`, `--sim-wled`, `--config path/to/config.yaml`.

---

## Configuration reference

| File | Purpose |
|------|---------|
| `config/config.yaml` | All runtime settings (also editable via web UI) |
| `docs/config_reference.md` | Every key documented |

**Important settings:**

- **`wled.ip`** — must match your WLED device on the LAN.
- **`wled.led_layout`** — LEDs per TV side; sum must equal WLED firmware LED count.
- **`wled.strip_start` / `strip_direction`** — must match physical wire order (see [getting started](docs/getting_started.md)).
- **`camera.rgb_swap`** — enable if red and blue are swapped in preview or on LEDs.
- **`color.edge_depth`** — sampling band thickness; use `horizontal` (top/bottom) and `vertical` (left/right) separately.
- **`color.sampling_enabled`** — turn off a side to fill its LEDs with a fixed colour instead of camera pixels (useful for partial strips).
- **`perspective.points`** — four corners TL→TR→BR→BL in the raw camera frame (set via web Preview or calibrate tools).
- **`processing.ambient_service_unit`** — systemd unit name for web UI Start/Stop (`wled-ambient.service`; empty = subprocess mode).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `WLED send error` / no LED update | Check `wled.ip`, ping WLED, confirm UDP realtime enabled on port 21324, LED count matches layout total |
| Red/blue swapped | Set `camera.rgb_swap: true` in web UI Camera tab |
| LEDs don’t match TV corners | Fix `strip_start` / `strip_direction` / `led_layout`; Stop → Start ambient |
| One side shows wrong colours / should stay off | Disable that side under **Color** → `sampling_enabled`, or set `led_layout` to `0` |
| Capture fails / camera busy | **Stop ambient** in web UI, or `systemctl --user stop wled-ambient.service` |
| Web UI not reachable after reboot | `systemctl --user status wled-web-config.service`; re-run `install-systemd.sh` |
| HyperHDR holds camera | Stop HyperHDR or disable its camera use in `/boot/firmware/config.txt` |
| Shutdown Pi fails from web UI | Allow passwordless shutdown: `sudo visudo` and add `a-mishra ALL=(ALL) NOPASSWD: /sbin/shutdown` (replace username) |

Logs: `app.log` in the project directory (path set in `processing.log_file`).

---

## Documentation

| Doc | Contents |
|-----|----------|
| [Overview & Design](docs/overview.md) | Hardware, performance, architecture |
| [Program Structure](docs/structure.md) | Modules and data flow |
| [Getting Started](docs/getting_started.md) | Full install, calibration, tuning |
| [Config Reference](docs/config_reference.md) | All config keys |

---

## Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

All tests run without real camera or WLED hardware.

---

## Security note

The web config UI has **no authentication**. Use only on a trusted home network. Do not expose port 8080 to the internet.
