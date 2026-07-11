#!/usr/bin/env bash
# TaskWA unattended autostart for macOS.
# Installs a LaunchAgent that runs at every login: opens Docker Desktop,
# waits for the engine, then `docker compose up -d` in this repo folder.
# This also repairs the "containers were stopped when Docker last quit"
# case that `restart: unless-stopped` does not cover.
#
#   ./scripts/autostart-macos.sh              install (or refresh)
#   ./scripts/autostart-macos.sh --uninstall  remove
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.taskwa.autostart.plist"
DOCKER_BIN="$(command -v docker || echo /usr/local/bin/docker)"

if [ "${1:-}" = "--uninstall" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "TaskWA autostart removed."
    exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.taskwa.autostart</string>
  <key>RunAtLoad</key><true/>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>open -ga Docker; i=0; while [ \$i -lt 60 ]; do if "$DOCKER_BIN" info >/dev/null 2>&amp;1; then break; fi; sleep 5; i=\$((i+1)); done; cd "$REPO_DIR"; "$DOCKER_BIN" compose up -d</string>
  </array>
  <key>StandardOutPath</key><string>/tmp/taskwa-autostart.log</string>
  <key>StandardErrorPath</key><string>/tmp/taskwa-autostart.log</string>
</dict></plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "TaskWA autostart installed for: $REPO_DIR"
echo "Log: /tmp/taskwa-autostart.log"
echo
echo "Also recommended (one-time):"
echo "  sudo pmset -a autorestart 1     # power back on after a power failure"
echo "  System Settings > Users & Groups > Log in automatically"
echo "  (note: with FileVault on, a password is still required at cold boot)"
