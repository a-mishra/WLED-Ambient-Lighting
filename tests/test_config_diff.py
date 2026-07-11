"""Tests for compute_config_diff."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ambient.config_schema import compute_config_diff


def test_compute_config_diff_no_changes():
  before = {"camera": {"rgb_swap": True, "resolution": [320, 240]}}
  assert compute_config_diff(before, before) == []


def test_compute_config_diff_flat_change():
  before = {"wled": {"ip": "192.168.1.1"}}
  after = {"wled": {"ip": "192.168.1.2"}}
  changes = compute_config_diff(before, after)
  assert len(changes) == 1
  assert changes[0]["path"] == "wled.ip"
  assert changes[0]["from"] == "192.168.1.1"
  assert changes[0]["to"] == "192.168.1.2"


def test_compute_config_diff_nested():
  before = {"color": {"edge_depth": {"horizontal": 0.05, "vertical": 0.05}}}
  after = {"color": {"edge_depth": {"horizontal": 0.06, "vertical": 0.05}}}
  changes = compute_config_diff(before, after)
  assert len(changes) == 1
  assert changes[0]["path"] == "color.edge_depth.horizontal"
