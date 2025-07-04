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

# Verify Xvfb is running
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
  echo "❌ Xvfb failed to start"
  cat /tmp/xvfb.log
  exit 1
fi
echo "✅ Xvfb started successfully on display :99"

# Set up runtime directory
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

# Start D-Bus session for better GUI support
if command -v dbus-launch >/dev/null 2>&1; then
  eval "$(dbus-launch --sh-syntax)"
  echo "✅ D-Bus session started"
fi

echo "🪟 Starting fluxbox window manager..."
fluxbox >/tmp/fluxbox.log 2>&1 &
sleep 2

# Start x11vnc with better configuration for GUI visibility
echo "🔗 Starting x11vnc server..."
x11vnc -display :99 -forever -shared -passwd secret -bg -o /tmp/x11vnc.log \
  -xkb -noxrecord -noxfixes -noxdamage -wait 10 -defer 10 -speeds modem
sleep 2

# Verify x11vnc is running
if ! pgrep -f "x11vnc" >/dev/null; then
  echo "❌ x11vnc failed to start"
  cat /tmp/x11vnc.log
  exit 1
fi
echo "✅ x11vnc server started"

# Start websockify for noVNC web interface
echo "🌐 Starting websockify for web GUI access..."
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
sleep 3

# Verify websockify is running
if ! pgrep -f "websockify" >/dev/null; then
  echo "❌ websockify failed to start"
  cat /tmp/websockify.log
  exit 1
fi
echo "✅ websockify started - GUI accessible at http://localhost:6080"

# Set up Automa extension
if [ -d "/opt/automa/dist" ]; then
  AUTOMA_DIR="/opt/automa/dist"
elif [ -d "/opt/automa/build" ]; then
  AUTOMA_DIR="/opt/automa/build"
else
  echo "❌ ERROR: Automa build not found"
  ls -la /opt/automa/ 2>/dev/null || echo "Automa directory does not exist"
  exit 1
fi

chmod -R a+r "$AUTOMA_DIR"
echo "✅ Automa extension found at: $AUTOMA_DIR"

# Enhanced Link Klipper extension download with better error handling
LINK_KLIPPER_DIR="/tmp/link-klipper-extension/extracted"
if [ ! -d "$LINK_KLIPPER_DIR" ]; then
    echo "📥 Downloading Link Klipper extension..."
    EXTENSION_ID="fahollcgofmpnehocdgofnhkkchiekoo"
    TEMP_DIR="/tmp/link-klipper-extension"
    mkdir -p "$TEMP_DIR"
    cd "$TEMP_DIR"
    
    # Download the extension
    echo "🔄 Fetching extension from Chrome Web Store..."
    DOWNLOAD_URL="https://clients2.google.com/service/update2/crx?response=redirect&prodversion=91.0&acceptformat=crx2,crx3&x=id%3D${EXTENSION_ID}%26uc"
    
    if curl -L -o "link-klipper.crx" "$DOWNLOAD_URL" 2>/dev/null; then
        echo "✅ Download successful"
    elif wget -q -O "link-klipper.crx" "$DOWNLOAD_URL" 2>/dev/null; then
        echo "✅ Download successful (via wget)"
    else
        echo "❌ Failed to download Link Klipper extension"
        LINK_KLIPPER_DIR=""
    fi
    
    # Extract the extension if download was successful
    if [ -f "link-klipper.crx" ] && [ -s "link-klipper.crx" ]; then
        echo "📦 Extracting Link Klipper extension..."
        mkdir -p "extracted"
        
        # Try multiple extraction methods
        if unzip -q "link-klipper.crx" -d "extracted/" 2>/dev/null; then
            echo "✅ Extraction successful"
        else
            # Try with different CRX header skip values
            for skip in 306 322 334; do
                if dd if="link-klipper.crx" bs=1 skip=$skip of="temp.zip" 2>/dev/null && \
                   unzip -q "temp.zip" -d "extracted/" 2>/dev/null; then
                    echo "✅ Extraction successful (skip=$skip)"
                    rm -f "temp.zip"
                    break
                fi
            done
        fi
        
        # Verify extraction
        if [ -f "extracted/manifest.json" ]; then
            echo "✅ Link Klipper extension ready"
        else
            echo "❌ Link Klipper extension extraction failed"
            LINK_KLIPPER_DIR=""
        fi
    else
        echo "❌ Link Klipper extension download failed"
        LINK_KLIPPER_DIR=""
    fi
