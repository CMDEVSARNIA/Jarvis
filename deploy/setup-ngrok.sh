#!/usr/bin/env bash
# Keep an ngrok tunnel running on a Linux server so Twilio can reach Jarvis.
# Needs a free ngrok account: copy your authtoken and claim your free static domain
# in the ngrok dashboard first.   Usage:  bash deploy/setup-ngrok.sh
set -euo pipefail

if ! command -v ngrok >/dev/null; then
  sudo snap install ngrok
fi
NGROK_BIN="$(command -v ngrok)"

read -rsp "ngrok authtoken (hidden while you paste): " TOKEN; echo
read -rp  "Your ngrok static domain (copy it exactly from the ngrok dashboard): " DOMAIN
DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN%/}"

# Save the token the standard way too (belt and braces).
"$NGROK_BIN" config add-authtoken "$TOKEN" >/dev/null

# Newer ngrok versions use --url, older ones --domain.
if "$NGROK_BIN" http --help 2>&1 | grep -q -- "--url"; then FLAG="--url"; else FLAG="--domain"; fi

sudo tee /etc/systemd/system/jarvis-tunnel.service >/dev/null <<UNIT
[Unit]
Description=ngrok tunnel for Jarvis
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
Environment=NGROK_AUTHTOKEN=$TOKEN
ExecStart=$NGROK_BIN http $FLAG=$DOMAIN 8000 --log=stdout
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo chmod 600 /etc/systemd/system/jarvis-tunnel.service
sudo systemctl daemon-reload
sudo systemctl enable jarvis-tunnel
sudo systemctl restart jarvis-tunnel

echo "Checking the tunnel..."
sleep 6
if curl -fsS --max-time 10 "https://$DOMAIN/" | grep -q "J.A.R.V.I.S."; then
  echo "OK: https://$DOMAIN reaches Jarvis."
else
  echo "Could not reach Jarvis through https://$DOMAIN yet."
  echo "Check:  systemctl status jarvis   and   journalctl -u jarvis-tunnel -n 30"
fi
echo
echo "Next: run  .venv/bin/python -m jarvis.configure  and enter the ngrok domain  $DOMAIN"
