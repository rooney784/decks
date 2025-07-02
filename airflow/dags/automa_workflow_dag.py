import os
import sys
import logging
import re
import json
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
from airflow import DAG
from airflow.operators.python import PythonOperator
from pymongo import MongoClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/airflow/logs/automa_workflow.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin")
client = MongoClient(MONGODB_URI)
db = client['messages_db']

WORKFLOW_GENERATION_ENABLED = os.getenv("WORKFLOW_GENERATION_ENABLED", "true").lower() == "true"
WORKFLOW_TEMPLATE_PATH = "/opt/airflow/src/automata/deck.automa.json"

def ensure_template_file_exists():
    if not os.path.exists(WORKFLOW_TEMPLATE_PATH):
        logger.error(f"Template file not found: {WORKFLOW_TEMPLATE_PATH}")
        raise FileNotFoundError(f"Missing: {WORKFLOW_TEMPLATE_PATH}")
    return WORKFLOW_TEMPLATE_PATH

def get_unused_messages_from_postgres(limit):
    logger.info(f"Fetching {limit} messages from PostgreSQL")
    sys.path.append('/opt/airflow/src')
    try:
        from core.database import get_unused_messages
        messages = get_unused_messages(limit=limit)
        return [(m_id, content) for m_id, content, _ in messages]
    except Exception as e:
        logger.error(f"PostgreSQL message fetch error: {e}")
        return []

def mark_message_as_used_in_mongo(message_id):
    logger.info(f"Marking message {message_id} as used in MongoDB")
    try:
        db.messages.update_one(
            {"message_id": message_id},
            {"$set": {"used": True, "used_time": datetime.now().isoformat()}}
        )
    except Exception as e:
        logger.error(f"MongoDB mark error: {e}")

def log_workflow_generation(name, message_id):
    try:
        db.workflow_stats.insert_one({
            "workflow_name": name,
            "message_id": message_id,
            "date": datetime.now().date().isoformat(),
            "hour": datetime.now().hour,
            "created_at": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to log workflow stat: {e}")

def generate_press_key_blocks(sentence, base_item_id):
    words = re.findall(r'\b\w+\b|[^\w\s]', sentence)
    blocks = []
    for i, word in enumerate(words):
        blocks.append({
            "id": "press-key",
            "itemId": f"{base_item_id}_{i}",
            "data": {
                "disableBlock": False,
                "keys": word,
                "selector": "",
                "pressTime": "3000",
                "description": "",
                "keysToPress": "",
                "action": "press-key",
                "onError": {
                    "retry": False,
                    "enable": True,
                    "retryTimes": 1,
                    "retryInterval": 2,
                    "toDo": "continue",
                    "insertData": False,
                    "dataToInsert": []
                },
                "settings": {"blockTimeout": 0, "debugMode": False}
            }
        })
        if i < len(words) - 1 and not re.match(r'^[^\w\s]+$', word):
            blocks.append({
                "id": "press-key",
                "itemId": f"{base_item_id}_{i}_space",
                "data": {
                    "disableBlock": False,
                    "keys": " ",
                    "selector": "",
                    "pressTime": "3000",
                    "description": "",
                    "keysToPress": "",
                    "action": "press-key",
                    "onError": {
                        "retry": False,
                        "enable": True,
                        "retryTimes": 1,
                        "retryInterval": 2,
                        "toDo": "continue",
                        "insertData": False,
                        "dataToInsert": []
                    },
                    "settings": {"blockTimeout": 0, "debugMode": False}
                }
            })
    return blocks

def update_json_with_message(input_file, name, message_text, message_id):
    with open(input_file) as f:
        data = json.load(f)

    data['id'] = str(uuid.uuid4())
    data['name'] = name

    for node in data.get('drawflow', {}).get('nodes', []):
        if node.get('type') == 'BlockGroup':
            new_blocks = []
            for blk in node['data']['blocks']:
                if blk.get('id') == 'press-key' and blk['data'].get('keys') == 'MESSAGE_PLACEHOLDER':
                    new_blocks.extend(generate_press_key_blocks(message_text, f"{name}_{message_id}"))
                else:
                    new_blocks.append(blk)
            node['data']['blocks'] = new_blocks

    try:
        db.workflows.insert_one({
            "workflow_id": data['id'],
            "name": name,
            "content": data,
            "message_id": message_id,
            "created_at": datetime.now().isoformat()
        })
        return True
    except Exception as e:
        logger.error(f"Failed to save workflow: {e}")
        return False

def generate_automa_workflows():
    if not WORKFLOW_GENERATION_ENABLED:
        logger.warning("Workflow generation is disabled")
        return 0, 0

    ensure_template_file_exists()
    messages = get_unused_messages_from_postgres(6)
    names = ['one', 'two', 'three', 'four', 'five', 'six']
    success = 0

    for i, (msg_id, msg_text) in enumerate(messages):
        name = names[i % len(names)]
        if update_json_with_message(WORKFLOW_TEMPLATE_PATH, name, msg_text, msg_id):
            mark_message_as_used_in_mongo(msg_id)
            log_workflow_generation(name, msg_id)
            success += 1

    return len(messages), success

def run_task():
    logger.info("Running Automa workflow generation task")
    total, success = generate_automa_workflows()
    logger.info(f"{success}/{total} workflows generated")
    if total > 0 and success == 0:
        raise Exception("Workflow generation failed for all entries")
    return f"Generated {success}/{total} workflows"

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 6, 27, 3, 5),
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'retry_exponential_backoff': True,
}

dag = DAG(
    'automa_workflow_generation',
    default_args=default_args,
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    description="Generate Automa workflows from PostgreSQL messages, save in MongoDB"
)

generate = PythonOperator(
    task_id='generate_automa_workflows',
    python_callable=run_task,
    dag=dag
)
