# Configuration Reference

All settings live in `config/config.yaml`. Every key is documented below.
To use a different config file: `python main.py --config path/to/config.yaml`.

---

## `camera` — Camera capture settings

```yaml
camera:
  resolution: [320, 240]
  rgb_swap: false
  awb_enable: true
  ae_enable: true
  analogue_gain: 3.0
  exposure_time: 10000
```

| Key | Type | Default | Description |
|---|---|---|---|
| `resolution` | `[W, H]` | `[320, 240]` | Capture resolution in pixels. This is the raw frame size from the camera. Used for calibration preview and as source for perspective correction. Larger = more detail but slower warp. |
| `rgb_swap` | bool | `false` | When `true`, swaps red and blue channels after capture (`BGR→RGB`). Enable if red and blue are reversed in preview or on the LEDs — a common mismatch between Picamera2 buffers and the pipeline's RGB assumption. |
| `awb_enable` | bool | `true` | Auto white balance. Set `false` to lock white balance for consistent colour in fixed lighting. |
| `ae_enable` | bool | `true` | Auto exposure. Set `false` to use a fixed `exposure_time`. |
| `analogue_gain` | float | `3.0` | Camera sensor gain. Range `1.0–8.0`. Increase for brighter image in dark rooms; too high introduces noise. |
| `exposure_time` | int | `10000` | Sensor exposure in microseconds. Only used when `ae_enable: false`. Longer = brighter but may cause motion blur on a fast-changing TV image. |

---

## `perspective` — TV corner calibration

```yaml
perspective:
  output_resolution: [160, 90]
  points:
    - [106, 35]
    - [238, 49]
    - [234, 121]
    - [98, 107]
```

| Key | Type | Default | Description |
|---|---|---|---|
| `output_resolution` | `[W, H]` | `[160, 90]` | Size of the warped output frame used for colour extraction. **This is the most important performance knob.** Halving this cuts warp time by ~4×. Use `[160, 90]` on Pi Zero 2W; `[320, 180]` on Pi 4 or if colour accuracy is insufficient. Must match a 16:9 ratio for TVs. |
| `points` | list of 4 `[x, y]` | — | Pixel coordinates of the TV corners in the raw camera frame, in order: **top-left → top-right → bottom-right → bottom-left**. Run `python -m tools.calibrate_manual` or `tools.calibrate_auto` to set these. |

---

## `color` — Colour extraction and post-processing

```yaml
color:
  edge_depth:
    horizontal: 0.05
    vertical: 0.05
  sampling_enabled:
    top: true
    right: true
    bottom: true
    left: true
  sampling_disabled_color:
    top: black
    right: black
    bottom: black
    left: black
  show_sampling_bands: true
  use_remap: false
  saturation_boost: 1.3
  brightness_floor: 10
  gamma: 2.2
  spatial_blur_sigma: 1.0
  smoothing:
    method: ema
    alpha: 0.3
```

### Extraction

| Key | Type | Default | Description |
|---|---|---|---|
| `edge_depth` | float or object | `0.05` | Sampling band depth. Legacy flat float applies to both axes. Prefer `horizontal` (top/bottom, fraction of output height) and `vertical` (left/right, fraction of output width). |
| `edge_depth.horizontal` | float | `0.05` | Top and bottom band depth as a fraction of warped frame height. |
| `edge_depth.vertical` | float | `0.05` | Left and right band depth as a fraction of warped frame width. |
| `sampling_enabled` | object | all `true` | Per-side toggles. When `false` but `led_layout` for that side is > 0, LEDs are filled with `sampling_disabled_color` instead of camera pixels. |
| `sampling_disabled_color` | object | all `black` | Fill mode per side when sampling is disabled: `black` or `brightness_floor`. |
| `show_sampling_bands` | bool | `true` | Draw sampling bands on web preview panel 2 (cyan = active, red = disabled fill). |
| `use_remap` | bool | `false` | When `true`, bypasses `warpPerspective` entirely. Pre-computed `cv2.remap` maps are built at startup; only the 4 edge strips are sampled from the raw frame (~5× fewer pixels computed). Enable this if benchmark shows `warp` is your bottleneck after trying a smaller `output_resolution`. |

### Post-processing

All post-processing operates on the LED colour array (~268 values) — negligible compute cost regardless of settings.