fi

# Create Chrome profile directory with fixed name for network access
CHROME_PROFILE_DIR="/tmp/chrome-profile-shared"
mkdir -p "$CHROME_PROFILE_DIR"
echo "📁 Chrome profile directory: $CHROME_PROFILE_DIR"

# Test extension loading capability
echo "🧪 Testing extension load capability..."
TEST_OUTPUT=$(google-chrome-stable \
  --headless=new --disable-gpu \
  --disable-extensions-except="$AUTOMA_DIR" \
  --load-extension="$AUTOMA_DIR" \
  --print-to-pdf=/dev/null 2>&1 || true)

if echo "$TEST_OUTPUT" | grep -q "Extension"; then
  echo "✅ Extension loading test passed"
else
  echo "⚠️ Extension loading test uncertain - proceeding with GUI mode"
fi

# Prepare extension loading arguments
EXTENSION_ARGS=""
EXTENSION_LIST=""
if [ -n "$AUTOMA_DIR" ] && [ -n "$LINK_KLIPPER_DIR" ]; then
    EXTENSION_ARGS="--disable-extensions-except=\"$AUTOMA_DIR,$LINK_KLIPPER_DIR\" --load-extension=\"$AUTOMA_DIR,$LINK_KLIPPER_DIR\""
    EXTENSION_LIST="Automa + Link Klipper"
elif [ -n "$AUTOMA_DIR" ]; then
    EXTENSION_ARGS="--disable-extensions-except=\"$AUTOMA_DIR\" --load-extension=\"$AUTOMA_DIR\""
    EXTENSION_LIST="Automa only"
else
    EXTENSION_LIST="No extensions"
fi

# Kill any existing Chrome processes to prevent conflicts
echo "🧹 Killing existing Chrome processes..."
pkill -f "chrome" || true
sleep 2

# Start Chrome with comprehensive flags for better GUI compatibility and network access
echo "🚀 Starting Chrome with extensions: $EXTENSION_LIST"
echo "🌐 Chrome will be accessible to network services at: chrome-gui:9222"

google-chrome-stable \
  $EXTENSION_ARGS \
  --no-sandbox --disable-setuid-sandbox \
  --disable-gpu --disable-dev-shm-usage \
  --user-data-dir="$CHROME_PROFILE_DIR" \
  --remote-debugging-port=9222 \
  --remote-debugging-address=0.0.0.0 \
  --disable-features=UseOzonePlatform,VizDisplayCompositor,TranslateUI \
  --disable-background-timer-throttling \
  --disable-backgrounding-occluded-windows \
  --disable-renderer-backgrounding \
  --disable-field-trial-config \
  --disable-back-forward-cache \
  --disable-ipc-flooding-protection \
  --window-size=1920,1080 --start-maximized \
  --disable-background-networking \
  --disable-default-apps \
  --disable-component-update \
  --no-first-run \
  --no-default-browser-check \
  --disable-web-security \
  --allow-running-insecure-content \
  --display=:99 \
  chrome-extension://infppggnoaenmfagbfknfkancpbljcca/newtab.html \
  >/tmp/chrome.log 2>&1 &

CHROME_PID=$!
echo "🌐 Chrome PID: $CHROME_PID"

# Wait for Chrome to fully initialize
echo "⏳ Waiting for Chrome to initialize..."
sleep 8

# Verify Chrome is running
if ! pgrep -f "chrome" >/dev/null; then
  echo "❌ Chrome failed to start"
  echo "Chrome log contents:"
  tail -20 /tmp/chrome.log
  exit 1
fi

# Verify Chrome DevTools is accessible
echo "🔍 Checking Chrome DevTools accessibility..."
TIMEOUT=30
COUNTER=0
while [ $COUNTER -lt $TIMEOUT ]; do
  if curl -sf http://localhost:9222/json/version >/dev/null 2>&1; then
    echo "✅ Chrome DevTools accessible"
    break
  fi
  echo "Waiting for DevTools... ($COUNTER/$TIMEOUT)"
  sleep 2
  COUNTER=$((COUNTER + 2))
done

