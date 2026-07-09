# Program Structure

## Directory Layout

```
wled_ambient_lighting/
│
├── main.py                     Entry point — run this to start the program
│
├── config/
│   └── config.yaml             All settings (single source of truth)
│
├── ambient/                    Core package
│   ├── base.py                 Abstract interfaces: CameraBase, WLEDBase
│   ├── config.py               YAML loader / saver
│   ├── camera.py               Real camera: PiCamera (Picamera2 + background thread)
│   ├── perspective.py          Perspective correction: PerspectiveCorrector
│   ├── color.py                Edge colour extraction + post-processing: EdgeColorExtractor
│   ├── smoother.py             Temporal smoothing: EMASmoother
│   ├── wled.py                 Real WLED UDP output: WLEDController
│   ├── factory.py              Wires config → real or simulated instances
│   └── sim/
│       ├── sim_camera.py       Simulated camera: video / image / synthetic frames
│       └── sim_wled.py         Simulated WLED: pygame window / ANSI console / none
│
├── tools/
│   ├── calibrate_manual.py     Click four TV corners → saves perspective points
│   └── calibrate_auto.py       Auto-detect TV via brightness → saves perspective points
│
├── tests/
│   ├── test_config.py          Config schema validation
│   ├── test_perspective.py     Warp accuracy with synthetic frames
│   ├── test_color.py           Colour extraction and post-processing
│   ├── test_smoother.py        EMA convergence and edge cases
│   ├── test_wled.py            UDP packet structure (DRGB and WARLS)
│   └── test_sim.py             SimCamera, SimWLED, factory
│
├── requirements.txt
└── docs/                       ← you are here
```

---

## Per-Frame Data Flow

```
CameraBase.get_latest_frame()
        │
        │  raw RGB frame  (H × W × 3  uint8)
        ▼
PerspectiveCorrector.correct()          ← skipped if use_remap=true
        │
        │  warped frame   (out_h × out_w × 3  uint8)
        ▼
EdgeColorExtractor.extract()
        │
        │  raw LED colours  (n_leds × 3  uint8)
        ▼
EdgeColorExtractor.post_process()
        │  1. saturation boost (HSV)
        │  2. gamma + brightness floor (LUT lookup)
        │  3. spatial blur (gaussian_filter1d, optional)
        │
        │  post-processed LED colours  (n_leds × 3  uint8)
        ▼
EMASmoother.smooth()
        │
        │  smoothed LED colours  (n_leds × 3  uint8)
        ▼
WLEDBase.send()
        │
        └─► UDP packet → WLED controller → LED strip
```

---

## Module Responsibilities

### `ambient/base.py`
Defines two abstract base classes. Neither contains logic — they only define
the interface contract.

- `CameraBase` — `get_latest_frame() → ndarray | None`, `close()`
- `WLEDBase` — `send(colors: ndarray)`, `close()`

Any class that implements these interfaces can be dropped into `main.py` without
changing anything else.

---

### `ambient/camera.py` — `PiCamera`
Wraps Picamera2 with a background capture thread.

- The thread runs `capture_array()` in a loop and stores the result in `_frame`
  under a lock.
- `get_latest_frame()` returns `_frame` without ever blocking the main loop.
- Camera settings (resolution, gain, exposure) are read from config once at
  startup.
- Raises `RuntimeError` if `picamera2` is not installed, with a clear message
  pointing to the simulator option.

---

### `ambient/perspective.py` — `PerspectiveCorrector`
Computes the 3×3 homography matrix once from the four TV corner points and
reuses it every frame.

- `correct(frame)` calls `cv2.warpPerspective(..., flags=cv2.INTER_NEAREST)`.
  Nearest-neighbour is sufficient for colour sampling and is ~20% faster than
  the default bilinear on ARM.
- `update_points(points)` recomputes the matrix after recalibration — no
  restart needed.
- Exposes `.matrix` so `EdgeColorExtractor` can build remap maps when
  `use_remap=true`.

---

### `ambient/color.py` — `EdgeColorExtractor`

**Extraction (two modes):**

| Mode | How it works |
|---|---|
| `use_remap: false` (default) | Receives the warped frame; slices each edge strip; calls `cv2.resize(strip, (n_leds, 1), INTER_AREA)` — one C-level call per side (4 total) |
| `use_remap: true` | Pre-computes `cv2.remap` float32 maps at startup for only the 4 edge strips (~5× fewer pixels than a full warp); samples raw frame directly each loop |

**Why `cv2.resize(INTER_AREA)`?**
`INTER_AREA` is OpenCV's proper area-averaging downsampler. Resizing a
`(depth_h × width × 3)` strip to `(1 × n_leds × 3)` is exactly equivalent to
computing the mean colour of `n_leds` equal-width segments — but it's a single
C-level call with no Python loops and handles non-integer ratios cleanly.

