#!/bin/bash
set -e

cleanup() {
  echo "Shutting down gracefully..."
  pkill -f "Xvfb|fluxbox|x11vnc|websockify|chrome" || true
  find /tmp -maxdepth 1 -name 'chrome-profile-*' -exec rm -rf {} + 2>/dev/null
  exit 0
}
trap cleanup SIGINT SIGTERM

echo "Cleaning Chrome profiles..."
find /tmp -maxdepth 1 -name 'chrome-profile-*' -exec rm -rf {} + 2>/dev/null

echo "Starting Xvfb..."
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR +extension GLX +render -noreset \
  >/tmp/xvfb.log 2>&1 &
sleep 3
export DISPLAY=:99
xdpyinfo -display :99 >/dev/null || { echo "Xvfb failed"; cat /tmp/xvfb.log; exit 1; }

export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
eval "$(dbus-launch --sh-syntax)"

fluxbox >/tmp/fluxbox.log 2>&1 &
sleep 2

x11vnc -display :99 -forever -shared -passwd secret -bg -o /tmp/x11vnc.log
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
sleep 3

# Automa directory
if [ -d "/opt/automa/dist" ]; then
  AUTOMA_DIR="/opt/automa/dist"
elif [ -d "/opt/automa/build" ]; then
  AUTOMA_DIR="/opt/automa/build"
else
  echo "ERROR: Automa build not found"; ls -la /opt/automa/; exit 1
fi

chmod -R a+r "$AUTOMA_DIR"

# Download Link Klipper extension if not exists
LINK_KLIPPER_DIR="/tmp/link-klipper-extension/extracted"
if [ ! -d "$LINK_KLIPPER_DIR" ]; then
    echo "Downloading Link Klipper extension..."
    EXTENSION_ID="fahollcgofmpnehocdgofnhkkchiekoo"
    TEMP_DIR="/tmp/link-klipper-extension"
    mkdir -p "$TEMP_DIR"
    cd "$TEMP_DIR"
    
    # Download and extract
    echo "Fetching extension from Chrome Web Store..."
    curl -L -o "link-klipper.crx" "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=91.0&acceptformat=crx2,crx3&x=id%3D${EXTENSION_ID}%26uc" 2>/dev/null || {
        echo "⚠️ Direct download failed, trying alternative method..."
        # Alternative download method
        wget -q -O "link-klipper.crx" "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=91.0&acceptformat=crx2,crx3&x=id%3D${EXTENSION_ID}%26uc" || {
            echo "❌ Failed to download Link Klipper extension"
            LINK_KLIPPER_DIR=""
        }
    }
    
    if [ -f "link-klipper.crx" ] && [ -s "link-klipper.crx" ]; then
        echo "Extracting Link Klipper extension..."
        mkdir -p "extracted"
        
        # Try standard unzip first
        if unzip -q "link-klipper.crx" -d "extracted/" 2>/dev/null; then
            echo "✅ Link Klipper extension extracted successfully"
        else
            # CRX files have a header, try skipping it
            echo "Trying alternative extraction method..."
            if dd if="link-klipper.crx" bs=1 skip=306 of="temp.zip" 2>/dev/null && unzip -q "temp.zip" -d "extracted/" 2>/dev/null; then
                echo "✅ Link Klipper extension extracted successfully"
                rm -f "temp.zip"
            else
                # Try different skip values for different CRX versions
                for skip in 322 334; do
                    if dd if="link-klipper.crx" bs=1 skip=$skip of="temp.zip" 2>/dev/null && unzip -q "temp.zip" -d "extracted/" 2>/dev/null; then
                        echo "✅ Link Klipper extension extracted successfully (skip=$skip)"
                        rm -f "temp.zip"
                        break
                    fi
                done
                
                # If all methods fail
                if [ ! -f "extracted/manifest.json" ]; then
                    echo "❌ Failed to extract Link Klipper extension"
                    LINK_KLIPPER_DIR=""
                fi
            fi
        fi
        
        # Verify extraction
        if [ -f "extracted/manifest.json" ]; then
            echo "✅ Link Klipper extension ready at: $LINK_KLIPPER_DIR"
        else
            echo "❌ Link Klipper extension extraction failed"
            LINK_KLIPPER_DIR=""
        fi
    else
        echo "❌ Link Klipper extension download failed"
        LINK_KLIPPER_DIR=""
    fi
fi

CHROME_PROFILE_DIR="/tmp/chrome-profile-$(date +%s)"
mkdir -p "$CHROME_PROFILE_DIR"

echo "Testing extension load..."
TEST=$(google-chrome-stable \
  --headless=new --disable-gpu \
  --disable-extensions-except="$AUTOMA_DIR" \
  --load-extension="$AUTOMA_DIR" \
  --print-to-pdf=/dev/null 2>&1 || true)

if echo "$TEST" | grep -q "Extension"; then
  echo "✅ Test load OK in headless=new"
else
  echo "⚠️ Warning: Extension may not load in headless mode. GUI mode will be used."
fi

# Prepare extension loading arguments
EXTENSION_ARGS=""
if [ -n "$AUTOMA_DIR" ] && [ -n "$LINK_KLIPPER_DIR" ]; then
    EXTENSION_ARGS="--disable-extensions-except=\"$AUTOMA_DIR,$LINK_KLIPPER_DIR\" --load-extension=\"$AUTOMA_DIR,$LINK_KLIPPER_DIR\""
    echo "Starting Chrome with Automa and Link Klipper extensions..."
elif [ -n "$AUTOMA_DIR" ]; then
    EXTENSION_ARGS="--disable-extensions-except=\"$AUTOMA_DIR\" --load-extension=\"$AUTOMA_DIR\""
    echo "Starting Chrome with Automa extension only..."
else
    echo "Starting Chrome without extensions..."
fi

# Start Chrome with extensions
eval "google-chrome-stable \
  $EXTENSION_ARGS \
  --no-sandbox --disable-setuid-sandbox \
  --disable-gpu --disable-dev-shm-usage \
  --user-data-dir=\"$CHROME_PROFILE_DIR\" \
  --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 \
  --disable-features=UseOzonePlatform,VizDisplayCompositor \
  --window-size=1920,1080 --start-maximized \
  >/tmp/chrome.log 2>&1 &"

sleep 8
if ! pgrep -f "chrome" >/dev/null; then
  echo "Chrome failed to start; last logs:"; tail -20 /tmp/chrome.log
  exit 1
fi

xterm -geometry 80x24+50+50 -title "Debug Terminal" &

cat <<EOF
==============================================
✅ Environment Ready!
GUI:        http://localhost:6080/vnc.html (password: secret)
DevTools:   http://localhost:9222
Automa:     $AUTOMA_DIR
Link Klipper: $LINK_KLIPPER_DIR
Profile:    $CHROME_PROFILE_DIR

Extensions loaded:
EOF

if [ -n "$AUTOMA_DIR" ]; then
    echo "  ✅ Automa - Web automation extension"
fi

if [ -n "$LINK_KLIPPER_DIR" ]; then
    echo "  ✅ Link Klipper - Extract all links from webpages"
else
    echo "  ❌ Link Klipper - Failed to load (will try manual installation)"
fi

cat <<EOF

Logs:
  Chrome: /tmp/chrome.log
  X11VNC: /tmp/x11vnc.log
  Xvfb:   /tmp/xvfb.log

Usage:
  - Right-click on any webpage to access Link Klipper
  - Use Automa for workflow automation
  - Access Chrome DevTools at port 9222
==============================================
EOF

[ "$1" = "--logs" ] && tail -f /tmp/chrome.log /tmp/x11vnc.log

tail -f /dev/null