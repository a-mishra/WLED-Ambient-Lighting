# WLED TV Ambient Lighting — Overview & Design

## What This Does

This program turns a Raspberry Pi Zero 2W + camera + WLED LED strip into a TV
ambient backlight. It continuously:

1. Captures a frame from the camera pointing at the TV
2. Corrects the perspective so the TV fills the frame perfectly
3. Samples the average colour along configurable bands on each enabled edge
4. Post-processes colours (saturation, gamma, smoothing)
5. Permutes logical edge order to physical strip wiring
6. Sends the colours to a WLED controller over UDP

The result is a bias lighting effect where the LEDs behind the TV glow with the
colours currently shown on screen.

---

## Hardware Setup

```
┌──────────────────────────────────────────────────────────┐
│                      TV                                  │
│  ┌────────────────────────────────────────────────────┐  │
│  │                  Screen Content                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [LED strip runs around the back of the TV frame]        │
│  Top: 84 LEDs  Right: 50  Bottom: 84  Left: 50          │
└──────────────────────────────────────────────────────────┘

         ↑ camera pointed at TV from a distance
    Raspberry Pi Zero 2W (runs this program)
         ↓ UDP over WiFi
    WLED controller (ESP8266/ESP32 driving the LED strip)
```

### Required hardware

| Component | Notes |
|---|---|
| Raspberry Pi Zero 2W | Quad-core Cortex-A53 @ 1GHz, 512MB RAM |
| Camera module | CSI ribbon cable; any Picamera2-compatible module |
| LED strip | WS2812B or SK6812 addressable RGB — 268 LEDs total for a typical TV |
| WLED controller | ESP8266 or ESP32 running WLED firmware |
| Power supply | Separate 5V supply for the LED strip |

---

## Design Goals

| Goal | How it's achieved |
|---|---|
| **24fps throughput** | `cv2.INTER_NEAREST` warp, `cv2.resize(INTER_AREA)` extraction, pre-computed matrix and LUT, threaded camera |
| **Configurable** | Single `config/config.yaml` controls every parameter |
| **Testable without hardware** | Config-driven simulator: SimCamera + SimWLED replace real hardware |
| **Modular** | Each concern is a separate class; `factory.py` wires them together |
| **Observable** | Benchmark mode logs per-stage timings; SimWLED shows a live LED ring |

---

## Performance Design (Pi Zero 2W)

The Pi Zero 2W has a Cortex-A53 @ 1GHz — roughly 4–5x slower than a Pi 4
for OpenCV operations. Every design decision targets this constraint.

### Key bottlenecks eliminated

| Old code | New code | Speedup |
|---|---|---|
| `cv2.kmeans` × 268 per frame | `cv2.resize(INTER_AREA)` — 4 C calls | ~50x |
| Perspective matrix recomputed each frame | Pre-computed once in `__init__` | free |
| Config re-read each frame | Loaded once at startup | free |
| `time.sleep(0.1)` = hard 10fps cap | Adaptive sleep with frame-drop guard | 24fps+ |
| UDP buffer allocated per frame | Pre-allocated `bytearray`, in-place write | ~1ms saved |
| `cv2.INTER_LINEAR` (bilinear warp) | `cv2.INTER_NEAREST` | ~20% faster warp |
| OpenCV multi-thread overhead | `cv2.setNumThreads(1)` | measurable on small frames |

### Realistic timing at 160×90 output (default)

| Stage | Time on Pi Zero 2W |
|---|---|
| Camera capture (threaded) | 0ms blocking |
| `warpPerspective` (160×90, INTER_NEAREST) | ~4ms |
| `cv2.resize` extraction (4 calls) | ~3ms |
| Post-processing (268 LEDs) | ~1ms |
| EMA smoothing | ~0.5ms |
| UDP send | ~1ms |
| **Total** | **~10ms → ~100fps headroom** |

24fps budget is 41ms — we use ~10ms, leaving 31ms of headroom.

---

## Architecture Decision: Why Not asyncio?

The original `main_async.py` used `asyncio.gather` to run the camera and WLED
loops concurrently. However:

- Camera capture via Picamera2 is a blocking C call that releases the GIL —
  plain threading already achieves true parallelism here.
- `asyncio` only helps when code is genuinely async (network I/O, awaitable
  coroutines). CPU-bound numpy operations hold the GIL anyway.
- A simple sync main loop with a threaded camera is cleaner, easier to debug,
  and easier to benchmark.
