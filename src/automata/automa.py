# automa_workflow.py
import json
import os
import logging
import re
from datetime import datetime
import uuid
from dotenv import load_dotenv
from pymongo import MongoClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('automa_workflow.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")

# MongoDB connection
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin")
client = MongoClient(MONGODB_URI)
db = client['messages_db']

# Get workflow limits
MAX_WORKFLOWS_PER_DAY = int(os.getenv("MAX_WORKFLOWS_PER_DAY", "6"))
MAX_WORKFLOWS_PER_HOUR = int(os.getenv("MAX_WORKFLOWS_PER_HOUR", "2"))
WORKFLOW_GENERATION_ENABLED = os.getenv("WORKFLOW_GENERATION_ENABLED", "true").lower() == "true"

def get_unused_tweets(limit):
    """Fetch unused tweets from MongoDB"""
    logger.info(f"Attempting to fetch {limit} unused tweets from MongoDB")
    try:
        tweets = db.tweets.find({"used": False}).sort("scraped_time", -1).limit(limit)
        result = [(tweet['tweet_id'], tweet['link']) for tweet in tweets]
        logger.info(f"Successfully retrieved {len(result)} unused tweets from MongoDB")
        return result
    except Exception as e:
        logger.error(f"Error retrieving tweets from MongoDB: {e}")
        return []

def mark_tweet_as_used(tweet_id):
    """Mark a tweet as used in MongoDB"""
    logger.info(f"Marking tweet {tweet_id} as used")
    timestamp = datetime.now().isoformat()
    try:
        db.tweets.update_one(
            {"tweet_id": tweet_id},
            {"$set": {"used": True, "used_time": timestamp}}
        )
        logger.info(f"Tweet {tweet_id} marked as used successfully at {timestamp}")
    except Exception as e:
        logger.error(f"Error marking tweet as used: {e}")

def get_unused_messages(limit):
    """Fetch unused messages from MongoDB"""
    logger.info(f"Attempting to fetch {limit} unused messages from MongoDB")
    try:
        messages = db.messages.find({"used": False}).sort("created_at", -1).limit(limit)
        result = [(message['message_id'], message['content']) for message in messages]
        logger.info(f"Successfully retrieved {len(result)} unused messages from MongoDB")
        return result
    except Exception as e:
        logger.error(f"Error retrieving messages from MongoDB: {e}")
        return []

def mark_message_as_used(message_id):
    """Mark a message as used in MongoDB"""
    logger.info(f"Marking message {message_id} as used")
    timestamp = datetime.now().isoformat()
    try:
        db.messages.update_one(
            {"message_id": message_id},
            {"$set": {"used": True, "used_time": timestamp}}
        )
        logger.info(f"Message {message_id} marked as used successfully at {timestamp}")
    except Exception as e:
        logger.error(f"Error marking message as used: {e}")

def log_workflow_generation(workflow_name, tweet_id, message_id):
    """Log workflow generation to MongoDB"""
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
    """Get workflow generation stats from MongoDB"""
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
    """Generate press-key blocks based on words in a sentence."""
    logger.info(f"Generating press-key blocks for sentence: '{sentence[:50]}...' with base_item_id: {base_item_id}")
    try:
        if not sentence:
            logger.warning("Empty sentence provided for press-key block generation")
            return []
        
        words = re.findall(r'\b\w+\b|[^\w\s]', sentence)
        blocks = []
        
        for i, word in enumerate(words):
            block = {
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
                    "settings": {
                        "blockTimeout": 0,
                        "debugMode": False
                    }
                },
                "id": "press-key",
                "itemId": f"{base_item_id}_{i}"
            }
            blocks.append(block)
            
            if i < len(words) - 1 and not re.match(r'^[^\w\s]+$', word) and not re.match(r'^[^\w\s]+$', words[i+1]):
                space_block = {
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
                        "settings": {
                            "blockTimeout": 0,
                            "debugMode": False
                        }
                    },
                    "id": "press-key",
                    "itemId": f"{base_item_id}_{i}_space"
                }
                blocks.append(space_block)
        
        logger.info(f"Generated {len(blocks)} press-key blocks for {len(words)} words")
        return blocks
    except Exception as e:
        logger.error(f"Error generating press-key blocks: {e}")
        return []

