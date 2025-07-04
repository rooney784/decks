# Dockerfile for Chrome GUI with socat for port forwarding
FROM node:20-bullseye

# Install system dependencies including socat for port forwarding
RUN apt-get update && apt-get install -y \
    ca-certificates fonts-liberation libappindicator3-1 libasound2 \
    libatk-bridge2.0-0 libatk1.0-0 libcairo2 libcups2 libdbus-1-3 \
    libexpat1 libfontconfig1 libgbm1 libgcc1 libglib2.0-0 libgtk-3-0 \
    libnspr4 libnss3 libpango-1.0-0 libpangocairo-1.0-0 libstdc++6 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 \
    libxss1 libxtst6 lsb-release wget xdg-utils xvfb fluxbox \
    x11vnc novnc websockify dbus-x11 x11-apps xterm net-tools \
    git build-essential curl socat unzip procps && \
    rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -O /tmp/chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -y /tmp/chrome.deb && rm /tmp/chrome.deb

# Install pnpm & build Automa extension
RUN npm install -g pnpm
RUN git clone https://github.com/AutomaApp/automa.git /opt/automa
WORKDIR /opt/automa
RUN mkdir -p src/utils && \
    echo "export default function() { return 'automa-codespaces'; }" > src/utils/getPassKey.js && \
    pnpm install && pnpm build

# Create startup script that includes socat for port forwarding
RUN cat > /usr/local/bin/start-gui.sh << 'EOF'
#!/bin/bash
set -e

echo "Starting Chrome GUI with socat port forwarding..."

# Start Xvfb
echo "Starting Xvfb display server..."
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset -nolisten tcp &
export DISPLAY=:99
sleep 5

# Start VNC server
echo "Starting VNC server..."
x11vnc -display :99 -forever -shared -rfbport 5900 -bg -o /tmp/x11vnc.log
sleep 3

# Start noVNC
echo "Starting noVNC web interface..."
websockify --web=/usr/share/novnc 6080 localhost:5900 &
sleep 3

# Start Chrome with debugging
echo "Starting Chrome with remote debugging..."
google-chrome \
    --remote-debugging-port=9222 \
    --remote-debugging-address=0.0.0.0 \
    --user-data-dir=/tmp/chrome-profile \
    --disable-dev-shm-usage \
    --no-sandbox \
    --disable-gpu \
    --disable-gpu-sandbox \
    --disable-software-rasterizer \
    --disable-extensions \
    --disable-plugins \
    --disable-background-timer-throttling \
    --disable-backgrounding-occluded-windows \
    --disable-renderer-backgrounding \
    --disable-features=TranslateUI,VizDisplayCompositor \
    --disable-default-apps \
    --no-first-run \
    --headless=new \
    --disable-sync \
    --disable-background-networking \
    --disable-component-extensions-with-background-pages \
    --disable-component-update \
    --disable-client-side-phishing-detection \
    --disable-hang-monitor \
    --disable-prompt-on-repost \
    --disable-web-resources \
    --no-service-autorun \
    --no-default-browser-check \
    --no-pings \
    --no-wifi \
    --disable-logging \
    --silent \
    --log-level=3 \
    --load-extension=/opt/automa/dist &

# Wait for Chrome to start
sleep 10

# Use socat to forward Chrome debugging port to all interfaces
echo "Setting up socat port forwarding for Chrome debugging..."
socat TCP-LISTEN:9223,fork,reuseaddr TCP:127.0.0.1:9222 &

echo "All services started successfully!"
echo "VNC accessible at: http://localhost:6080"
echo "Chrome DevTools at: http://localhost:9222 (internal) or http://localhost:9223 (forwarded)"

# Keep container running
tail -f /dev/null
EOF

RUN chmod +x /usr/local/bin/start-gui.sh

# Create health check script
RUN cat > /usr/local/bin/health-check.sh << 'EOF'
#!/bin/bash
# Check both Chrome DevTools and VNC
if curl -sf http://localhost:9222/json/version >/dev/null 2>&1 && \
   curl -sf http://localhost:6080 >/dev/null 2>&1; then
    exit 0
else
    exit 1
fi
EOF

RUN chmod +x /usr/local/bin/health-check.sh

# Prepare workspace
RUN mkdir -p /workspace && chmod 777 /workspace
WORKDIR /workspace

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /usr/local/bin/health-check.sh

# Expose ports
EXPOSE 6080 9222 9223

# Start services
CMD ["/usr/local/bin/start-gui.sh"]