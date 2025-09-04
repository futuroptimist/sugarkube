#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: $0 SERVICE_NAME WORK_DIR START_CMD [STOP_CMD]" >&2
  exit 1
fi

SERVICE_NAME="$1"
WORK_DIR="$2"
START_CMD="$3"
STOP_CMD="${4:-}"

SCRIPT_PATH="/opt/projects/${SERVICE_NAME}_start.sh"
cat >"$SCRIPT_PATH" <<EOS
#!/usr/bin/env bash
set -e
cd "$WORK_DIR"
$START_CMD
EOS
chmod +x "$SCRIPT_PATH"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
{
  echo "[Unit]"
  echo "Description=${SERVICE_NAME} service"
  echo "After=network-online.target docker.service"
  echo "Requires=docker.service"
  echo ""
  echo "[Service]"
  echo "Type=oneshot"
  echo "WorkingDirectory=$WORK_DIR"
  echo "ExecStart=$SCRIPT_PATH"
  if [ -n "$STOP_CMD" ]; then
    echo "ExecStop=$STOP_CMD"
  fi
  echo "RemainAfterExit=yes"
  echo "Restart=on-failure"
  echo "RestartSec=5s"
  echo ""
  echo "[Install]"
  echo "WantedBy=multi-user.target"
} >"$SERVICE_FILE"

chmod 0644 "$SERVICE_FILE"

systemctl enable "$SERVICE_NAME.service" >/dev/null 2>&1 || true
