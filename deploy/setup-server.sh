#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu cloud VM (Oracle Cloud / Google Cloud free tier).
# Run from inside the cloned repo:  bash deploy/setup-server.sh
set -euo pipefail
cd "$(dirname "$0")/.."

sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env"
fi

# Install as a service so Jarvis starts on boot and restarts if it crashes.
sed -e "s|__USER__|$USER|g" -e "s|__DIR__|$PWD|g" deploy/jarvis.service \
  | sudo tee /etc/systemd/system/jarvis.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable jarvis
echo
echo "Next: enter your keys with  .venv/bin/python -m jarvis.configure"
echo "Then start Jarvis with:      sudo systemctl restart jarvis"
echo "Watch the logs with:           journalctl -u jarvis -f"
