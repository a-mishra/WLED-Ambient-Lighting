#!/usr/bin/env bash
# Install user-level systemd units for web config (autostart) and ambient pipeline.
#
# Usage (on the Pi, from the project root):
#   bash scripts/install-systemd.sh
#
# Web UI autostarts on boot. Ambient pipeline is started/stopped from the web UI
# (or manually: systemctl --user start wled-ambient.service).

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SRC_DIR="$PROJECT_DIR/deploy/systemd"

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "error: venv not found at $PROJECT_DIR/.venv — create it first." >&2
  exit 1
fi

mkdir -p "$USER_UNIT_DIR"

for unit in wled-web-config.service wled-ambient.service; do
  sed "s|@PROJECT_DIR@|$PROJECT_DIR|g" "$SRC_DIR/$unit" > "$USER_UNIT_DIR/$unit"
  echo "Installed $USER_UNIT_DIR/$unit"
done

# User services can run at boot without an active login session.
if command -v loginctl >/dev/null 2>&1; then
  loginctl enable-linger "$(whoami)" 2>/dev/null || true
fi

systemctl --user daemon-reload
systemctl --user enable wled-web-config.service
systemctl --user restart wled-web-config.service

echo ""
echo "Web config UI: enabled on boot (http://$(hostname -I | awk '{print $1}'):8080)"
echo "Ambient pipeline: NOT autostarted — use Start in the web UI or:"
echo "  systemctl --user start wled-ambient.service"
echo ""
echo "Status:"
systemctl --user status wled-web-config.service --no-pager || true
