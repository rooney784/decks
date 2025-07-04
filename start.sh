#!/bin/bash

# Docker Compose Application Startup Script
# This script ensures services start in the correct order

set -e

echo "🚀 Starting Docker Compose Application..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if a service is healthy
check_service_health() {
    local service_name=$1
    local max_attempts=30
    local attempt=1
    
    echo -e "${YELLOW}Checking health of ${service_name}...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if docker-compose ps ${service_name} | grep -q "healthy"; then
            echo -e "${GREEN}✓ ${service_name} is healthy${NC}"
            return 0
        fi
        
        if [ $attempt -eq 1 ]; then
            echo -n "Waiting for ${service_name} to be healthy"
        fi
        
        echo -n "."
        sleep 10
        ((attempt++))
    done
    
    echo -e "${RED}✗ ${service_name} failed to become healthy after $((max_attempts * 10)) seconds${NC}"
    return 1
}

# Function to check if a service is running
check_service_running() {
    local service_name=$1
    local max_attempts=20
    local attempt=1
    
    echo -e "${YELLOW}Checking if ${service_name} is running...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if docker-compose ps ${service_name} | grep -q "Up"; then
            echo -e "${GREEN}✓ ${service_name} is running${NC}"
            return 0
        fi
        
        if [ $attempt -eq 1 ]; then
            echo -n "Waiting for ${service_name} to start"
        fi
        
        echo -n "."
        sleep 5
        ((attempt++))
    done
    
    echo -e "${RED}✗ ${service_name} failed to start after $((max_attempts * 5)) seconds${NC}"
    return 1
}

# Function to display service logs
show_logs() {
    local service_name=$1
    echo -e "${YELLOW}Recent logs for ${service_name}:${NC}"
    docker-compose logs --tail=10 ${service_name}
    echo ""
}

# Stop all services first
echo -e "${YELLOW}Stopping all services...${NC}"
docker-compose down --remove-orphans

# Clean up any dangling containers
echo -e "${YELLOW}Cleaning up dangling containers...${NC}"
docker system prune -f

# Phase 1: Start databases
echo -e "${GREEN}Phase 1: Starting databases...${NC}"
docker-compose up -d postgres mongodb

# Wait for databases to be healthy
if ! check_service_health postgres; then
    show_logs postgres
    exit 1
fi

if ! check_service_health mongodb; then
    show_logs mongodb
    exit 1
fi

# Phase 2: Start Chrome GUI
echo -e "${GREEN}Phase 2: Starting Chrome GUI...${NC}"
docker-compose up -d chrome-gui

# Wait for Chrome GUI to be healthy
if ! check_service_health chrome-gui; then
    show_logs chrome-gui
    exit 1
fi

# Phase 3: Initialize Airflow
echo -e "${GREEN}Phase 3: Initializing Airflow...${NC}"
docker-compose up -d airflow-init

# Wait for Airflow initialization to complete
if ! check_service_running airflow-init; then
    show_logs airflow-init
    exit 1
fi

# Wait for the init container to finish
echo -e "${YELLOW}Waiting for Airflow initialization to complete...${NC}"
docker-compose logs -f airflow-init &
LOG_PID=$!

while docker-compose ps airflow-init | grep -q "Up"; do
    sleep 5
done

kill $LOG_PID 2>/dev/null || true

# Check if initialization was successful
if ! docker-compose ps airflow-init | grep -q "Exit 0"; then
    echo -e "${RED}✗ Airflow initialization failed${NC}"
    show_logs airflow-init
    exit 1
fi

echo -e "${GREEN}✓ Airflow initialization completed successfully${NC}"

# Phase 4: Start Airflow services
echo -e "${GREEN}Phase 4: Starting Airflow services...${NC}"
docker-compose up -d airflow-webserver airflow-scheduler

# Wait for Airflow services to be healthy
if ! check_service_health airflow-webserver; then
    show_logs airflow-webserver
    exit 1
fi

if ! check_service_health airflow-scheduler; then
    show_logs airflow-scheduler
    exit 1
fi

# Phase 5: Start Streamlit application
echo -e "${GREEN}Phase 5: Starting Streamlit application...${NC}"
docker-compose up -d app

# Wait for Streamlit to be healthy
if ! check_service_health app; then
    show_logs app
    exit 1
fi

# Phase 6: Start backup service if profile is enabled
if [ "$1" == "--with-backup" ]; then
    echo -e "${GREEN}Phase 6: Starting backup service...${NC}"
    docker-compose --profile backup up -d db-backup
    
    if ! check_service_running db-backup; then
        show_logs db-backup
        exit 1
    fi
fi

# Final status check
echo -e "${GREEN}🎉 All services started successfully!${NC}"
echo ""
echo -e "${YELLOW}Service Status:${NC}"
docker-compose ps

echo ""
echo -e "${YELLOW}Access URLs:${NC}"
echo "• Streamlit App: http://localhost:8501"
echo "• Airflow Web UI: http://localhost:8080 (admin: brian / kimu)"
echo "• Chrome VNC: http://localhost:6080"
echo "• Chrome DevTools: http://localhost:9222"
echo "• MongoDB: mongodb://admin:admin123@localhost:27017/messages_db"
echo "• PostgreSQL: postgresql://airflow:airflow@localhost:5432/messages"

echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo "• View logs: docker-compose logs -f [service-name]"
echo "• Stop all: docker-compose down"
echo "• Restart service: docker-compose restart [service-name]"
echo "• Shell access: docker-compose exec [service-name] bash"

echo ""
echo -e "${GREEN}✅ Setup complete! Your application is ready to use.${NC}"