**Post-processing pipeline** (all on the `(n_leds × 3)` array — negligible cost):

| Step | Operation | Config key |
|---|---|---|
| 1 | Saturation boost | `color.saturation_boost` |
| 2 | Gamma correction | `color.gamma` (pre-computed LUT) |
| 3 | Brightness floor | `color.brightness_floor` (folded into LUT) |
| 4 | Spatial blur | `color.spatial_blur_sigma` |

Steps 2 and 3 are combined into a single 256-entry `uint8` LUT built once at
startup. Per frame: `lut[colors]` — a single numpy index operation.

---

### `ambient/smoother.py` — `EMASmoother`
Exponential moving average applied to the full LED array in one vectorized step:

```
state = α × new + (1 − α) × state
```

- `α = 1.0` → instant response (no smoothing)
- `α = 0.3` → moderate smoothing — colours trail ~3 frames behind
- `α = 0.1` → slow, dreamy transitions — suitable for ambient/mood scenes

The state array is `float32` to avoid rounding accumulation. Output is cast
back to `uint8`.

---

### `ambient/wled.py` — `WLEDController`
Sends LED colours via WLED's UDP real-time protocol.

**DRGB protocol** (`protocol: drgb`, default):
```
Byte 0:     2          (protocol ID)
Byte 1:     timeout    (seconds, 1–255)
Bytes 2…N:  R0 G0 B0 R1 G1 B1 …  (3 bytes per LED from index 0)
```
Total packet size for 268 LEDs: `2 + 268×3 = 806 bytes`.

**WARLS protocol** (`protocol: warls`):
```
Byte 0:     1          (protocol ID)
Byte 1:     timeout
Bytes 2…N:  i0 R0 G0 B0  i1 R1 G1 B1 …  (4 bytes per LED, with LED index)
```
Total: `2 + 268×4 = 1074 bytes`.

Both fit within the 1472-byte safe UDP MTU. The packet `bytearray` is allocated
once; `send()` writes colour bytes in-place via `np.copyto` (DRGB) or a
`.tobytes()` slice loop (WARLS).

---

### `ambient/factory.py`
Single point that maps config flags to concrete classes:

```python
create_camera(config)  →  PiCamera   or  SimCamera
create_wled(config)    →  WLEDController  or  SimWLED
```

`main.py` only calls these two functions — it never imports hardware or
simulator classes directly.

---

### `ambient/sim/sim_camera.py` — `SimCamera`
Implements `CameraBase` with no real hardware.

| Source | Behaviour |
|---|---|
| `synthetic` | Generates frames algorithmically each tick (gradient, colorbar, solid, noise) |
| `image` | Loads a JPEG/PNG once; returns it on every call |
| `video` | Reads an MP4/AVI via `cv2.VideoCapture`; loops when exhausted |

A background thread paces frame generation to `simulator.camera.fps`.
Falls back to `synthetic/gradient` if the specified file is missing.

---

### `ambient/sim/sim_wled.py` — `SimWLED`
Implements `WLEDBase` with no real hardware.

| Display mode | Behaviour |
|---|---|
| `window` | Pygame window: LED ring around a TV frame preview |
| `console` | ANSI escape codes — coloured blocks in the terminal (SSH / headless Pi) |
| `none` | No-op — useful in unit tests |

The pygame window layout:

```
+──[■■■■■■■■■■■■■■  top LEDs  ■■■■■■■■■■■■■■]──+
│                                               │
[■]        corrected TV frame preview          [■]
[l]                                            [r]
[e]                                            [i]
[f]                                            [g]
[t]                                            [h]
│                                               │
+──[■■■■■■■■■■■■■■ bottom LEDs ■■■■■■■■■■■■■■]──+
```

---

### `tools/calibrate_manual.py`
Interactive corner picker:

1. Warms up camera for 1.5s (lets AE/AWB settle)
2. Captures one frame and displays it
3. User clicks four TV corners: TL → TR → BR → BL
4. Writes `perspective.points` to `config.yaml`

Keys: **Enter** to save, **Esc** to cancel, **R** to reset clicks.

---

### `tools/calibrate_auto.py`
Automatic corner detection:

1. Warms up camera for 2s
2. Captures one frame
3. Thresholds at `--threshold` (default 200) to isolate the bright TV screen
4. Finds the largest contour; approximates to a quadrilateral or falls back to
   bounding box
5. Optionally shows a preview before saving (`--preview` flag)

Works best when the TV displays a solid white image.