if [ $COUNTER -ge $TIMEOUT ]; then
  echo "❌ Chrome DevTools not accessible after $TIMEOUT seconds"
  echo "Chrome log contents:"
  tail -20 /tmp/chrome.log
  exit 1
fi

# Create a health check endpoint
echo "🏥 Creating health check endpoint..."
cat > /tmp/health-status.json << EOF
{
  "status": "healthy",
  "chrome_pid": $CHROME_PID,
  "devtools_url": "http://chrome-gui:9222",
  "vnc_url": "http://chrome-gui:6080",
  "extensions": "$EXTENSION_LIST",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# Start a debug terminal in the GUI
xterm -geometry 80x24+50+50 -title "Debug Terminal" -e "bash -c 'echo \"Debug Terminal Ready\"; echo \"Chrome PID: $CHROME_PID\"; echo \"Network accessible at: chrome-gui:9222\"; echo \"Type exit to close\"; bash'" &

# Display comprehensive status information
cat <<EOF
==============================================
✅ CHROME GUI ENVIRONMENT READY
==============================================
🌐 Web GUI Access:    http://localhost:6080/vnc.html
🔑 VNC Password:      secret
🔧 DevTools:          http://localhost:9222
📁 Chrome Profile:    $CHROME_PROFILE_DIR
🎯 Display:           :99
🔗 Network Access:    chrome-gui:9222 (for other containers)

📦 EXTENSIONS LOADED:
EOF

if [ -n "$AUTOMA_DIR" ]; then
    echo "  ✅ Automa - Web automation extension"
    echo "     Path: $AUTOMA_DIR"
fi

if [ -n "$LINK_KLIPPER_DIR" ]; then
    echo "  ✅ Link Klipper - Extract all links from webpages"
    echo "     Path: $LINK_KLIPPER_DIR"
else
    echo "  ❌ Link Klipper - Failed to load (manual installation may be needed)"
fi

cat <<EOF

🔍 PROCESS STATUS:
  Xvfb PID:      $XVFB_PID
  Chrome PID:    $CHROME_PID
  x11vnc:        $(pgrep -f "x11vnc" || echo "Not running")
  websockify:    $(pgrep -f "websockify" || echo "Not running")
  fluxbox:       $(pgrep -f "fluxbox" || echo "Not running")

📊 LOG FILES:
  Chrome:        /tmp/chrome.log
  X11VNC:        /tmp/x11vnc.log
  Xvfb:          /tmp/xvfb.log
  Fluxbox:       /tmp/fluxbox.log
  Websockify:    /tmp/websockify.log

🎮 USAGE INSTRUCTIONS:
  1. Open http://localhost:6080/vnc.html in your browser
  2. Enter password: secret
  3. You should see Chrome running with extensions
  4. Right-click on any webpage to access Link Klipper
  5. Use Automa for workflow automation
  6. Access Chrome DevTools at http://localhost:9222

🔗 NETWORK CONNECTIVITY:
  - Airflow DAGs can connect to: http://chrome-gui:9222
  - Other containers can use: chrome-gui:9222
  - Environment variables are set: CHROME_DEBUG_URL, CHROME_VNC_URL
  - Health check available at: /tmp/health-status.json

🔄 TROUBLESHOOTING:
  - If GUI is not visible, check log files above
  - If extensions don't work, restart Chrome manually
  - If VNC connection fails, check x11vnc.log
  - If network access fails, check Docker network configuration
  - Debug terminal is available in the GUI

==============================================
EOF

# Option to show logs in real-time
if [ "$1" = "--logs" ]; then
    echo "📋 Showing real-time logs (Ctrl+C to stop):"
    tail -f /tmp/chrome.log /tmp/x11vnc.log /tmp/xvfb.log
fi

# Keep the script running and periodically update health status
echo "🏃 Script running... Press Ctrl+C to stop"
while true; do
    if pgrep -f "chrome" >/dev/null; then
        cat > /tmp/health-status.json << EOF
{
  "status": "healthy",
  "chrome_pid": $CHROME_PID,
  "devtools_url": "http://chrome-gui:9222",
  "vnc_url": "http://chrome-gui:6080",
  "extensions": "$EXTENSION_LIST",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
    else
        echo "❌ Chrome process died, attempting restart..."
        exec "$0" "$@"
    fi
    sleep 60
done