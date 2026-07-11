"""Tests for config_schema validation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config import load_config
from ambient.config_schema import (
  ConfigValidationError,
  apply_patch,
  extract_editable_config,
  get_editable_schema,
  validate_perspective_points,
  validate_patch,
)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


@pytest.fixture
def base_config():
  return load_config(CONFIG_PATH)


def test_validate_perspective_points_ok():
  pts = validate_perspective_points([[10, 10], [100, 10], [100, 80], [10, 80]], 320, 240)
  assert len(pts) == 4


def test_validate_perspective_points_wrong_count():
  with pytest.raises(ConfigValidationError):
    validate_perspective_points([[0, 0], [1, 1], [2, 2]], 320, 240)


def test_validate_perspective_points_out_of_bounds():
  with pytest.raises(ConfigValidationError):
    validate_perspective_points([[10, 10], [400, 10], [100, 80], [10, 80]], 320, 240)


def test_validate_patch_rejects_simulator():
  with pytest.raises(ConfigValidationError) as exc:
    validate_patch({"simulator": {"camera": {"enabled": True}}})
  assert "simulator" in exc.value.errors


def test_validate_patch_rejects_perspective_points():
  with pytest.raises(ConfigValidationError) as exc:
    validate_patch({"perspective": {"points": [[0, 0], [1, 1], [2, 2], [3, 3]]}})
  assert "perspective.points" in exc.value.errors


def test_validate_patch_camera_gain_range():
  with pytest.raises(ConfigValidationError):
    validate_patch({"camera": {"analogue_gain": 99.0}})


def test_apply_patch_preserves_simulator(base_config):
  patch = {"wled": {"ip": "192.168.1.99"}}
  updated = apply_patch(base_config, patch)
  assert updated["wled"]["ip"] == "192.168.1.99"
  assert "simulator" in updated
  assert updated["simulator"] == base_config["simulator"]


def test_extract_editable_excludes_simulator(base_config):
  editable = extract_editable_config(base_config)
  assert "simulator" not in editable
  assert "camera" in editable
  assert "points" in editable["perspective"]


def test_validate_patch_strip_routing():
  validated = validate_patch({
    "wled": {
      "strip_start": "bottom_right",
      "strip_direction": "ccw",
      "led_layout": {"top": 72, "right": 40, "bottom": 0, "left": 40},
    },
  })
  assert validated["wled"]["strip_start"] == "bottom_right"
  assert validated["wled"]["strip_direction"] == "ccw"
  assert validated["wled"]["led_layout"]["bottom"] == 0


def test_validate_patch_rejects_all_zero_leds():
  with pytest.raises(ConfigValidationError) as exc:
    validate_patch({"wled": {"led_layout": {"bottom": 0}}})
  assert "wled.led_layout" in exc.value.errors


def test_validate_patch_nested_edge_depth():
  validated = validate_patch({
    "color": {
      "edge_depth": {"horizontal": 0.06, "vertical": 0.04},
      "sampling_enabled": {"bottom": False},
      "sampling_disabled_color": {"bottom": "brightness_floor"},
      "show_sampling_bands": False,
    },
  })
  assert validated["color"]["edge_depth"]["horizontal"] == 0.06
  assert validated["color"]["sampling_enabled"]["bottom"] is False
  assert validated["color"]["sampling_disabled_color"]["bottom"] == "brightness_floor"
  assert validated["color"]["show_sampling_bands"] is False


def test_validate_patch_legacy_flat_edge_depth():
  validated = validate_patch({"color": {"edge_depth": 0.07}})
  assert validated["color"]["edge_depth"] == 0.07


def test_validate_patch_rejects_invalid_disabled_color():
  with pytest.raises(ConfigValidationError) as exc:
    validate_patch({"color": {"sampling_disabled_color": {"top": "red"}}})
  assert "color.sampling_disabled_color.top" in exc.value.errors


def test_validate_patch_rejects_invalid_strip_start():
  with pytest.raises(ConfigValidationError) as exc:
    validate_patch({"wled": {"strip_start": "middle"}})
  assert "wled.strip_start" in exc.value.errors


def _flatten_schema_keys(schema: dict, prefix: str = "") -> set[str]:
  keys: set[str] = set()
  for key, spec in schema.items():
    path = f"{prefix}.{key}" if prefix else key
    if spec.get("type"):
      keys.add(path)
    else:
      keys.update(_flatten_schema_keys(spec, path))
  return keys


def test_editable_schema_covers_runtime_config(base_config):
  """Every non-simulator config key (except perspective.points) has a web UI field."""
  schema = get_editable_schema()
  schema_keys = _flatten_schema_keys(schema)

  expected = set()
  for section, values in base_config.items():
    if section == "simulator":
      continue
    if section == "perspective":
      expected.add("perspective.output_resolution")
      continue

    def _walk(obj: dict, prefix: str) -> None:
      for k, v in obj.items():
        path = f"{prefix}.{k}"
        if isinstance(v, dict):
          _walk(v, path)
        else:
          expected.add(path)

    _walk(values, section)

  missing = expected - schema_keys
  assert not missing, f"config keys missing from web schema: {sorted(missing)}"

