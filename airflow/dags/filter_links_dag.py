from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import os
import requests
import time

# Default args
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2025, 6, 27),
    'retries': 2,
    'retry_delay': timedelta(seconds=30),
    'max_active_tis_per_dag': 1,  # Prevent multiple instances
}

dag = DAG(
    dag_id='extract_and_filter_links_v2',
    default_args=default_args,
    schedule_interval=timedelta(minutes=15),
    catchup=False,
    max_active_runs=1,
    tags=['puppeteer', 'filter', 'db', 'chrome-headless']
)

def check_chrome_health():
    """Python function to robustly check Chrome health"""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.get('http://localhost:9222/json/version', timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Chrome is healthy: {data.get('Product', 'Unknown version')}")
                return True
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
    
    raise Exception("Chrome health check failed after all retries")

# Task 1: Start Chrome with proper background execution
start_chrome = BashOperator(
    task_id='start_chrome',
    bash_command='''
        set -e  # Exit on any error
        
        echo "🚀 Starting Chrome setup..."
        
        # Kill any existing processes (ignore errors)
        pkill -f "google-chrome" 2>/dev/null || true
        pkill -f "Xvfb" 2>/dev/null || true
        
        # Clean up old profiles
        find /tmp -maxdepth 1 -name 'chrome-profile-*' -type d -exec rm -rf {} + 2>/dev/null || true
        
        # Set up display
        export DISPLAY=:99
        export XDG_RUNTIME_DIR=/tmp/runtime-airflow
        mkdir -p "$XDG_RUNTIME_DIR"
        
        # Start Xvfb with better configuration
        echo "🖥️ Starting Xvfb..."
        nohup Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR +extension GLX +render -noreset -dpi 96 > /tmp/xvfb.log 2>&1 &
        XVFB_PID=$!
        sleep 5
        
        # Create unique Chrome profile
        CHROME_PROFILE_DIR="/tmp/chrome-profile-$(date +%s)-$"
        mkdir -p "$CHROME_PROFILE_DIR"
        
        echo "📁 Chrome profile: $CHROME_PROFILE_DIR"
        
        # Start Chrome with comprehensive flags - IMPORTANT: Use nohup and redirect output
        echo "🌐 Starting Chrome..."
        nohup google-chrome-stable \
            --no-sandbox \
            --disable-setuid-sandbox \
            --disable-gpu \
            --disable-software-rasterizer \
            --disable-dev-shm-usage \
            --disable-extensions \
            --disable-plugins \
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
            --window-size=1920,1080 \
            --disable-background-networking \
            --disable-default-apps \
            --disable-component-update \
            --no-first-run \
            --no-default-browser-check \
            --display=:99 \
            --headless=new \
            about:blank > /tmp/chrome.log 2>&1 &
        
        CHROME_PID=$!
        echo "🌐 Chrome PID: $CHROME_PID, Xvfb PID: $XVFB_PID"
        
        # Store PIDs for cleanup
        echo "$CHROME_PID" > /tmp/chrome.pid
        echo "$XVFB_PID" > /tmp/xvfb.pid
        echo "$CHROME_PROFILE_DIR" > /tmp/chrome_profile.path
        
        # Wait for Chrome to be ready with timeout
        echo "⏳ Waiting for Chrome to start..."
        TIMEOUT=30
        COUNTER=0
        
        while [ $COUNTER -lt $TIMEOUT ]; do
            if curl -sf http://localhost:9222/json/version > /dev/null 2>&1; then
                echo "✅ Chrome is ready and responding on port 9222"
                curl -s http://localhost:9222/json/version | head -n 1
                break
            fi
            
            # Check if Chrome process is still running
            if ! kill -0 "$CHROME_PID" 2>/dev/null; then
                echo "❌ Chrome process died unexpectedly"
                cat /tmp/chrome.log || echo "No Chrome log available"
                exit 1
            fi
            
            echo "Waiting... ($COUNTER/$TIMEOUT)"
            sleep 2
            COUNTER=$((COUNTER + 1))
        done
        
        if [ $COUNTER -eq $TIMEOUT ]; then
            echo "❌ Chrome failed to start within timeout"
            cat /tmp/chrome.log || echo "No Chrome log available"
            exit 1
        fi
        
        echo "✅ Chrome startup completed successfully"
    ''',
    dag=dag,
)

# Task 2: Health check using Python
chrome_health_check = PythonOperator(
    task_id='chrome_health_check',
    python_callable=check_chrome_health,
    dag=dag,
)

# Task 3: Extract and filter with better error handling
extract_and_filter = BashOperator(
    task_id='extract_and_filter',
    bash_command='''
        set -e
        
        echo "🔍 Starting extraction process..."
        
        # Verify Chrome is still running
        if ! curl -sf http://localhost:9222/json/version > /dev/null; then
            echo "❌ Chrome is not responding"
            exit 1
        fi
        
        # Navigate to project directory
        cd /opt/airflow/src || {
            echo "❌ Source directory not found"
            exit 1
        }
        
        # Environment setup
        export MONGODB_URI="{{ var.value.MONGODB_URI }}"
        export NODE_ENV=production
        export CHROME_DEBUG_PORT=9222
        
        # Verify Node.js setup
        echo "Node.js version: $(node --version)"
        echo "NPM version: $(npm --version)"
        
        # Check if puppeteer is available
        if ! npm list puppeteer-core >/dev/null 2>&1; then
            echo "⚠️ Installing puppeteer-core..."
            npm install puppeteer-core
        fi
        
        # Run the extraction
        echo "🚀 Running extraction script..."
        timeout 300 node open_and_extract.js --extract-only || {
            echo "❌ Extraction failed or timed out"
            exit 1
        }
        
        echo "✅ Extraction completed successfully"
    ''',
    dag=dag,
)

# Task 4: Comprehensive cleanup
cleanup_chrome = BashOperator(
    task_id='cleanup_chrome',
    trigger_rule='all_done',  # Run regardless of upstream task status
    bash_command='''
        echo "🧹 Starting cleanup..."
        
        # Kill Chrome process
        if [ -f /tmp/chrome.pid ]; then
            CHROME_PID=$(cat /tmp/chrome.pid)
            kill -TERM "$CHROME_PID" 2>/dev/null || true
            sleep 5
            kill -KILL "$CHROME_PID" 2>/dev/null || true
            rm -f /tmp/chrome.pid
        fi
        
        # Kill Xvfb process
        if [ -f /tmp/xvfb.pid ]; then
            XVFB_PID=$(cat /tmp/xvfb.pid)
            kill -TERM "$XVFB_PID" 2>/dev/null || true
            sleep 2
            kill -KILL "$XVFB_PID" 2>/dev/null || true
            rm -f /tmp/xvfb.pid
        fi
        
        # Kill any remaining processes
        pkill -f "google-chrome" 2>/dev/null || true
        pkill -f "Xvfb" 2>/dev/null || true
        
        # Clean up profile directory
        if [ -f /tmp/chrome_profile.path ]; then
            PROFILE_PATH=$(cat /tmp/chrome_profile.path)
            rm -rf "$PROFILE_PATH" 2>/dev/null || true
            rm -f /tmp/chrome_profile.path
        fi
        
        # Clean up any remaining profiles
        find /tmp -maxdepth 1 -name 'chrome-profile-*' -type d -exec rm -rf {} + 2>/dev/null || true
        
        # Clean up runtime directory
        rm -rf /tmp/runtime-airflow 2>/dev/null || true
        
        echo "✅ Cleanup completed"
    ''',
    dag=dag,
)

# Task dependencies
start_chrome >> chrome_health_check >> extract_and_filter >> cleanup_chrome