#!/bin/bash
set -e

# Start Xvfb in the background
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99

# Start Fluxbox window manager
fluxbox >/tmp/fluxbox.log 2>&1 &

# Start Chrome
google-chrome --no-sandbox --disable-gpu --window-size=1920,1080 --start-maximized >/tmp/chrome.log 2>&1 &

# Start x11vnc so we can view the display
x11vnc -display :99 -forever -shared -passwd secret >/tmp/x11vnc.log 2>&1 &

# Start noVNC
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &

echo "GUI components started. Access Chrome at:"
echo "http://localhost:6080/vnc.html (password: secret)"

# Keep the script running
tail -f /dev/null