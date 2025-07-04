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
    'max_active_tis_per_dag': 1,
    'email_on_failure': False,
    'email_on_retry': False,
}

dag = DAG(
    dag_id='inject_workflow_js_v2',
    default_args=default_args,
    schedule_interval="*/10 3-7 * * *",  # Every 10 minutes between 3-7 UTC
    catchup=False,
    max_active_runs=1,
    description="Inject workflows into Automa using existing Chrome instance",
    tags=['workflow', 'injection', 'automa', 'chrome-lifecycle']
)

def check_chrome_and_automa_health():
    """Check Chrome health and Automa extension availability"""
    max_retries = 5
    chrome_url = os.getenv('CHROME_DEBUG_URL', 'http://chrome-gui:9222')

    for attempt in range(max_retries):
        try:
            response = requests.get(f'{chrome_url}/json/version', timeout=5)
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

    try:
        tabs_response = requests.get(f'{chrome_url}/json', timeout=5)
        if tabs_response.status_code == 200:
            tabs = tabs_response.json()
            print(f"✅ Chrome has {len(tabs)} tab(s) available")
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

chrome_automa_health_check = PythonOperator(
    task_id='chrome_automa_health_check',
    python_callable=check_chrome_and_automa_health,
    dag=dag,
)

inject_workflows = BashOperator(
    task_id='inject_workflows',
    bash_command='''
        set -e

        echo "💉 Starting workflow injection process..."

        CHROME_URL=${CHROME_DEBUG_URL:-http://chrome-gui:9222}
        if ! curl -sf "$CHROME_URL/json/version" > /dev/null; then
            echo "❌ Chrome is not responding at $CHROME_URL"
            exit 1
        fi

        cd /opt/airflow/src || {
            echo "❌ Source directory not found"
            exit 1
        }

        export MONGODB_URI="{{ var.value.MONGODB_URI }}"
        export NODE_ENV=production
        export CHROME_DEBUG_URL="$CHROME_URL"

        echo "Node.js version: $(node --version)"
        echo "NPM version: $(npm --version)"

        if ! npm list puppeteer-core >/dev/null 2>&1; then
            echo "⚠️ Installing puppeteer-core..."
            npm install puppeteer-core
        fi
        if ! npm list mongodb >/dev/null 2>&1; then
            echo "⚠️ Installing mongodb..."
            npm install mongodb
        fi

        if [ ! -f "injectworkflow.js" ]; then
            echo "❌ injectworkflow.js not found in $(pwd)"
            echo "Available files:"
            ls -la
            exit 1
        fi

        echo "🚀 Running workflow injection..."
        timeout 180 node injectworkflow.js || {
            EXIT_CODE=$?
            if [ $EXIT_CODE -eq 124 ]; then
                echo "❌ Workflow injection timed out after 3 minutes"
            else
                echo "❌ Workflow injection failed with exit code: $EXIT_CODE"
            fi
            exit 1
        }

        echo "✅ Workflow injection completed successfully"
    ''',
    dag=dag,
)

# Set task dependency chain
chrome_automa_health_check >> inject_workflows
