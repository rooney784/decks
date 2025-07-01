# airflow/dags/automa_workflow_generation_dag.py
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/airflow/logs/automa_workflow.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin")
client = MongoClient(MONGODB_URI)
db = client['messages_db']

MAX_WORKFLOWS_PER_DAY = int(os.getenv("MAX_WORKFLOWS_PER_DAY", "6"))
MAX_WORKFLOWS_PER_HOUR = int(os.getenv("MAX_WORKFLOWS_PER_HOUR", "2"))
WORKFLOW_GENERATION_ENABLED = os.getenv("WORKFLOW_GENERATION_ENABLED", "true").lower() == "true"

# Fix the template file path - make it absolute and create if not exists
WORKFLOW_TEMPLATE_PATH = "/opt/airflow/workflows/deck.automa.json"

def ensure_template_file_exists():
    """Create the template file if it doesn't exist"""
    os.makedirs(os.path.dirname(WORKFLOW_TEMPLATE_PATH), exist_ok=True)
    
    if not os.path.exists(WORKFLOW_TEMPLATE_PATH):
        logger.info(f"Creating template file at {WORKFLOW_TEMPLATE_PATH}")
        
        # Default template structure
        template = {
            "name": "Automa Workflow Template",
            "id": str(uuid.uuid4()),
            "version": "1.0.0",
            "drawflow": {
                "nodes": [
                    {
                        "type": "BlockGroup",
                        "data": {
                            "blocks": [
                                {
                                    "id": "new-tab",
                                    "itemId": "new_tab_1",
                                    "data": {
                                        "url": "https://twitter.com",
                                        "active": True,
                                        "inBackground": False,
                                        "updatePrevTab": False,
                                        "windowId": "",
                                        "onError": {
                                            "retry": False,
                                            "enable": True,
                                            "retryTimes": 1,
                                            "retryInterval": 2,
                                            "toDo": "continue"
                                        }
                                    }
                                },
                                {
                                    "id": "press-key",
                                    "itemId": "press_key_placeholder",
                                    "data": {
                                        "disableBlock": False,
                                        "keys": "MESSAGE_PLACEHOLDER",
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
                                }
                            ]
                        }
                    }
                ]
            }
        }
        
        with open(WORKFLOW_TEMPLATE_PATH, 'w') as f:
            json.dump(template, f, indent=2)
        
        logger.info(f"Template file created at {WORKFLOW_TEMPLATE_PATH}")
    
    return WORKFLOW_TEMPLATE_PATH

def get_unused_tweets(limit):
    logger.info(f"Fetching up to {limit} unused tweets")
    try:
        tweets = db.tweets.find({"used": False}).sort("scraped_time", -1).limit(limit)
        result = [(tweet['tweet_id'], tweet['link']) for tweet in tweets]
        logger.info(f"Fetched {len(result)} tweets from MongoDB")
        
        # If no tweets in MongoDB, try PostgreSQL fallback
        if not result:
            logger.info("No tweets in MongoDB, checking PostgreSQL...")
            sys.path.append('/opt/airflow/src')
            try:
                from core.database import get_unused_tweets as pg_get_tweets
                pg_tweets = pg_get_tweets(limit)
                result = [(tweet_id, link) for tweet_id, link in pg_tweets]
                logger.info(f"Fetched {len(result)} tweets from PostgreSQL")
            except Exception as e:
                logger.error(f"PostgreSQL fallback failed: {e}")
        
        return result
    except Exception as e:
        logger.error(f"get_unused_tweets error: {e}")
        return []

def mark_tweet_as_used(tweet_id):
    logger.info(f"Marking tweet {tweet_id} used")
    try:
        ts = datetime.now().isoformat()
        
        # Update MongoDB
        mongo_result = db.tweets.update_one(
            {"tweet_id": tweet_id},
            {"$set": {"used": True, "used_time": ts}}
        )
        
        # Update PostgreSQL if MongoDB didn't find the record
        if mongo_result.matched_count == 0:
            sys.path.append('/opt/airflow/src')
            try:
                from core.database import mark_tweet_as_used as pg_mark_tweet
                pg_mark_tweet(tweet_id)
                logger.info(f"Tweet {tweet_id} marked as used in PostgreSQL")
            except Exception as e:
                logger.error(f"PostgreSQL tweet update failed: {e}")
        else:
            logger.info(f"Tweet {tweet_id} marked as used in MongoDB")
            
    except Exception as e:
        logger.error(f"mark_tweet_as_used error: {e}")

def get_unused_messages(limit):
    logger.info(f"Fetching up to {limit} unused messages")
    try:
        messages = db.messages.find({"used": False}).sort("created_at", -1).limit(limit)
        result = [(message['message_id'], message['content']) for message in messages]
        logger.info(f"Fetched {len(result)} messages from MongoDB")
        
        # If no messages in MongoDB, try PostgreSQL fallback
        if not result:
            logger.info("No messages in MongoDB, checking PostgreSQL...")
            sys.path.append('/opt/airflow/src')
            try:
                from core.database import get_unused_messages as pg_get_messages
                pg_messages = pg_get_messages(limit=limit)
                result = [(msg_id, content) for msg_id, content, user_id in pg_messages]
                logger.info(f"Fetched {len(result)} messages from PostgreSQL")
            except Exception as e:
                logger.error(f"PostgreSQL fallback failed: {e}")
        
        return result
    except Exception as e:
        logger.error(f"get_unused_messages error: {e}")
        return []

def mark_message_as_used(message_id):
    logger.info(f"Marking message {message_id} used")
    try:
        ts = datetime.now().isoformat()
        
        # Update MongoDB
        mongo_result = db.messages.update_one(
            {"message_id": message_id},
            {"$set": {"used": True, "used_time": ts}}
        )
        
        # Update PostgreSQL if MongoDB didn't find the record
        if mongo_result.matched_count == 0:
            sys.path.append('/opt/airflow/src')
            try:
                from core.database import mark_message_as_used as pg_mark_message
                pg_mark_message(message_id)
                logger.info(f"Message {message_id} marked as used in PostgreSQL")
            except Exception as e:
                logger.error(f"PostgreSQL message update failed: {e}")
        else:
            logger.info(f"Message {message_id} marked as used in MongoDB")
            
    except Exception as e:
        logger.error(f"mark_message_as_used error: {e}")

def log_workflow_generation(workflow_name, tweet_id, message_id):
    try:
        db.workflow_stats.insert_one({
            "workflow_name": workflow_name,
            "tweet_id": tweet_id,
            "message_id": message_id,
            "date": datetime.now().date().isoformat(),
            "hour": datetime.now().hour,
            "created_at": datetime.now().isoformat()
        })
        logger.info(f"Logged workflow generation for {workflow_name}")
    except Exception as e:
        logger.error(f"Error logging workflow generation: {e}")

def get_workflow_stats():
    try:
        today = datetime.now().date().isoformat()
        current_hour = datetime.now().hour
        daily_count = db.workflow_stats.count_documents({"date": today})
        hourly_count = db.workflow_stats.count_documents({"date": today, "hour": current_hour})
        return {
            "daily_workflows": daily_count,
            "hourly_workflows": hourly_count
        }
    except Exception as e:
        logger.error(f"Error getting workflow stats: {e}")
        return {"daily_workflows": 0, "hourly_workflows": 0}

def generate_press_key_blocks(sentence, base_item_id):
    logger.info(f"Generating press-key blocks for: {sentence[:30]}...")
    words = re.findall(r'\b\w+\b|[^\w\s]', sentence)
    blocks = []
    for i, w in enumerate(words):
        blocks.append({
            "id": "press-key",
            "itemId": f"{base_item_id}_{i}",
            "data": {
                "disableBlock": False,
                "keys": w,
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
        if i < len(words) - 1 and not re.match(r'^[^\w\s]+$', w):
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

def update_json_with_content(input_file, name, tweet_url, messages):
    logger.info(f"Updating JSON for workflow '{name}'")
    
    if not os.path.exists(input_file):
        logger.error(f"Template file not found: {input_file}")
        return False
    
    try:
        with open(input_file) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in template file: {e}")
        return False

    workflow_id = str(uuid.uuid4())
    data['id'] = workflow_id

    nodes = data.get('drawflow', {}).get('nodes', [])
    blockgroups = [n for n in nodes if n.get('type') == 'BlockGroup']

    for idx, node in enumerate(blockgroups):
        for blk in node.get('data', {}).get('blocks', []):
            if blk.get('id') == 'new-tab':
                blk['data']['url'] = tweet_url

        msg = messages[idx][1] if idx < len(messages) else "I can help with your assignments; payment after completion."
        new_blocks = []
        for blk in node['data']['blocks']:
            if blk.get('id') == 'press-key' and blk['data'].get('keys') == 'MESSAGE_PLACEHOLDER':
                new_blocks.extend(generate_press_key_blocks(msg, f"{name}_{idx}"))
            else:
                new_blocks.append(blk)
        node['data']['blocks'] = new_blocks

    data['name'] = name

    # Store in MongoDB
    try:
        db.workflows.insert_one({
            "workflow_id": workflow_id,
            "name": name,
            "content": data,
            "tweet_id": messages[0][0] if messages else None,
            "message_id": messages[0][0] if messages else None,
            "created_at": datetime.now().isoformat()
        })
        logger.info(f"Successfully saved workflow {workflow_id} to MongoDB")
        return True
    except Exception as e:
        logger.error(f"Failed to save workflow to MongoDB: {e}")
        return False

def generate_single_workflow(name, input_file, tweet, message):
    tweet_id, tweet_url = tweet
    msg_id, msg_content = message

    success = update_json_with_content(
        input_file, name, tweet_url, [(msg_id, msg_content)]
    )
    if success:
        if tweet_id:
            mark_tweet_as_used(tweet_id)
        if msg_id:
            mark_message_as_used(msg_id)
        log_workflow_generation(name, tweet_id, msg_id)
    return success

def generate_automa_workflows():
    if not WORKFLOW_GENERATION_ENABLED:
        logger.warning("Workflow generation disabled")
        return 0, 0, 0

    # Ensure template file exists
    template_file = ensure_template_file_exists()
    logger.info(f"Using template file: {template_file}")

    stats = get_workflow_stats()
    daily = stats.get('daily_workflows', 0)
    hourly = stats.get('hourly_workflows', 0)
    avail = min(MAX_WORKFLOWS_PER_DAY - daily, MAX_WORKFLOWS_PER_HOUR - hourly)
    
    if avail <= 0:
        logger.info(f"No slots available - Daily: {daily}/{MAX_WORKFLOWS_PER_DAY}, Hourly: {hourly}/{MAX_WORKFLOWS_PER_HOUR}")
        return 0, 0, 0

    logger.info(f"Available workflow slots: {avail}")

    tweets = get_unused_tweets(avail)
    messages = get_unused_messages(avail)

    # Fill with defaults if needed
    tweets += [(None, "https://twitter.com")] * max(0, avail - len(tweets))
    messages += [(None, "I can help with your assignments; payment after completion.")] * max(0, avail - len(messages))

    names = ['one', 'two', 'three', 'four', 'five', 'six']
    success = 0

    for i in range(avail):
        try:
            workflow_name = names[i % len(names)]
            logger.info(f"Generating workflow {i+1}/{avail}: {workflow_name}")
            
            if generate_single_workflow(workflow_name, template_file, tweets[i], messages[i]):
                success += 1
                logger.info(f"Successfully generated workflow: {workflow_name}")
            else:
                logger.error(f"Failed to generate workflow: {workflow_name}")
                
        except Exception as e:
            logger.error(f"Failed to generate workflow {i}: {str(e)}")
            continue

    return avail, success, len(messages)

def run_task():
    logger.info("Starting workflow generation task")
    total, success, used = generate_automa_workflows()
    logger.info(f"Workflow generation completed: {success}/{total} workflows generated using {used} messages")
    
    # Don't fail if some workflows succeed
    if success == 0 and total > 0:
        raise Exception(f"Failed to generate any workflows out of {total} attempts")
    
    return f"Generated {success}/{total} workflows successfully"

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 6, 27, 3, 5),
    'retries': 2,  # Reduced retries
    'retry_delay': timedelta(minutes=5),  # Add delay between retries
    'retry_exponential_backoff': True,
}

dag = DAG(
    'automa_workflow_generation',
    default_args=default_args,
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    description="Generate Automa workflows by filling in tweets + messages"
)

generate = PythonOperator(
    task_id='generate_automa_workflows',
    python_callable=run_task,
    dag=dag
)