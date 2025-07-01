import os
import time
import sqlite3
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/messages.db")
BATCH_SIZE = int(os.getenv("OPEN_LINKS_BATCH_SIZE", 10))

def get_unprocessed_tweets():
    """Retrieve unprocessed tweets from the database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT st.tweet_id, st.url 
            FROM tweets_scraped st
            LEFT JOIN processed_tweets pt ON st.tweet_id = pt.tweet_id
            WHERE pt.tweet_id IS NULL
            LIMIT ?
        ''', (BATCH_SIZE,))
        
        unprocessed_tweets = cursor.fetchall()
        return unprocessed_tweets
    finally:
        conn.close()

def mark_as_processed(tweet_id):
    """Mark a tweet as processed in the database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO processed_tweets (tweet_id, processed_time)
            VALUES (?, ?)
        ''', (tweet_id, datetime.now()))
        conn.commit()
    finally:
        conn.close()

def open_links_in_browser():
    """Open unprocessed tweet links in visible browser"""
    # Configure Chrome options for visible mode
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1280,1024")
    
    # Disable headless mode
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--remote-debugging-port=9222")
    
    driver = None
    success = True
    opened_urls = []
    
    try:
        # Initialize WebDriver with visible Chrome
        driver = webdriver.Chrome(
            service=Service('/usr/local/bin/chromedriver'),
            options=chrome_options
        )
        
        # Get unprocessed tweets
        unprocessed_tweets = get_unprocessed_tweets()
        
        if not unprocessed_tweets:
            logging.info("No unprocessed tweets found")
            return True, [], ""
        
        # Open each URL in a new tab
        for tweet_id, url in unprocessed_tweets:
            try:
                driver.execute_script(f"window.open('{url}', '_blank');")
                opened_urls.append(url)
                mark_as_processed(tweet_id)
                time.sleep(1)  # Brief pause between tabs
            except Exception as e:
                logging.error(f"Error opening {url}: {str(e)}")
                success = False
        
        # Switch to first tab
        driver.switch_to.window(driver.window_handles[0])
        
        return success, opened_urls, ""
        
    except Exception as e:
        logging.error(f"Browser error: {str(e)}")
        return False, [], ""
    
    finally:
        # IMPORTANT: Don't quit the driver so Chrome stays open
        # The browser will remain visible until manually closed
        pass