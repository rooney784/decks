
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
    'start_date': datetime(2025, 6, 27, 3, 5),
    'retries': 2,
    'retry_delay': timedelta(minutes=2),
    'max_active_tis_per_dag': 1,  # Prevent multiple instances
    'email_on_failure': False,
    'email_on_retry': False,
}

dag = DAG(
    dag_id='inject_workflow_js_v2',
    default_args=default_args,
    schedule_interval="*/10 3-7 * * *",  # Every 10 minutes between 3-7 UTC
    catchup=False,
    max_active_runs=1,
    description="Inject workflows into Automa with Chrome lifecycle management",
    tags=['workflow', 'injection', 'automa', 'chrome-lifecycle']
)

def check_chrome_and_automa_health():
    """Python function to check Chrome health and Automa extension availability"""
    max_retries = 5
    
    # First check Chrome health
    for attempt in range(max_retries):
        try:
            response = requests.get('http://localhost:9222/json/version', timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Chrome is healthy: {data.get('Product', 'Unknown version')}")
                break
        except Exception as e:
            print(f"Chrome health attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise Exception("Chrome health check failed after all retries")
    
    # Check if we can access Chrome tabs (looking for Automa)
    try:
        tabs_response = requests.get('http://localhost:9222/json', timeout=5)
        if tabs_response.status_code == 200:
            tabs = tabs_response.json()
            print(f"✅ Chrome has {len(tabs)} tab(s) available")
            
            # Look for chrome-extension URLs or newtab
            automa_tabs = [tab for tab in tabs if 'chrome-extension' in tab.get('url', '') or 'newtab' in tab.get('url', '')]
            if automa_tabs:
                print(f"✅ Found {len(automa_tabs)} extension tab(s)")
            else:
                print("ℹ️ No extension tabs found yet, but Chrome is ready")
        else:
            raise Exception(f"Failed to get Chrome tabs: {tabs_response.status_code}")
    except Exception as e:
        print(f"Warning: Could not check Chrome tabs: {e}")
    
    return True

# Task 1: Start Chrome with Automa extension
start_chrome_with_automa = BashOperator(
    task_id='start_chrome_with_automa',
    bash_command='''
        set -e  # Exit on any error
        
        echo "🚀 Starting Chrome with Automa setup..."
        
        # Kill any existing processes (ignore errors)
        pkill -f "google-chrome" 2>/dev/null || true
        pkill -f "Xvfb" 2>/dev/null || true
        
        # Clean up old profiles
        find /tmp -maxdepth 1 -name 'chrome-profile-*' -type d -exec rm -rf {} + 2>/dev/null || true
        
        # Set up display
        export DISPLAY=:99
        export XDG_RUNTIME_DIR=/tmp/runtime-airflow
        mkdir -p "$XDG_RUNTIME_DIR"
        chmod 700 "$XDG_RUNTIME_DIR"
        
        # Start Xvfb with better configuration
        echo "🖥️ Starting Xvfb..."
        nohup Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR +extension GLX +render -noreset -dpi 96 > /tmp/xvfb.log 2>&1 &
        XVFB_PID=$!
        sleep 5
        
        # Start fluxbox window manager for better extension compatibility
        echo "🪟 Starting fluxbox..."
        nohup fluxbox > /tmp/fluxbox.log 2>&1 &
        sleep 3
        
        # Find Automa extension directory
        if [ -d "/opt/automa/dist" ]; then
            AUTOMA_DIR="/opt/automa/dist"
        elif [ -d "/opt/automa/build" ]; then
            AUTOMA_DIR="/opt/automa/build"
        else
            echo "❌ ERROR: Automa build not found"
            ls -la /opt/automa/ || echo "Automa directory does not exist"
            exit 1
        fi
        
        echo "📦 Using Automa extension from: $AUTOMA_DIR"
        
        # Create unique Chrome profile
        CHROME_PROFILE_DIR="/tmp/chrome-profile-$(date +%s)-$$"
        mkdir -p "$CHROME_PROFILE_DIR"
        
        echo "📁 Chrome profile: $CHROME_PROFILE_DIR"
        
        # Start Chrome with Automa extension - IMPORTANT: Use nohup and redirect output
        echo "🌐 Starting Chrome with Automa..."
        nohup google-chrome-stable \
            --disable-extensions-except="$AUTOMA_DIR" \
            --load-extension="$AUTOMA_DIR" \
            --no-sandbox \
            --disable-setuid-sandbox \
            --disable-gpu \
            --disable-software-rasterizer \
            --disable-dev-shm-usage \
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
            --start-maximized \
            --disable-background-networking \
            --disable-default-apps \
            --disable-component-update \
            --no-first-run \
            --no-default-browser-check \
            --display=:99 \
            chrome-extension://infppggnoaenmfagbfknfkancpbljcca/newtab.html > /tmp/chrome.log 2>&1 &
        
        CHROME_PID=$!
        echo "🌐 Chrome PID: $CHROME_PID, Xvfb PID: $XVFB_PID"
        
        # Store PIDs and paths for cleanup
        echo "$CHROME_PID" > /tmp/chrome.pid
        echo "$XVFB_PID" > /tmp/xvfb.pid
        echo "$CHROME_PROFILE_DIR" > /tmp/chrome_profile.path
        echo "$AUTOMA_DIR" > /tmp/automa_dir.path
        
        # Wait for Chrome to be ready with timeout
        echo "⏳ Waiting for Chrome to start..."
        TIMEOUT=45
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
                echo "Chrome log contents:"
                cat /tmp/chrome.log || echo "No Chrome log available"
                exit 1
            fi
            
            echo "Waiting... ($COUNTER/$TIMEOUT)"
            sleep 3
            COUNTER=$((COUNTER + 3))
        done
        
        if [ $COUNTER -ge $TIMEOUT ]; then
            echo "❌ Chrome failed to start within timeout"
            echo "Chrome log contents:"
            cat /tmp/chrome.log || echo "No Chrome log available"
            exit 1
        fi
        
        # Give extension additional time to load
        echo "⏳ Allowing extension time to initialize..."
        sleep 10
        
        echo "✅ Chrome with Automa startup completed successfully"
    ''',
    dag=dag,
)

# Task 2: Health check using Python
chrome_automa_health_check = PythonOperator(
    task_id='chrome_automa_health_check',
    python_callable=check_chrome_and_automa_health,
    dag=dag,
)

# Task 3: Run workflow injection
inject_workflows = BashOperator(
    task_id='inject_workflows',
    bash_command='''
        set -e
        
        echo "💉 Starting workflow injection process..."
        
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
        
        # Check if required packages are available
        if ! npm list puppeteer-core >/dev/null 2>&1; then
            echo "⚠️ Installing puppeteer-core..."
            npm install puppeteer-core
        fi
        if ! npm list mongodb >/dev/null 2>&1; then
            echo "⚠️ Installing mongodb..."
            npm install mongodb
        fi
        
        # Verify workflow injection script exists
        if [ ! -f "injectworkflow.js" ]; then
            echo "❌ injectworkflow.js not found in $(pwd)"
            echo "Available files:"
            ls -la
            exit 1
        fi
        
        # Run the workflow injection with timeout
        echo "🚀 Running workflow injection..."
        timeout 180 node injectworkflow.js || {
            EXIT_CODE=$?
            if [ $EXIT_CODE -eq 124 ]; then
                echo "❌ Workflow injection timed out after 3 minutes"
            else
                echo "❌ Workflow injection failed with exit code: $EXIT_CODE"
            fi
            echo "Chrome log contents:"
            cat /tmp/chrome.log || echo "No Chrome log available"
            exit 1
        }
        
        echo "✅ Workflow injection completed successfully"
    ''',
    dag=dag,
)

# Task 4: Comprehensive cleanup
cleanup_chrome_and_automa = BashOperator(
    task_id='cleanup_chrome_and_automa',
    trigger_rule='all_done',  # Run regardless of upstream task status
    bash_command='''
        echo "🧹 Starting cleanup..."
        
        # Kill Chrome process
        if [ -f /tmp/chrome.pid ]; then
            CHROME_PID=$(cat /tmp/chrome.pid)
            echo "Terminating Chrome process: $CHROME_PID"
            kill -TERM "$CHROME_PID" 2>/dev/null || true
            sleep 5
            kill -KILL "$CHROME_PID" 2>/dev/null || true
            rm -f /tmp/chrome.pid
        fi
        
        # Kill Xvfb process
        if [ -f /tmp/xvfb.pid ]; then
            XVFB_PID=$(cat /tmp/xvfb.pid)
            echo "Terminating Xvfb process: $XVFB_PID"
            kill -TERM "$XVFB_PID" 2>/dev/null || true
            sleep 2
            kill -KILL "$XVFB_PID" 2>/dev/null || true
            rm -f /tmp/xvfb.pid
        fi
        
        # Kill any remaining processes
        pkill -f "google-chrome" 2>/dev/null || true
        pkill -f "Xvfb" 2>/dev/null || true
        pkill -f "fluxbox" 2>/dev/null || true
        
        # Clean up profile directory
        if [ -f /tmp/chrome_profile.path ]; then
            PROFILE_PATH=$(cat /tmp/chrome_profile.path)
            echo "Cleaning up Chrome profile: $PROFILE_PATH"
            rm -rf "$PROFILE_PATH" 2>/dev/null || true
            rm -f /tmp/chrome_profile.path
        fi
        
        # Clean up any remaining profiles
        find /tmp -maxdepth 1 -name 'chrome-profile-*' -type d -exec rm -rf {} + 2>/dev/null || true
        
        # Clean up runtime directory
        rm -rf /tmp/runtime-airflow 2>/dev/null || true
        
        # Clean up temp files
        rm -f /tmp/automa_dir.path /tmp/chrome.log /tmp/xvfb.log /tmp/fluxbox.log 2>/dev/null || true
        
        echo "✅ Cleanup completed"
    ''',
    dag=dag,
)

# Task dependencies
start_chrome_with_automa >> chrome_automa_health_check >> inject_workflows >> cleanup_chrome_and_automa

# injectworkflow.js
"""
const puppeteer = require('puppeteer-core');
const { MongoClient } = require('mongodb');

(async () => {
  // Connect to MongoDB
  const uri = process.env.MONGODB_URI;
  if (!uri) throw new Error('MONGODB_URI environment variable not set');
  
  const client = new MongoClient(uri, { 
    serverSelectionTimeoutMS: 5000,
    connectTimeoutMS: 10000
  });
  
  try {
    await client.connect();
    console.log('✅ Connected to MongoDB');
    
    const db = client.db('messages_db');
    const workflowsCollection = db.collection('workflows');
    
    // Fetch workflows from MongoDB
    const workflows = await workflowsCollection.find({}).toArray();
    if (workflows.length === 0) {
      console.warn('⚠️ No workflows found in MongoDB');
      return;
    }
    console.log(`✅ Retrieved ${workflows.length} workflows from MongoDB`);

    // Connect to browser
    const browser = await puppeteer.connect({
      browserURL: 'http://localhost:9222',
      defaultViewport: null,
    });

    try {
      // Find Automa dashboard page
      let page;
      const deadline = Date.now() + 60000;
      while (!page && Date.now() < deadline) {
        page = (await browser.pages()).find(p => p.url().includes('/newtab.html'));
        if (!page) await new Promise(r => setTimeout(r, 1000));
      }
      if (!page) throw new Error('Automa dashboard not found');
      await page.waitForSelector('#app', { timeout: 20000 });

      // Import workflows
      for (const wf of workflows) {
        try {
          await page.evaluate(wf => {
            chrome.storage.local.get('workflows', res => {
              const arr = Array.isArray(res.workflows) ? res.workflows : [];
              if (!arr.find(w => w.id === wf.id)) {
                arr.unshift(wf);
                chrome.storage.local.set({ workflows: arr });
              }
            });
          }, wf);
          console.log(`✅ Workflow imported: ${wf.name}`);
        } catch (err) {
          console.warn(`⚠️ Failed to import workflow ${wf.name}: ${err.message}`);
        }
      }

      // Reload dashboard
      await Promise.all([
        page.reload({ waitUntil: ['domcontentloaded', 'networkidle0'] }),
        page.waitForNavigation({ waitUntil: ['domcontentloaded', 'networkidle0'] }),
      ]);
      console.log('🔄 Dashboard reloaded');

      // Execute workflows
      for (const wf of workflows) {
        console.log(`▶️ Executing workflow: ${wf.name}`);
        await page.evaluate(async (workflowId) => {
          // Load the actual workflow object from storage
          const all = await chrome.storage.local.get('workflows');
          const wfObj = (all.workflows || []).find(w => w.id === workflowId);
          if (!wfObj) {
            console.error('Workflow not found:', workflowId);
            return;
          }
          // Send the execution message to background script
          chrome.runtime.sendMessage({
            name: 'background--workflow:execute',
            data: { ...wfObj, options: { data: { variables: {} } } },
          });
        }, wf.id);

        // Give it a moment to start
        await new Promise(r => setTimeout(r, 2000));
      }

      console.log('✅ All workflows dispatched – check Automa logs.');
    } finally {
      await browser.disconnect();
      console.log('🔚 Browser disconnected');
    }
  } catch (err) {
    console.error('❌ Fatal error:', err);
    process.exit(1);
  } finally {
    await client.close();
    console.log('🔒 MongoDB connection closed');
  }
})();
"""
