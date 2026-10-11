#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

# Detect primary Wi-Fi IP on macOS or Linux
IP=""
if command -v ipconfig &>/dev/null; then
  IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
fi
if [ -z "$IP" ] && command -v hostname &>/dev/null; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [ -z "$IP" ]; then
  IP="127.0.0.1"
fi

URL="http://${IP}:5173"

echo "========================================================"
echo "  🛵 Can My Scooter Cross? - Mobile Access Launcher"
echo "========================================================"
echo ""
echo "  1. Connect your phone to the same Wi-Fi network as this laptop."
echo "  2. Scan this QR code with your phone camera, or open:"
echo ""
echo "     👉  $URL"
echo ""
echo "========================================================"

if command -v npx &>/dev/null; then
  npx -y qrcode-terminal "$URL" small 2>/dev/null || true
fi

echo ""
echo "Starting local Python API on 0.0.0.0:8787..."
python3 scripts/local_api.py --host 0.0.0.0 &
API_PID=$!

cleanup() {
  echo ""
  echo "Shutting down servers..."
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting Vite Frontend on 0.0.0.0:5173..."
cd frontend
npm run dev
