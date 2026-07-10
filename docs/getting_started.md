# Getting Started

## 1. Install Dependencies

**On Raspberry Pi:**
```bash
pip install opencv-python numpy PyYAML scipy picamera2 pygame
```

**On a PC (for simulation / development):**
```bash
pip install opencv-python numpy PyYAML scipy pygame pytest
# picamera2 is not needed — the simulator replaces it
```

> `pygame` is only required if you want the visual `window` simulator display.
> The `console` and `none` display modes work without it.

---

## 2. Configure WLED

Before running this program, set up WLED on your ESP8266/ESP32:

1. Flash WLED firmware (see [kno.wled.ge](https://kno.wled.ge))
2. In the WLED web UI → Config → LED Preferences:
   - Set LED count to match your strip (default: 268 total)
   - Enable **Realtime** → UDP
3. Note the WLED device IP address

Update `config/config.yaml`:
```yaml
wled:
  ip: "192.168.1.77"   # ← your WLED device IP
```

---

## 3. Calibrate the Camera (Perspective)

The program needs to know where the TV corners appear in the camera frame.
Run this **once** (or whenever the camera moves):

### Option A — Web UI (recommended for Pi OS Lite / SSH)

Stop `main.py` first if it is running (only one process can use the camera at a time).

```bash
python -m tools.web_config --port 8080 --exit-on-idle --idle-timeout 300
```

Open `http://<pi-ip>:8080` from a phone or PC on the same network.

1. **Preview** tab → **Capture** (grabs one camera frame)
2. Click the four TV corners on the raw image: **TL → TR → BR → BL**
3. **Save calibration**
4. Use **Reprocess** after changing color/WLED settings to refresh the preview panels
5. Tune other settings on the Camera / Color / WLED / Processing tabs

The server does not touch the camera until you click Capture. With `--exit-on-idle`, it shuts down automatically after 5 minutes of no browser activity.

> Config changes saved via the web UI take effect in `main.py` after you restart it.

### Option B — Manual (display attached)

Display a solid white image on the TV, then:

```bash
python -m tools.calibrate_manual
```

Click the four corners of the TV in order: **TL → TR → BR → BL**.
Press **Enter** to save. The points are written to `config/config.yaml`.

### Option C — Automatic

```bash
# Show a solid white image on the TV first, then:
python -m tools.calibrate_auto --preview
```

Add `--threshold 180` if the TV isn't detected (lower = more sensitive).
The `--preview` flag shows the detected corners before saving.

---

## 4. Run the Program

### On Raspberry Pi (real hardware):
```bash
python main.py
```

### On a PC (full simulator — no camera, no WLED):
```bash
python main.py --sim
```

### Mixed modes:
```bash
python main.py --sim-camera   # SimCamera + real WLED output
python main.py --sim-wled     # Real camera + SimWLED pygame window
```

### With benchmark mode (measure per-stage timing):
Set `processing.benchmark_mode: true` in `config/config.yaml`, then run normally.
Output looks like:
```
[BENCH] cap=0.0ms warp=3.8ms ext=2.9ms post=0.3ms smo=0.4ms send=0.9ms total=8.3ms
```

### Using a custom config file:
```bash
python main.py --config /path/to/my_config.yaml
```

---

## 5. Run the Tests

```bash
pytest tests/ -v
```

All 60 tests run without real hardware (picamera2, WLED, or a display).

---

## 6. Tune for Your Setup

### If 24fps is not being achieved

1. Enable benchmark mode (`processing.benchmark_mode: true`) to see which stage is slow.
2. If `warp` is the bottleneck, the `output_resolution` is too large. Try `[120, 68]`.
3. If `ext` is slow, reduce `color.edge_depth` (e.g. `0.03` instead of `0.05`).
4. Enable remap mode (`color.use_remap: true`) to skip the full warp — the
   extractor then samples the raw frame directly using pre-computed maps.

### If colours look wrong

- Run calibration again (`calibrate_manual.py`) — the camera may have moved.
- Increase `color.saturation_boost` (e.g. `1.5`) if colours look washed out.
- Adjust `color.gamma`: `2.2` is standard; lower values (e.g. `1.8`) make LEDs
  brighter at midtones.

### If transitions are too fast / too slow

Adjust `color.smoothing.alpha` in `config.yaml`:

| Alpha | Effect |
|---|---|
| `1.0` | Instant — no smoothing at all |
| `0.5` | Fast — half-life of ~1 frame |
| `0.3` | Moderate — good for action content |
| `0.1` | Slow — dreamy transitions, good for ambient/music |

### If LEDs at strip edges don't match the TV corners

Set `wled.strip_start` and `wled.strip_direction` to match where physical LED 0 sits and
which way the strip runs around the TV (viewed from the front). `wled.led_layout` defines
how many LEDs are on each side in logical order `top → right → bottom → left` (any side
may be `0` if unused). Restart `main.py` after changing strip routing.

Example — strip starts bottom-right, runs counter-clockwise, no bottom LEDs:

```yaml
wled:
  strip_start: bottom_right
  strip_direction: ccw
  led_layout:
    top: 72
    right: 40
    bottom: 0
    left: 40
```

---

## Simulator Modes Quick Reference

| Flag / Setting | Camera source | WLED output |
|---|---|---|
| `python main.py` | Picamera2 (Pi only) | Real UDP |
| `python main.py --sim` | Synthetic frames | Console/window |
| `python main.py --sim-camera` | Synthetic frames | Real UDP |
| `python main.py --sim-wled` | Picamera2 | Pygame window |
| `simulator.camera.source: video` | MP4 file | — |
| `simulator.camera.source: image` | JPEG file | — |
| `simulator.wled.display: window` | — | Pygame LED ring |
| `simulator.wled.display: console` | — | ANSI terminal |
| `simulator.wled.display: none` | — | No-op |