def update_json_with_content(input_file, workflow_name, tweet_url, message_list):
    """Update JSON content with URL and press-key blocks, store in MongoDB"""
    logger.info(f"Updating JSON for workflow: {workflow_name}")
    
    try:
        with open(input_file, 'r') as file:
            data = json.load(file)
        logger.info(f"Successfully loaded input file: {input_file}")

        workflow_id = str(uuid.uuid4())
        data['id'] = workflow_id
        logger.info(f"Set workflow ID to: {workflow_id}")

        block_groups = [node for node in data['drawflow']['nodes'] if node['type'] == 'BlockGroup']
        num_block_groups = len(block_groups)
        logger.info(f"Found {num_block_groups} BlockGroups in the JSON")

        if num_block_groups == 0:
            logger.warning("No BlockGroups found in the JSON file")

        for idx, block_group in enumerate(block_groups):
            logger.info(f"Processing BlockGroup {idx + 1}/{num_block_groups}")
            
            if 'data' not in block_group or 'blocks' not in block_group['data']:
                logger.error(f"Invalid BlockGroup structure at index {idx}")
                continue
            
            blocks = block_group['data']['blocks']
            new_blocks = []

            url_updated = False
            for block in blocks:
                if block.get('id') == 'new-tab':
                    block['data']['url'] = tweet_url
                    logger.info(f"Updated URL to: {tweet_url}")
                    url_updated = True
                    
            if not url_updated:
                logger.warning("No new-tab block found for URL update")

            if idx < len(message_list):
                message_id, message_content = message_list[idx]
                logger.info(f"Using message {idx + 1}: '{message_content[:50]}...'")
            else:
                message_content = "I can help with your assignments; payment after completion."
                logger.warning(f"Using default message for BlockGroup {idx}")

            press_key_blocks_found = 0
            for block in blocks:
                if block.get('id') == 'press-key':
                    press_key_blocks_found += 1
                    keys_value = block.get('data', {}).get('keys', '')
                    if keys_value == 'MESSAGE_PLACEHOLDER':
                        base_item_id = f"press-key_{workflow_name}_{idx}"
                        new_blocks.extend(generate_press_key_blocks(message_content, base_item_id))
                        logger.info(f"Replaced press-key block with placeholder in BlockGroup {idx}")
                    else:
                        new_blocks.append(block)
                        logger.info(f"Kept press-key block with keys='{keys_value}' unchanged")
                else:
                    new_blocks.append(block)

            logger.info(f"Found and processed {press_key_blocks_found} press-key blocks in BlockGroup {idx}")
            block_group['data']['blocks'] = new_blocks

        data["name"] = workflow_name

        # Store in MongoDB
        db.workflows.insert_one({
            "workflow_id": workflow_id,
            "name": workflow_name,
            "content": data,
            "tweet_id": message_list[0][0] if message_list else None,
            "message_id": message_list[0][0] if message_list else None,
            "created_at": datetime.now().isoformat()
        })
        logger.info(f"Successfully saved workflow {workflow_id} to MongoDB")
        return True

    except Exception as e:
        logger.error(f"Error updating JSON with content: {e}")
        return False

def generate_single_workflow(workflow_name, input_file, tweet, message):
    """Generate a single workflow with given resources"""
    try:
        tweet_id, tweet_url = tweet
        message_id, message_content = message
        
        if update_json_with_content(input_file, workflow_name, tweet_url, [(message_id, message_content)]):
            if tweet_id is not None:
                mark_tweet_as_used(tweet_id)
            if message_id is not None:
                mark_message_as_used(message_id)
            log_workflow_generation(workflow_name, tweet_id, message_id)
            return True
        return False
    except Exception as e:
        logger.error(f"Error generating single workflow: {e}")
        return False

def generate_automa_workflows():
    """Main function to generate workflows with rate limiting"""
    if not WORKFLOW_GENERATION_ENABLED:
        logger.warning("Workflow generation is disabled via environment variable")
        return 0, 0, 0
    
    logger.info("Starting automa workflow generation")
    logger.info(f"Workflow limits: {MAX_WORKFLOWS_PER_DAY}/day, {MAX_WORKFLOWS_PER_HOUR}/hour")
    
    try:
        stats = get_workflow_stats()
        daily_count = stats.get('daily_workflows', 0)
        hourly_count = stats.get('hourly_workflows', 0)
        logger.info(f"Current workflow counts - Today: {daily_count}, This hour: {hourly_count}")
        
        daily_available = max(0, MAX_WORKFLOWS_PER_DAY - daily_count)
        hourly_available = max(0, MAX_WORKFLOWS_PER_HOUR - hourly_count)
        workflows_to_generate = min(daily_available, hourly_available)
        
        if workflows_to_generate <= 0:
            logger.warning("Workflow generation limit reached. Skipping generation.")
            return 0, 0, 0
        
        logger.info(f"Can generate up to {workflows_to_generate} workflows")
        
        input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deck.automa.json')
        logger.info(f"Input template file: {input_file}")
        
        if not os.path.exists(input_file):
            logger.error(f"Template file not found: {input_file}")
            return 0, 0, 0
        
        tweets = get_unused_tweets(workflows_to_generate)
        logger.info(f"Retrieved {len(tweets)} unused tweets from database")
        
        if len(tweets) < workflows_to_generate:
            tweets_to_pad = workflows_to_generate - len(tweets)
            tweets += [(None, "https://twitter.com")] * tweets_to_pad
            logger.warning(f"Padded with {tweets_to_pad} default URLs")

        messages = get_unused_messages(workflows_to_generate)
        logger.info(f"Retrieved {len(messages)} unused messages from database")
        
        if len(messages) < workflows_to_generate:
            messages_to_pad = workflows_to_generate - len(messages)
            default_msg = (None, "I can help with your assignments; payment after completion.")
            messages += [default_msg] * messages_to_pad
            logger.warning(f"Padded with {messages_to_pad} default messages")

        workflow_names = ['one', 'two', 'three', 'four', 'five', 'six']
        success_count = 0
        
        for i in range(workflows_to_generate):
            workflow_name = workflow_names[i % len(workflow_names)]
            logger.info(f"Generating workflow {i + 1}/{workflows_to_generate}: {workflow_name}")
            
            if generate_single_workflow(
                workflow_name, 
                input_file, 
                tweets[i], 
                messages[i]
            ):
                success_count += 1
                logger.info(f"Successfully generated workflow: {workflow_name}")
            else:
                logger.error(f"Failed to generate workflow: {workflow_name}")
        
        logger.info(f"Successfully completed {success_count}/{workflows_to_generate} workflow generation")
        return workflows_to_generate, success_count, len(messages)
        
    except Exception as e:
        logger.error(f"Critical error in generate_automa_workflows: {e}")
        raise

if __name__ == "__main__":
    try:
        logger.info("Starting automa workflow generation script")
        total_workflows, success_count, messages_used = generate_automa_workflows()
        success_message = f"Generated {success_count}/{total_workflows} workflows using {messages_used} messages"
        logger.info(success_message)
        print(success_message)
    except Exception as e:
        error_message = f"Script execution failed: {e}"
        logger.error(error_message)
        print(f"ERROR: {error_message}")
        exit(1)