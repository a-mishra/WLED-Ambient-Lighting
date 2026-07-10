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
