FROM node:20-bullseye

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates fonts-liberation libappindicator3-1 libasound2 \
    libatk-bridge2.0-0 libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 \
    libexpat1 libfontconfig1 libgbm1 libgcc1 libglib2.0-0 libgtk-3-0 \
    libnspr4 libnss3 libpango-1.0-0 libpangocairo-1.0-0 libstdc++6 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 \
    libxss1 libxtst6 lsb-release wget xdg-utils xvfb fluxbox \
    x11vnc novnc websockify dbus-x11 x11-apps xterm net-tools \
    git build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -O /tmp/chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -y /tmp/chrome.deb && rm /tmp/chrome.deb

# Install pnpm
RUN npm install -g pnpm

# Clone and build Automa
RUN git clone https://github.com/AutomaApp/automa.git /opt/automa
WORKDIR /opt/automa
RUN mkdir -p src/utils && \
    echo "export default function() { return 'automa-codespaces'; }" > src/utils/getPassKey.js
RUN pnpm install && pnpm build

# Make GUI start script executable
COPY start-gui.sh /usr/local/bin/start-gui.sh
RUN chmod +x /usr/local/bin/start-gui.sh

# Create a separate workspace for development
RUN mkdir -p /workspace && chmod 777 /workspace

# Create a health check script
RUN echo '#!/bin/bash\ncurl -sf http://localhost:9222/json/version >/dev/null 2>&1' > /usr/local/bin/health-check.sh && \
    chmod +x /usr/local/bin/health-check.sh

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /usr/local/bin/health-check.sh

# Optional: start container in /workspace but keep /opt/automa built and usable
WORKDIR /workspace

EXPOSE 6080 9222

# Start GUI and keep container running
CMD ["/usr/local/bin/start-gui.sh"]