| Key | Type | Default | Description |
|---|---|---|---|
| `saturation_boost` | float | `1.3` | Multiplier applied to the HSV S (saturation) channel. `1.0` = no change. `1.3` = 30% more vivid. Camera images of TVs often look washed out — boost helps LEDs pop. Values above `2.0` may look unnatural. |
| `brightness_floor` | int | `10` | Per-channel minimum value (0–255). Prevents LEDs from going fully dark during black scenes, giving a subtle ambient glow. Set to `0` to disable. |
| `gamma` | float | `2.2` | Gamma correction for LED perceptual linearity. The raw pixel values from the camera are in sRGB space; LEDs respond linearly to voltage. `2.2` is the standard sRGB gamma and gives perceptually accurate colour rendering. Combined with `brightness_floor` into a single LUT at startup — no per-frame cost. Lower values (e.g. `1.8`) produce brighter midtones; `1.0` disables gamma correction. |
| `spatial_blur_sigma` | float | `1.0` | Gaussian blur along the LED strip (σ in LED units). Smooths hard colour boundaries between adjacent LEDs. `0.0` disables. `1.0` blends each LED with its immediate neighbours. `3.0` gives a softer, more diffuse glow. Has no effect on temporal smoothing (see below). |

### Temporal smoothing

| Key | Type | Default | Description |
|---|---|---|---|
| `smoothing.method` | string | `ema` | `ema` = exponential moving average. `none` = pass through unchanged. |
| `smoothing.alpha` | float | `0.3` | EMA factor. Controls how quickly colours respond to changes. `1.0` = instant (no smoothing). `0.3` = moderate lag (~3 frames). `0.1` = slow, dreamy transitions. Lower values make the system more stable but slower to react to scene cuts. |

---

## `wled` — WLED controller connection

```yaml
wled:
  ip: "192.168.1.77"
  port: 21324
  protocol: drgb
  timeout: 255
  strip_start: top_left        # top_left | top_right | bottom_right | bottom_left
  strip_direction: cw         # cw | ccw (viewed from front of TV)
  led_layout:
    top: 84
    right: 50
    bottom: 84
    left: 50
```

| Key | Type | Default | Description |
|---|---|---|---|
| `ip` | string | `"192.168.1.77"` | IP address of the WLED device on your local network. Find it in the WLED web UI or your router's DHCP table. |
| `port` | int | `21324` | UDP port. WLED's default real-time port. Do not change unless you've changed it in WLED settings. |
| `protocol` | string | `drgb` | UDP protocol variant. `drgb` = 3 bytes/LED from index 0 (simpler, default). `warls` = 4 bytes/LED with an explicit index (allows sparse updates, slightly more overhead). Use `drgb` unless you have a specific reason for `warls`. |
| `timeout` | int | `255` | WLED real-time timeout in seconds. WLED will revert to its normal effect after this many seconds of not receiving packets. `255` = maximum (never revert during normal operation). |
| `strip_start` | string | `top_left` | Corner where physical LED 0 sits: `top_left`, `top_right`, `bottom_right`, or `bottom_left`. |
| `strip_direction` | string | `cw` | Direction the strip runs around the TV when viewed from the front: `cw` (clockwise) or `ccw` (counter-clockwise). |

### `wled.led_layout` — LEDs per TV edge

| Key | Type | Description |
|---|---|---|
| `top` | int | Number of LEDs along the top edge. |
| `right` | int | Number of LEDs along the right edge. |
| `bottom` | int | Number of LEDs along the bottom edge (may be `0` if no strip on that side). |
| `left` | int | Number of LEDs along the left edge. |

Colors are sampled in **logical** order: top (L→R) → right (T→B) → bottom (R→L) → left (B→T).
Before sending to WLED, they are permuted into **physical wire order** using `strip_start` and
`strip_direction`.

The default (`strip_start: top_left`, `strip_direction: cw`) matches a strip that starts at the
top-left corner and runs clockwise — the original hardcoded behavior.

The total LED count (`top + right + bottom + left`) must match the WLED controller's configured
LED count.

> **Common TV sizes:**  
> 55" TV with 5mm LED density: top≈84, right≈50, bottom≈84, left≈50 (268 total)  
> 65" TV: top≈100, right≈56, bottom≈100, left≈56 (312 total)

---

## `processing` — Runtime behaviour

