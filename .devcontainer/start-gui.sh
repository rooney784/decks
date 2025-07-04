#!/bin/bash
set -e

cleanup() {
  echo "Shutting down gracefully..."
  pkill -f "Xvfb|fluxbox|x11vnc|websockify|chrome" || true
  find /tmp -maxdepth 1 -name 'chrome-profile-*' -exec rm -rf {} + 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

echo "🧹 Cleaning Chrome profiles..."
find /tmp -maxdepth 1 -name 'chrome-profile-*' -exec rm -rf {} + 2>/dev/null || true

echo "🖥️  Starting Xvfb with enhanced configuration..."
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR +extension GLX +render -noreset -dpi 96 \
  >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
sleep 3
export DISPLAY=:99

if ! xdpyinfo -display :99 >/dev/null 2>&1; then
  echo "❌ Xvfb failed"; cat /tmp/xvfb.log; exit 1
fi
echo "✅ Xvfb started"

export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

if command -v dbus-launch >/dev/null 2>&1; then
  eval "$(dbus-launch --sh-syntax)"
  echo "✅ D-Bus session started"
fi

echo "🪟 Starting fluxbox"
fluxbox >/tmp/fluxbox.log 2>&1 &
sleep 2

echo "🔗 Starting x11vnc server"
x11vnc -display :99 -forever -shared -passwd secret -bg -o /tmp/x11vnc.log \
  -xkb -noxrecord -noxfixes -noxdamage -wait 10 -defer 10 -speeds modem
sleep 2
if ! pgrep -f "x11vnc" >/dev/null; then echo "❌ x11vnc failed"; cat /tmp/x11vnc.log; exit 1; fi
echo "✅ x11vnc started"

echo "🌐 Starting websockify for noVNC"
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
sleep 3
if ! pgrep -f "websockify" >/dev/null; then echo "❌ websockify failed"; cat /tmp/websockify.log; exit 1; fi
echo "✅ websockify ready"

# Setup Automa extension
if [ -d "/opt/automa/dist" ]; then AUTOMA_DIR="/opt/automa/dist";
elif [ -d "/opt/automa/build" ]; then AUTOMA_DIR="/opt/automa/build";
else echo "❌ Automa not found"; exit 1; fi
chmod -R a+r "$AUTOMA_DIR"
echo "✅ Automa extension at: $AUTOMA_DIR"

# Download and extract Link Klipper
LINK_KLIPPER_DIR="/tmp/link-klipper-extension/extracted"
if [ ! -d "$LINK_KLIPPER_DIR" ]; then
    mkdir -p "$(dirname "$LINK_KLIPPER_DIR")"
    echo "📥 Downloading Link Klipper..."
    DOWNLOAD_URL="https://clients2.google.com/service/update2/crx?response=redirect&prodversion=91.0&acceptformat=crx2,crx3&x=id%3Dfahollcgofmpnehocdgofnhkkchiekoo%26uc"
    curl -L -o link-klipper.crx "$DOWNLOAD_URL" 2>/dev/null || wget -q -O link-klipper.crx "$DOWNLOAD_URL"
    mkdir -p extracted
    unzip -q link‑klipper.crx -d extracted/ 2>/dev/null || {
       for skip in 306 322 334; do
         dd if=link‑klipper.crx bs=1 skip=$skip of=temp.zip && unzip -q temp.zip -d extracted/ && break
       done
    }
    mv extracted "$LINK_KLIPPER_DIR"
    if [ ! -f "$LINK_KLIPPER_DIR/manifest.json" ]; then
       echo "⚠️ Link Klipper extraction failed"; LINK_KLIPPER_DIR=""
    else
       echo "✅ Link Klipper ready at $LINK_KLIPPER_DIR"
    fi
fi

CHROME_PROFILE_DIR="/tmp/chrome-profile-shared"
mkdir -p "$CHROME_PROFILE_DIR"
echo "📁 Profile: $CHROME_PROFILE_DIR"

# Test extension
TEST_OUT=$(google-chrome-stable \
  --headless=new --disable-gpu \
  --disable-extensions-except="$AUTOMA_DIR" \
  --load-extension="$AUTOMA_DIR" \
  --print-to-pdf=/dev/null 2>&1 || true)
if echo "$TEST_OUT" | grep -q "Extension"; then echo "✅ Extension test ok"; else echo "⚠️ Extension test uncertain"; fi

# Prepare extension args
if [ -n "$LINK_KLIPPER_DIR" ]; then
  EXT_ARGS="--disable-extensions-except=\"$AUTOMA_DIR,$LINK_KLIPPER_DIR\" \
  --load-extension=\"$AUTOMA_DIR,$LINK_KLIPPER_DIR\""
else
  EXT_ARGS="--disable-extensions-except=\"$AUTOMA_DIR\" --load-extension=\"$AUTOMA_DIR\""
fi

echo "🧹 Killing existing Chrome"
pkill -f chrome || true
sleep 2

echo "🚀 Starting Chrome with flags"
google-chrome-stable \
  $EXT_ARGS \
  --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --user-data-dir="$CHROME_PROFILE_DIR" \
  --remote-debugging-port=9222 \
  --remote-debugging-address=0.0.0.0 \
  --remote-allow-origins=* \
  --window-size=1920,1080 --start-maximized \
  chrome-extension://infppggnoaenmfagbfknfkancpbljcca/newtab.html \
  >/tmp/chrome.log 2>&1 &
CHROME_PID=$!
echo "🌐 Chrome PID: $CHROME_PID"

sleep 8

# Check DevTools availability
COUNTER=0; TIMEOUT=30
while ! curl -sf http://localhost:9222/json/version; do
  echo "⌛ Waiting DevTools... ($COUNTER)"
  sleep 2; COUNTER=$((COUNTER+2))
  [ $COUNTER -ge $TIMEOUT ] && { echo "❌ DevTools not ready"; tail -n20 /tmp/chrome.log; exit 1; }
done
echo "✅ DevTools ready"

# Start socat to expose DevTools
socat TCP-LISTEN:9222,fork TCP:127.0.0.1:9222 &
SVC_PID=$!

echo "✅ ENV READY: GUI at http://localhost:6080 | DevTools at http://localhost:9222"
echo "Press Ctrl+C to terminate."
wait
