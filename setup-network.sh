#!/bin/bash
set -e

echo "🔗 Setting up network connectivity..."

# Function to check if network exists
network_exists() {
    docker network ls | grep -q "app-network"
}

# Function to get the devcontainer name
get_devcontainer_name() {
    # Try to find the devcontainer by looking for running containers with our image
    CONTAINER_NAME=$(docker ps --format "table {{.Names}}" | grep -E "(devcontainer|chrome)" | head -1)
    if [ -z "$CONTAINER_NAME" ]; then
        echo "❌ Could not find devcontainer"
        return 1
    fi
    echo "$CONTAINER_NAME"
}

# Create network if it doesn't exist
if ! network_exists; then
    echo "📡 Creating app-network..."
    docker network create app-network --driver bridge
    echo "✅ app-network created"
else
    echo "✅ app-network already exists"
fi

# Get devcontainer name
DEVCONTAINER_NAME=$(get_devcontainer_name)
if [ $? -eq 0 ]; then
    echo "📦 Found devcontainer: $DEVCONTAINER_NAME"
    
    # Check if container is already connected to the network
    if docker network inspect app-network --format '{{range .Containers}}{{.Name}} {{end}}' | grep -q "$DEVCONTAINER_NAME"; then
        echo "✅ Devcontainer already connected to app-network"
    else
        echo "🔌 Connecting devcontainer to app-network..."
        docker network connect app-network "$DEVCONTAINER_NAME"
        echo "✅ Devcontainer connected to app-network"
    fi
    
    # Start the GUI service
    echo "🚀 Starting Chrome GUI service..."
    docker exec "$DEVCONTAINER_NAME" /usr/local/bin/start-gui.sh &
    
    echo "✅ Network setup complete!"
    echo "🌐 Chrome will be accessible at: http://$DEVCONTAINER_NAME:9222"
else
    echo "❌ Failed to find devcontainer"
    exit 1
fi