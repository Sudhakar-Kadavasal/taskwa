#!/usr/bin/env bash
# TaskWA unattended autostart for Linux (systemd). Run with sudo.
# Installs a system service that brings the compose stack up at boot,
# after the Docker daemon — no login required (ideal for servers/Pis).
#
#   sudo ./scripts/autostart-linux.sh              install
#   sudo ./scripts/autostart-linux.sh --uninstall  remove
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT="/etc/systemd/system/taskwa.service"
DOCKER_BIN="$(command -v docker || echo /usr/bin/docker)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0 $*"
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now taskwa.service 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    echo "TaskWA autostart removed."
    exit 0
fi

cat > "$UNIT" <<EOF
[Unit]
Description=TaskWA (WhatsApp task manager) compose stack
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$REPO_DIR
ExecStart=$DOCKER_BIN compose up -d
ExecStop=$DOCKER_BIN compose stop
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now docker.service
systemctl enable --now taskwa.service
echo "TaskWA autostart installed for: $REPO_DIR"
echo "Check with: systemctl status taskwa.service"
