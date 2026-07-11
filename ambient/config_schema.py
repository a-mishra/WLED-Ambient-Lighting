"""Config validation and editable-field schema for the web config UI."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

from .edge_sampling import parse_edge_sampling

EDITABLE_TOP_LEVEL = frozenset({"camera", "perspective", "color", "wled", "processing"})
FORBIDDEN_PATCH_KEYS = frozenset({"simulator"})


class ConfigValidationError(Exception):
  def __init__(self, errors: dict[str, str]) -> None:
    self.errors = errors
    super().__init__(str(errors))


class CameraBusyError(RuntimeError):
  """Raised when the camera cannot be opened (e.g. main.py holds it)."""


def get_editable_schema() -> dict:
  """Field metadata for building web forms."""
  return {
    "camera": {
      "resolution": {"type": "resolution", "label": "Resolution [W, H]"},
      "rgb_swap": {"type": "bool", "label": "Swap R/B channels (fix red↔blue)"},
      "awb_enable": {"type": "bool", "label": "Auto white balance"},
      "ae_enable": {"type": "bool", "label": "Auto exposure"},
      "analogue_gain": {"type": "float", "label": "Analogue gain", "min": 1.0, "max": 8.0, "step": 0.1},
      "exposure_time": {"type": "int", "label": "Exposure (µs)", "min": 100, "max": 1_000_000},
    },
    "perspective": {
      "output_resolution": {"type": "resolution", "label": "Output resolution [W, H]"},
    },
    "color": {
      "edge_depth": {
        "horizontal": {
          "type": "float",
          "label": "Top/bottom band depth (fraction of height)",
          "min": 0.01,
          "max": 0.5,
          "step": 0.01,
        },
        "vertical": {
          "type": "float",
          "label": "Left/right band depth (fraction of width)",
          "min": 0.01,
          "max": 0.5,
          "step": 0.01,
        },
      },
      "sampling_enabled": {
        "top": {"type": "bool", "label": "Sample top edge"},
        "right": {"type": "bool", "label": "Sample right edge"},
        "bottom": {"type": "bool", "label": "Sample bottom edge"},
        "left": {"type": "bool", "label": "Sample left edge"},
      },
      "sampling_disabled_color": {
        "top": {
          "type": "enum",
          "label": "Top fill when disabled",
          "options": ["black", "brightness_floor"],
        },
        "right": {
          "type": "enum",
          "label": "Right fill when disabled",
          "options": ["black", "brightness_floor"],
        },
        "bottom": {
          "type": "enum",
          "label": "Bottom fill when disabled",
          "options": ["black", "brightness_floor"],
        },
        "left": {
          "type": "enum",
          "label": "Left fill when disabled",
          "options": ["black", "brightness_floor"],
        },
      },
      "show_sampling_bands": {"type": "bool", "label": "Show sampling bands on preview"},
      "use_remap": {"type": "bool", "label": "Use remap (skip full warp)"},
      "saturation_boost": {"type": "float", "label": "Saturation boost", "min": 0.5, "max": 3.0, "step": 0.1},
      "brightness_floor": {"type": "int", "label": "Brightness floor", "min": 0, "max": 255},
      "gamma": {"type": "float", "label": "Gamma", "min": 0.5, "max": 3.0, "step": 0.1},
      "spatial_blur_sigma": {"type": "float", "label": "Spatial blur σ", "min": 0.0, "max": 10.0, "step": 0.1},
      "smoothing": {
        "method": {"type": "enum", "label": "Smoothing method", "options": ["ema", "none"]},
        "alpha": {"type": "float", "label": "Smoothing alpha", "min": 0.0, "max": 1.0, "step": 0.05},
      },
    },
    "wled": {
      "ip": {"type": "string", "label": "WLED IP address"},
      "port": {"type": "int", "label": "UDP port", "min": 1, "max": 65535},
      "protocol": {"type": "enum", "label": "Protocol", "options": ["drgb", "warls"]},
      "timeout": {"type": "int", "label": "Realtime timeout (s)", "min": 1, "max": 255},
      "strip_start": {
        "type": "enum",
        "label": "Strip start corner",
        "options": ["top_left", "top_right", "bottom_right", "bottom_left"],
      },
      "strip_direction": {
        "type": "enum",
        "label": "Strip direction",
        "options": ["cw", "ccw"],
      },
      "led_layout": {
        "top": {"type": "int", "label": "Top LEDs", "min": 0, "max": 500},
        "right": {"type": "int", "label": "Right LEDs", "min": 0, "max": 500},
        "bottom": {"type": "int", "label": "Bottom LEDs", "min": 0, "max": 500},
        "left": {"type": "int", "label": "Left LEDs", "min": 0, "max": 500},
      },
    },
    "processing": {
      "target_fps": {"type": "float", "label": "Target FPS", "min": 1.0, "max": 60.0, "step": 1.0},
      "log_level": {
        "type": "enum", "label": "Log level",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
      },
      "log_file": {"type": "string", "label": "Log file path"},
      "benchmark_mode": {"type": "bool", "label": "Benchmark mode"},
      "opencv_threads": {"type": "int", "label": "OpenCV threads", "min": 1, "max": 8},
      "ambient_service_unit": {
        "type": "string",
        "label": "Ambient systemd unit (empty = subprocess mode)",
      },
      "ambient_use_systemd_user": {
        "type": "bool",
        "label": "Use systemctl --user for ambient service",
      },
    },
  }


def normalize_color_for_ui(color: dict) -> dict:
  """Expand legacy flat edge_depth and fill sampling defaults for web forms."""
  cfg = parse_edge_sampling(color)
  out = copy.deepcopy(color)
  out["edge_depth"] = {"horizontal": cfg.depth_h_frac, "vertical": cfg.depth_w_frac}
  out["sampling_enabled"] = dict(cfg.enabled)
  out["sampling_disabled_color"] = dict(cfg.disabled_color)
  out["show_sampling_bands"] = cfg.show_sampling_bands
  return out


def extract_editable_config(config: dict) -> dict:
  """Return only the sections editable via the web UI."""
  return {
    "camera": copy.deepcopy(config.get("camera", {})),
    "perspective": {
      "output_resolution": copy.deepcopy(config["perspective"]["output_resolution"]),
      "points": copy.deepcopy(config["perspective"]["points"]),
    },
    "color": normalize_color_for_ui(config.get("color", {})),
    "wled": copy.deepcopy(config.get("wled", {})),
    "processing": copy.deepcopy(config.get("processing", {})),
  }


def validate_perspective_points(
  points: list,
  frame_w: int,
  frame_h: int,
) -> list[list[int]]:
  errors: dict[str, str] = {}
  if not isinstance(points, list) or len(points) != 4:
    errors["perspective.points"] = "exactly 4 points required"
    raise ConfigValidationError(errors)

  out: list[list[int]] = []
  for i, pt in enumerate(points):
    key = f"perspective.points[{i}]"
    if not isinstance(pt, (list, tuple)) or len(pt) != 2:
      errors[key] = "each point must be [x, y]"
      continue
    try:
      x, y = int(pt[0]), int(pt[1])
    except (TypeError, ValueError):
      errors[key] = "coordinates must be integers"
      continue
    if not (0 <= x < frame_w and 0 <= y < frame_h):
      errors[key] = f"must be within frame 0..{frame_w - 1}, 0..{frame_h - 1}"
      continue
    out.append([x, y])

  if errors:
    raise ConfigValidationError(errors)
  return out


def _validate_resolution(value: Any, key: str, errors: dict[str, str]) -> list[int] | None:
  if not isinstance(value, (list, tuple)) or len(value) != 2:
    errors[key] = "must be [width, height]"
    return None
  try:
    w, h = int(value[0]), int(value[1])
  except (TypeError, ValueError):
    errors[key] = "width and height must be integers"
    return None
  if w < 16 or h < 16 or w > 4096 or h > 4096:
    errors[key] = "resolution out of allowed range (16–4096)"
    return None
  return [w, h]


def _validate_float(value: Any, key: str, lo: float, hi: float, errors: dict[str, str]) -> float | None:
  try:
    v = float(value)
  except (TypeError, ValueError):
    errors[key] = "must be a number"
    return None
  if not lo <= v <= hi:
    errors[key] = f"must be between {lo} and {hi}"
    return None
  return v


def _validate_int(value: Any, key: str, lo: int, hi: int, errors: dict[str, str]) -> int | None:
  try:
    v = int(value)
  except (TypeError, ValueError):
    errors[key] = "must be an integer"
    return None
  if not lo <= v <= hi:
    errors[key] = f"must be between {lo} and {hi}"
    return None
  return v


def validate_patch(patch: dict) -> dict:
  """Validate a partial config update from PATCH /api/config."""
  if not isinstance(patch, dict):
    raise ConfigValidationError({"_": "body must be a JSON object"})

  errors: dict[str, str] = {}
  for key in patch:
    if key in FORBIDDEN_PATCH_KEYS or key not in EDITABLE_TOP_LEVEL:
      errors[key] = "section not editable via this endpoint"

  if errors:
    raise ConfigValidationError(errors)

  validated: dict = {}

  if "camera" in patch:
    cam = patch["camera"]
    if not isinstance(cam, dict):
      errors["camera"] = "must be an object"
    else:
      out: dict = {}
      if "resolution" in cam:
        res = _validate_resolution(cam["resolution"], "camera.resolution", errors)
        if res is not None:
          out["resolution"] = res
      if "rgb_swap" in cam:
        out["rgb_swap"] = bool(cam["rgb_swap"])
      for bool_key in ("awb_enable", "ae_enable"):
        if bool_key in cam:
          out[bool_key] = bool(cam[bool_key])
      if "analogue_gain" in cam:
        v = _validate_float(cam["analogue_gain"], "camera.analogue_gain", 1.0, 8.0, errors)
        if v is not None:
          out["analogue_gain"] = v
      if "exposure_time" in cam:
        v = _validate_int(cam["exposure_time"], "camera.exposure_time", 100, 1_000_000, errors)
        if v is not None:
          out["exposure_time"] = v
      if out:
        validated["camera"] = out

  if "perspective" in patch:
    persp = patch["perspective"]
    if not isinstance(persp, dict):
      errors["perspective"] = "must be an object"
    elif "points" in persp:
      errors["perspective.points"] = "use POST /api/calibration to set points"
    else:
      out = {}
      if "output_resolution" in persp:
        res = _validate_resolution(
          persp["output_resolution"], "perspective.output_resolution", errors,
        )
        if res is not None:
          out["output_resolution"] = res
      if out:
        validated["perspective"] = out

  if "color" in patch:
    col = patch["color"]
    if not isinstance(col, dict):
      errors["color"] = "must be an object"
    else:
      out = {}
      if "edge_depth" in col:
        ed = col["edge_depth"]
        if isinstance(ed, dict):
          ed_out: dict = {}
          if "horizontal" in ed:
            v = _validate_float(ed["horizontal"], "color.edge_depth.horizontal", 0.01, 0.5, errors)
            if v is not None:
              ed_out["horizontal"] = v
          if "vertical" in ed:
            v = _validate_float(ed["vertical"], "color.edge_depth.vertical", 0.01, 0.5, errors)
            if v is not None:
              ed_out["vertical"] = v
          if ed_out:
            out["edge_depth"] = ed_out
        else:
          v = _validate_float(ed, "color.edge_depth", 0.01, 0.5, errors)
          if v is not None:
            out["edge_depth"] = v
      if "sampling_enabled" in col:
        se = col["sampling_enabled"]
        if not isinstance(se, dict):
          errors["color.sampling_enabled"] = "must be an object"
        else:
          se_out: dict = {}
          for side in ("top", "right", "bottom", "left"):
            if side in se:
              se_out[side] = bool(se[side])
          if se_out:
            out["sampling_enabled"] = se_out
      if "sampling_disabled_color" in col:
        sdc = col["sampling_disabled_color"]
        if not isinstance(sdc, dict):
          errors["color.sampling_disabled_color"] = "must be an object"
        else:
          sdc_out: dict = {}
          for side in ("top", "right", "bottom", "left"):
            if side in sdc:
              mode = str(sdc[side]).lower()
              if mode not in ("black", "brightness_floor"):
                errors[f"color.sampling_disabled_color.{side}"] = (
                  "must be black or brightness_floor"
                )
              else:
                sdc_out[side] = mode
          if sdc_out:
            out["sampling_disabled_color"] = sdc_out
      if "show_sampling_bands" in col:
        out["show_sampling_bands"] = bool(col["show_sampling_bands"])
      if "use_remap" in col:
        out["use_remap"] = bool(col["use_remap"])
      if "saturation_boost" in col:
        v = _validate_float(col["saturation_boost"], "color.saturation_boost", 0.5, 3.0, errors)
        if v is not None:
          out["saturation_boost"] = v
      if "brightness_floor" in col:
        v = _validate_int(col["brightness_floor"], "color.brightness_floor", 0, 255, errors)
        if v is not None:
          out["brightness_floor"] = v
      if "gamma" in col:
        v = _validate_float(col["gamma"], "color.gamma", 0.5, 3.0, errors)
        if v is not None:
          out["gamma"] = v
      if "spatial_blur_sigma" in col:
        v = _validate_float(col["spatial_blur_sigma"], "color.spatial_blur_sigma", 0.0, 10.0, errors)
        if v is not None:
          out["spatial_blur_sigma"] = v
      if "smoothing" in col:
        sm = col["smoothing"]
        if not isinstance(sm, dict):
          errors["color.smoothing"] = "must be an object"
        else:
          sm_out: dict = {}
          if "method" in sm:
            if sm["method"] not in ("ema", "none"):
              errors["color.smoothing.method"] = "must be ema or none"
            else:
              sm_out["method"] = sm["method"]
          if "alpha" in sm:
            v = _validate_float(sm["alpha"], "color.smoothing.alpha", 0.0, 1.0, errors)
            if v is not None:
              sm_out["alpha"] = v
          if sm_out:
            out["smoothing"] = sm_out
      if out:
        validated["color"] = out

  if "wled" in patch:
    wled = patch["wled"]
    if not isinstance(wled, dict):
      errors["wled"] = "must be an object"
    else:
      out = {}
      if "ip" in wled:
        ip = str(wled["ip"]).strip()
        if not ip:
          errors["wled.ip"] = "must not be empty"
        else:
          out["ip"] = ip
      if "port" in wled:
        v = _validate_int(wled["port"], "wled.port", 1, 65535, errors)
        if v is not None:
          out["port"] = v
      if "protocol" in wled:
        if wled["protocol"] not in ("drgb", "warls"):
          errors["wled.protocol"] = "must be drgb or warls"
        else:
          out["protocol"] = wled["protocol"]
      if "timeout" in wled:
        v = _validate_int(wled["timeout"], "wled.timeout", 1, 255, errors)
        if v is not None:
          out["timeout"] = v
      if "strip_start" in wled:
        start = str(wled["strip_start"])
        if start not in ("top_left", "top_right", "bottom_right", "bottom_left"):
          errors["wled.strip_start"] = "must be top_left, top_right, bottom_right, or bottom_left"
        else:
          out["strip_start"] = start
      if "strip_direction" in wled:
        direction = str(wled["strip_direction"])
        if direction not in ("cw", "ccw"):
          errors["wled.strip_direction"] = "must be cw or ccw"
        else:
          out["strip_direction"] = direction
      if "led_layout" in wled:
        layout = wled["led_layout"]
        if not isinstance(layout, dict):
          errors["wled.led_layout"] = "must be an object"
        else:
          lo: dict = {}
          for side in ("top", "right", "bottom", "left"):
            if side in layout:
              v = _validate_int(layout[side], f"wled.led_layout.{side}", 0, 500, errors)
              if v is not None:
                lo[side] = v
          if lo:
            total = sum(lo.values())
            if total < 1:
              errors["wled.led_layout"] = "total LED count must be at least 1"
            out["led_layout"] = lo
      if out:
        validated["wled"] = out

  if "processing" in patch:
    proc = patch["processing"]
    if not isinstance(proc, dict):
      errors["processing"] = "must be an object"
    else:
      out = {}
      if "target_fps" in proc:
        v = _validate_float(proc["target_fps"], "processing.target_fps", 1.0, 60.0, errors)
        if v is not None:
          out["target_fps"] = v
      if "log_level" in proc:
        level = str(proc["log_level"]).upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
          errors["processing.log_level"] = "invalid log level"
        else:
          out["log_level"] = level
      if "log_file" in proc:
        out["log_file"] = str(proc["log_file"])
      if "benchmark_mode" in proc:
        out["benchmark_mode"] = bool(proc["benchmark_mode"])
      if "opencv_threads" in proc:
        v = _validate_int(proc["opencv_threads"], "processing.opencv_threads", 1, 8, errors)
        if v is not None:
          out["opencv_threads"] = v
      if "ambient_service_unit" in proc:
        out["ambient_service_unit"] = str(proc["ambient_service_unit"]).strip()
      if "ambient_use_systemd_user" in proc:
        out["ambient_use_systemd_user"] = bool(proc["ambient_use_systemd_user"])
      if out:
        validated["processing"] = out

  if errors:
    raise ConfigValidationError(errors)
  if not validated:
    raise ConfigValidationError({"_": "no valid fields in patch"})
  return validated


def deep_merge(base: dict, patch: dict) -> dict:
  """Deep-merge patch into a copy of base."""
  result = copy.deepcopy(base)
  for key, value in patch.items():
    if key in result and isinstance(result[key], dict) and isinstance(value, dict):
      result[key] = deep_merge(result[key], value)
    else:
      result[key] = copy.deepcopy(value)
  return result


def apply_patch(config: dict, patch: dict) -> dict:
  """Validate and deep-merge a partial update into config."""
  validated = validate_patch(patch)
  return deep_merge(config, validated)


def patch_warnings(config: dict, patch: dict) -> list[str]:
  """Non-fatal warnings after a successful patch."""
  warnings: list[str] = []
  if "camera" in patch and "resolution" in patch.get("camera", {}):
    warnings.append("Camera resolution changed — recalibrate perspective points.")
  if "camera" in patch and "rgb_swap" in patch.get("camera", {}):
    warnings.append("rgb_swap changed — restart main.py to apply.")
  if "perspective" in patch and "output_resolution" in patch.get("perspective", {}):
    warnings.append("Output resolution changed — restart main.py to apply.")
  if "wled" in patch:
    wled_patch = patch.get("wled", {})
    if "led_layout" in wled_patch:
      layout = config["wled"]["led_layout"]
      total = layout["top"] + layout["right"] + layout["bottom"] + layout["left"]
      warnings.append(f"LED layout total: {total} — must match WLED firmware.")
    if any(k in wled_patch for k in ("strip_start", "strip_direction", "led_layout")):
      warnings.append("Strip routing changed — restart main.py to apply.")
  return warnings


def _values_equal(a: Any, b: Any) -> bool:
  if type(a) is not type(b):
    return False
  if isinstance(a, dict):
    if set(a.keys()) != set(b.keys()):
      return False
    return all(_values_equal(a[k], b[k]) for k in a)
  if isinstance(a, (list, tuple)):
    if len(a) != len(b):
      return False
    return all(_values_equal(x, y) for x, y in zip(a, b))
  return a == b


def compute_config_diff(
  before: dict,
  after: dict,
  prefix: str = "",
) -> list[dict[str, Any]]:
  """Return list of {path, from, to} for leaf values that differ."""
  changes: list[dict[str, Any]] = []
  all_keys = set(before.keys()) | set(after.keys())
  for key in sorted(all_keys):
    path = f"{prefix}.{key}" if prefix else key
    old_val = before.get(key)
    new_val = after.get(key)
    if isinstance(old_val, dict) and isinstance(new_val, dict):
      changes.extend(compute_config_diff(old_val, new_val, path))
    elif not _values_equal(old_val, new_val):
      changes.append({"path": path, "from": old_val, "to": new_val})
  return changes


def save_config_atomic(config: dict, path: str | Path) -> None:
  """Write config atomically (temp file + rename)."""
  config_path = Path(path)
  tmp = config_path.with_suffix(config_path.suffix + ".tmp")
  with open(tmp, "w", encoding="utf-8") as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
  tmp.replace(config_path)
