#!/usr/bin/env bash
# Keep an ngrok tunnel running on a Linux server so Twilio can reach Jarvis.
# Needs a free ngrok account: copy your authtoken and claim your free static domain
# in the ngrok dashboard first.   Usage:  bash deploy/setup-ngrok.sh
set -euo pipefail

if ! command -v ngrok >/dev/null; then
  sudo snap install ngrok
fi
NGROK_BIN="$(command -v ngrok)"

read -rsp "ngrok authtoken (hidden): " TOKEN; echo
read -rp  "Your ngrok static domain (e.g. jarvis-abc.ngrok-free.app): " DOMAIN
DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%/}"

sudo tee /etc/systemd/system/jarvis-tunnel.service >/dev/null <<UNIT
[Unit]
Description=ngrok tunnel for Jarvis
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
Environment=NGROK_AUTHTOKEN=$TOKEN
ExecStart=$NGROK_BIN http --url=$DOMAIN 8000 --log=stdout
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo chmod 600 /etc/systemd/system/jarvis-tunnel.service
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-tunnel
echo
echo "Tunnel running. Set PUBLIC_BASE_URL=https://$DOMAIN  (python -m jarvis.configure)"