```yaml
processing:
  target_fps: 24
  log_level: INFO
  log_file: app.log
  benchmark_mode: false
  opencv_threads: 1
  ambient_service_unit: wled-ambient.service
  ambient_use_systemd_user: true
```

| Key | Type | Default | Description |
|---|---|---|---|
| `target_fps` | float | `24` | Target frames per second. The main loop sleeps adaptively to hit this rate. If a frame takes longer than `1/target_fps`, sleep is skipped (frame drop guard). On Pi Zero 2W the pipeline comfortably achieves 24fps with the default settings. |
| `log_level` | string | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. Use `DEBUG` to see every config value loaded. |
| `log_file` | string | `app.log` | Log file path. Relative to the project root. Logs go to both file and stdout. Set to `""` or remove to disable file logging. |
| `benchmark_mode` | bool | `false` | When `true`, logs the wall-clock time of every pipeline stage for every frame: `[BENCH] cap=0.0ms warp=3.8ms ext=2.9ms post=0.3ms smo=0.4ms send=0.9ms total=8.3ms`. Use this to find your bottleneck and decide whether to enable `use_remap`, reduce `output_resolution`, or change `opencv_threads`. |
| `opencv_threads` | int | `1` | Passed to `cv2.setNumThreads()` at startup. On Pi Zero 2W, `1` is usually faster for small frame sizes because thread synchronisation overhead outweighs any parallelism benefit. On Pi 4 with large frames, try `4`. |
| `ambient_service_unit` | string | `wled-ambient.service` | Systemd unit name for the web UI **Start ambient** / **Stop ambient** buttons. Set to `""` to run `main.py` as a subprocess instead of `systemctl --user`. |
| `ambient_use_systemd_user` | bool | `true` | When `true`, use `systemctl --user` for ambient control. Install units with `bash scripts/install-systemd.sh`. |

---

## `simulator` — Hardware simulation

When the corresponding `enabled` flag is `true`, the factory returns the
simulator class instead of the real hardware class. The rest of the pipeline
runs identically.

```yaml
simulator:
  camera:
    enabled: false
    source: synthetic
    video_path: tests/assets/sample.mp4
    image_path: tests/assets/sample.jpg
    synthetic:
      pattern: gradient
      color: [255, 0, 0]
    loop: true
    fps: 24

  wled:
    enabled: false
    display: window
    window_title: "WLED Simulator"
    window_scale: 4
    show_frame_preview: true
```

### `simulator.camera`

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Set `true` to use SimCamera instead of PiCamera. Also activated by `--sim` or `--sim-camera` CLI flags. |
| `source` | string | `synthetic` | Frame source: `synthetic` (generated in code), `video` (MP4/AVI file), `image` (JPEG/PNG file). Falls back to `synthetic/gradient` if the specified file is missing. |
| `video_path` | string | — | Path to the video file used when `source: video`. Relative to project root. |
| `image_path` | string | — | Path to the image file used when `source: image`. |
| `synthetic.pattern` | string | `gradient` | Synthetic frame pattern: `gradient` (rotating hue sweep — good for visualising extraction), `colorbar` (SMPTE colour bars — good for accuracy testing), `solid` (flat colour), `noise` (random RGB). |
| `synthetic.color` | `[R, G, B]` | `[255,0,0]` | Colour used when `pattern: solid`. Values 0–255. |
| `loop` | bool | `true` | Whether to loop the video when it reaches the end. Has no effect for `synthetic` and `image` sources. |
| `fps` | float | `24` | Playback speed for `video` and `synthetic` sources. The background thread sleeps between frames to match this rate. |

### `simulator.wled`

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Set `true` to use SimWLED instead of WLEDController. Also activated by `--sim` or `--sim-wled` CLI flags. |
| `display` | string | `window` | Output mode: `window` (pygame LED ring — requires pygame), `console` (ANSI terminal — works over SSH), `none` (no-op — useful in tests). |
| `window_title` | string | `"WLED Simulator"` | Title bar text for the pygame window. |
| `window_scale` | int | `4` | Pixel size of each LED square in the display. `4` means each LED is a 4×4 pixel square. Larger = easier to see individual LEDs. The window is sized automatically: `n_top × scale` wide, `n_left × scale` tall, plus a border for the LED ring. |
| `show_frame_preview` | bool | `true` | Show the corrected TV frame (after perspective correction) in the centre of the LED ring window. Disable to show a black placeholder instead. |
