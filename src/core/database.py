import os
import random
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse

# Get database URL from environment variable
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://airflow:airflow@postgres:5432/messages")

def get_db_connection():
    """Create a connection to the PostgreSQL database"""
    try:
        # Check if DATABASE_URL is a DSN string (e.g., "host=...") or a URL
        if DATABASE_URL.startswith("host="):
            # DSN string format
            conn = psycopg2.connect(DATABASE_URL)
        else:
            # URL format (e.g., postgresql+psycopg2:// or postgres://)
            parsed_url = urlparse(DATABASE_URL.replace("postgresql+psycopg2://", "postgres://"))
            conn_params = {
                "host": parsed_url.hostname,
                "port": parsed_url.port or 5432,
                "dbname": parsed_url.path.lstrip("/"),
                "user": parsed_url.username,
                "password": parsed_url.password
            }
            conn = psycopg2.connect(**conn_params)
        return conn
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        return None

def create_tables():
    """Create all required tables if they don't exist"""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        
        # Create messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                message_id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                used_time TIMESTAMP
            )
        ''')
        
        # Create tweets_scraped table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tweets_scraped (
                tweet_id TEXT PRIMARY KEY,
                link TEXT NOT NULL,
                scraped_time TIMESTAMP NOT NULL,
                user_id INTEGER NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                used_time TIMESTAMP,
                follow BOOLEAN DEFAULT FALSE,
                message BOOLEAN DEFAULT FALSE,
                reply BOOLEAN DEFAULT FALSE,
                retweet BOOLEAN DEFAULT FALSE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id SERIAL PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_tweets (
                id SERIAL PRIMARY KEY,
                tweet_id TEXT NOT NULL UNIQUE,
                processed_time TIMESTAMP NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workflow_generation_log (
                id SERIAL PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                generated_time TIMESTAMP NOT NULL,
                tweet_id TEXT,
                message_id INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workflow_limits (
                id SERIAL PRIMARY KEY,
                limit_type TEXT NOT NULL UNIQUE,
                max_count INTEGER NOT NULL,
                current_count INTEGER DEFAULT 0,
                reset_time TIMESTAMP NOT NULL
            )
        ''')
        
        # Initialize workflow limits if not exists
        cursor.execute('''
            INSERT INTO workflow_limits (limit_type, max_count, reset_time)
            VALUES 
                ('daily', 6, NOW() + INTERVAL '1 day'),
                ('hourly', 2, NOW() + INTERVAL '1 hour')
            ON CONFLICT (limit_type) DO NOTHING
        ''')
        
        conn.commit()
        print(f"✅ Database tables created at: {DATABASE_URL}")
        return True
    except Exception as e:
        print(f"❌ Error creating database tables: {e}")
        return False
    finally:
        conn.close()

def ensure_database():
    """Ensure database tables are created"""
    return create_tables()

def save_messages_to_db(messages: List[str]):
    """Save messages to the database with random user_id distribution"""
    if not ensure_database():
        raise Exception("Failed to ensure database exists")
        
    conn = get_db_connection()
    if not conn:
        raise Exception("Failed to connect to database")
        
    cursor = conn.cursor()
    try:
        user_ids = [1, 2, 3]
        inserted_count = 0
        
        for message in messages:
            user_id = random.choice(user_ids)
            cursor.execute('''
                INSERT INTO messages (content, user_id, used)
                VALUES (%s, %s, %s)
            ''', (message, user_id, False))
            inserted_count += 1
        
        conn.commit()
        print(f"✅ {inserted_count} messages saved to database")
        
        cursor.execute('''
            SELECT user_id, COUNT(*) as count 
            FROM messages 
            WHERE message_id IN (
                SELECT message_id FROM messages 
                ORDER BY message_id DESC LIMIT %s
            )
            GROUP BY user_id 
            ORDER BY user_id
        ''', (inserted_count,))
        
        distribution = cursor.fetchall()
        print("📊 Message distribution:")
        for user_id, count in distribution:
            print(f"  👤 User {user_id}: {count} messages")
            
    except Exception as e:
        conn.rollback()
        print(f"❌ Error saving messages: {e}")
        raise
    finally:
        conn.close()

def get_unused_messages(user_id: Optional[int] = None, limit: Optional[int] = None) -> List[Tuple[int, str, int]]:
    """Get unused messages from the database"""
    conn = get_db_connection()
    if not conn:
        return []
        
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = "SELECT message_id, content, user_id FROM messages WHERE used = FALSE"
        params = []
        
        if user_id is not None:
            query += " AND user_id = %s"
            params.append(user_id)
        
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        
        cursor.execute(query, params)
        return [(row['message_id'], row['content'], row['user_id']) for row in cursor.fetchall()]
        
    except Exception as e:
        print(f"❌ Error retrieving messages: {e}")
        return []
    finally:
        conn.close()

def mark_message_as_used(message_id: int):
    """Mark a message as used with timestamp"""
    conn = get_db_connection()
    if not conn:
        return
        
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    
    try:
        cursor.execute('''
            UPDATE messages 
            SET used = TRUE, used_time = %s
            WHERE message_id = %s
        ''', (timestamp, message_id))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            print(f"📩 Message {message_id} marked as used at {timestamp}")
        else:
            print(f"⚠️ Message {message_id} not found")
            
    except Exception as e:
        print(f"❌ Error marking message as used: {e}")
    finally:
        conn.close()

def save_tweets_to_db(valid_entries: List[Tuple[str, str]]):
    """Save scraped tweets to DB with actual Twitter IDs and URLs"""
    if not ensure_database():
        raise Exception("Failed to ensure database exists")
        
    conn = get_db_connection()
    if not conn:
        raise Exception("Failed to connect to database")
        
    cursor = conn.cursor()
    try:
        user_ids = [1, 2, 3]
        now = datetime.now().isoformat()
        inserted_count = 0
        
        for tweet_id, url in valid_entries:
            user_id = random.choice(user_ids)
            try:
                cursor.execute('''
                    INSERT INTO tweets_scraped (
                        tweet_id, link, scraped_time, user_id
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (tweet_id) DO NOTHING
                ''', (tweet_id, url, now, user_id))
                
                if cursor.rowcount > 0:
                    inserted_count += 1
            except psycopg2.IntegrityError:
                continue  # Skip duplicates

        conn.commit()
        print(f"✅ {inserted_count} tweets saved to database")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error saving tweets: {e}")
        raise
    finally:
        conn.close()

def get_unused_tweets(limit: int) -> List[Tuple[str, str]]:
    """Fetch unused tweets from the PostgreSQL database"""
    print(f"Attempting to fetch {limit} unused tweets from database")
    
    conn = get_db_connection()
    if not conn:
        return []
        
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            SELECT tweet_id, link 
            FROM tweets_scraped 
            WHERE used = FALSE 
            ORDER BY scraped_time DESC 
            LIMIT %s
        """, (limit,))
        tweets = cursor.fetchall()
        
        print(f"Successfully retrieved {len(tweets)} unused tweets from database")
        return [(row['tweet_id'], row['link']) for row in tweets]
        
    except Exception as e:
        print(f"❌ Error retrieving tweets: {e}")
        return []
    finally:
        conn.close()

def mark_tweet_as_used(tweet_id: str):
    """Mark a tweet as used with timestamp"""
    conn = get_db_connection()
    if not conn:
        return
        
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    
    try:
        cursor.execute('''
            UPDATE tweets_scraped 
            SET used = TRUE, used_time = %s
            WHERE tweet_id = %s
        ''', (timestamp, tweet_id))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            print(f"🐦 Tweet {tweet_id} marked as used at {timestamp}")
        else:
            print(f"⚠️ Tweet {tweet_id} not found")
            
    except Exception as e:
        print(f"❌ Error marking tweet as used: {e}")
    finally:
        conn.close()

def log_workflow_run(workflow_name: str, run_id: str, success: bool):
    """Insert a record of the workflow run and its status"""
    conn = get_db_connection()
    if not conn:
        return
        
    cursor = conn.cursor()
    status = 'success' if success else 'failure'
    timestamp = datetime.utcnow().isoformat()
    
    try:
        cursor.execute('''
            INSERT INTO workflow_runs (workflow_name, run_id, status, timestamp)
            VALUES (%s, %s, %s, %s)
        ''', (workflow_name, run_id, status, timestamp))
        conn.commit()
        print(f"📋 Logged workflow run: {workflow_name} ({status})")
    except Exception as e:
        print(f"❌ Error logging workflow run: {e}")
    finally:
        conn.close()

def log_workflow_generation(workflow_name: str, tweet_id: Optional[str] = None, message_id: Optional[int] = None):
    """Log workflow generation in database"""
    conn = get_db_connection()
    if not conn:
        return
        
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    
    try:
        cursor.execute('''
            INSERT INTO workflow_generation_log (workflow_name, generated_time, tweet_id, message_id)
            VALUES (%s, %s, %s, %s)
        ''', (workflow_name, timestamp, tweet_id, message_id))
        conn.commit()
        print(f"📝 Logged workflow generation: {workflow_name}")
    except Exception as e:
        print(f"❌ Error logging workflow generation: {e}")
    finally:
        conn.close()

def can_generate_workflow() -> bool:
    """Check if we can generate a new workflow based on limits"""
    conn = get_db_connection()
    if not conn:
        return False
        
    cursor = conn.cursor()
    now = datetime.now()
    
    try:
        cursor.execute('''
            SELECT current_count, reset_time 
            FROM workflow_limits 
            WHERE limit_type = 'daily'
        ''')
        daily_row = cursor.fetchone()
        
        if daily_row and datetime.fromisoformat(daily_row[1]) < now:
            reset_time = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            cursor.execute('''
                UPDATE workflow_limits 
                SET current_count = 0, reset_time = %s
                WHERE limit_type = 'daily'
            ''', (reset_time.isoformat(),))
            daily_count = 0
        else:
            daily_count = daily_row[0] if daily_row else 0
            
        cursor.execute('''
            SELECT current_count, reset_time 
            FROM workflow_limits 
            WHERE limit_type = 'hourly'
        ''')
        hourly_row = cursor.fetchone()
        
        if hourly_row and datetime.fromisoformat(hourly_row[1]) < now:
            reset_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            cursor.execute('''
                UPDATE workflow_limits 
                SET current_count = 0, reset_time = %s
                WHERE limit_type = 'hourly'
            ''', (reset_time.isoformat(),))
            hourly_count = 0
        else:
            hourly_count = hourly_row[0] if hourly_row else 0
            
        cursor.execute('''
            SELECT max_count 
            FROM workflow_limits 
            WHERE limit_type = 'daily'
        ''')
        max_daily = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT max_count 
            FROM workflow_limits 
            WHERE limit_type = 'hourly'
        ''')
        max_hourly = cursor.fetchone()[0]
        
        can_generate = daily_count < max_daily and hourly_count < max_hourly
        
        if can_generate:
            cursor.execute('''
                UPDATE workflow_limits 
                SET current_count = current_count + 1
                WHERE limit_type IN ('daily', 'hourly')
            ''')
            conn.commit()
            print(f"🔄 Workflow counts updated: Daily {daily_count+1}/{max_daily}, Hourly {hourly_count+1}/{max_hourly}")
        else:
            print(f"⛔ Workflow limit reached: Daily {daily_count}/{max_daily}, Hourly {hourly_count}/{max_hourly}")
            
        return can_generate
        
    except Exception as e:
        print(f"❌ Error checking workflow limits: {e}")
        return False
    finally:
        conn.close()

def get_message_stats() -> Dict[str, Any]:
    """Get statistics about messages in the database"""
    conn = get_db_connection()
    if not conn:
        return {}
        
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT COUNT(*) FROM messages")
        total = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM messages WHERE used = TRUE")
        used = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT user_id, 
                   COUNT(*) as total,
                   SUM(CASE WHEN used = TRUE THEN 1 ELSE 0 END) as used_count
            FROM messages 
            GROUP BY user_id 
            ORDER BY user_id
        ''')
        user_stats = cursor.fetchall()
        
        return {
            'total_messages': total,
            'used_messages': used,
            'unused_messages': total - used,
            'user_stats': [(row['user_id'], row['total'], row['used_count']) for row in user_stats]
        }
    except Exception as e:
        print(f"❌ Error getting message stats: {e}")
        return {}
    finally:
        conn.close()

def get_tweet_stats() -> Dict[str, Any]:
    """Get statistics about tweets in the database"""
    conn = get_db_connection()
    if not conn:
        return {}
        
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT COUNT(*) FROM tweets_scraped")
        total = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM tweets_scraped WHERE used = TRUE")
        used = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT user_id, 
                   COUNT(*) as total,
                   SUM(CASE WHEN used = TRUE THEN 1 ELSE 0 END) as used_count
            FROM tweets_scraped 
            GROUP BY user_id 
            ORDER BY user_id
        ''')
        user_stats = cursor.fetchall()
        
        return {
            'total_tweets': total,
            'used_tweets': used,
            'unused_tweets': total - used,
            'user_stats': [(row['user_id'], row['total'], row['used_count']) for row in user_stats]
        }
    except Exception as e:
        print(f"❌ Error getting tweet stats: {e}")
        return {}
    finally:
        conn.close()

def get_workflow_stats() -> Dict[str, Any]:
    """Get workflow statistics"""
    conn = get_db_connection()
    if not conn:
        return {}
        
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT COUNT(*) FROM workflow_runs")
        total_runs = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM workflow_runs WHERE status = 'success'")
        success_runs = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM workflow_generation_log")
        total_generated = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT current_count, reset_time 
            FROM workflow_limits 
            WHERE limit_type = 'daily'
        ''')
        daily = cursor.fetchone()
        
        cursor.execute('''
            SELECT current_count, reset_time 
            FROM workflow_limits 
            WHERE limit_type = 'hourly'
        ''')
        hourly = cursor.fetchone()
        
        return {
            'total_workflow_runs': total_runs,
            'successful_runs': success_runs,
            'failed_runs': total_runs - success_runs,
            'total_generated': total_generated,
            'daily_workflows': daily['current_count'] if daily else 0,
            'daily_reset': daily['reset_time'] if daily else None,
            'hourly_workflows': hourly['current_count'] if hourly else 0,
            'hourly_reset': hourly['reset_time'] if hourly else None
        }
    except Exception as e:
        print(f"❌ Error getting workflow stats: {e}")
        return {}
    finally:
        conn.close()

def get_database_info() -> Dict[str, Any]:
    """Get comprehensive database information"""
    conn = get_db_connection()
    if not conn:
        return {
            'path': DATABASE_URL,
            'size': 0,
            'modified_time': None,
            'tables': [],
            'table_counts': {},
            'message_stats': {},
            'tweet_stats': {},
            'workflow_stats': {}
        }
        
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get table list
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row['table_name'] for row in cursor.fetchall()]
        
        # Table row counts
        table_counts = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            table_counts[table] = cursor.fetchone()['count']
        
        return {
            'path': DATABASE_URL,
            'size': 0,  # Note: Size calculation requires additional logic for PostgreSQL
            'modified_time': None,  # Not directly available in PostgreSQL
            'tables': tables,
            'table_counts': table_counts,
            'message_stats': get_message_stats(),
            'tweet_stats': get_tweet_stats(),
            'workflow_stats': get_workflow_stats()
        }
    except Exception as e:
        print(f"❌ Error getting database info: {e}")
        return {}
    finally:
        conn.close()

def print_database_info():
    """Print comprehensive database information"""
    info = get_database_info()
    
    if not info:
        print("❌ No database information available")
        return
        
    print("\n" + "="*60)
    print("📊 DATABASE INFORMATION")
    print("="*60)
    print(f"📂 Path: {info['path']}")
    print(f"📏 Size: Not available")
    print(f"⏱️ Last Modified: Not available")
    
    print("\n" + "-"*60)
    print("🗃️ TABLES")
    print("-"*60)
    for table in info['tables']:
        print(f"  ▸ {table}: {info['table_counts'].get(table, 0)} rows")
    
    msg_stats = info.get('message_stats', {})
    if msg_stats:
        print("\n" + "-"*60)
        print("💬 MESSAGE STATS")
        print("-"*60)
        print(f"  Total Messages: {msg_stats.get('total_messages', 0)}")
        print(f"  Used Messages: {msg_stats.get('used_messages', 0)}")
        print(f"  Unused Messages: {msg_stats.get('unused_messages', 0)}")
        
        user_stats = msg_stats.get('user_stats', [])
        if user_stats:
            print("\n  By User:")
            for user_id, total, used_count in user_stats:
                unused = total - used_count
                print(f"    👤 User {user_id}: {total} total ({used_count} used, {unused} unused)")
    
    tweet_stats = info.get('tweet_stats', {})
    if tweet_stats:
        print("\n" + "-"*60)
        print("🐦 TWEET STATS")
        print("-"*60)
        print(f"  Total Tweets: {tweet_stats.get('total_tweets', 0)}")
        print(f"  Used Tweets: {tweet_stats.get('used_tweets', 0)}")
        print(f"  Unused Tweets: {tweet_stats.get('unused_tweets', 0)}")
        
        user_stats = tweet_stats.get('user_stats', [])
        if user_stats:
            print("\n  By User:")
            for user_id, total, used_count in user_stats:
                unused = total - used_count
                print(f"    👤 User {user_id}: {total} total ({used_count} used, {unused} unused)")
    
    wf_stats = info.get('workflow_stats', {})
    if wf_stats:
        print("\n" + "-"*60)
        print("⚙️ WORKFLOW STATS")
        print("-"*60)
        print(f"  Total Runs: {wf_stats.get('total_workflow_runs', 0)}")
        print(f"  Successful Runs: {wf_stats.get('successful_runs', 0)}")
        print(f"  Failed Runs: {wf_stats.get('failed_runs', 0)}")
        print(f"  Total Generated: {wf_stats.get('total_generated', 0)}")
        print(f"  Daily Workflows: {wf_stats.get('daily_workflows', 0)} (Reset: {wf_stats.get('daily_reset', 'N/A')})")
        print(f"  Hourly Workflows: {wf_stats.get('hourly_workflows', 0)} (Reset: {wf_stats.get('hourly_reset', 'N/A')})")
    
    print("="*60 + "\n")

if __name__ == "__main__":
    print_database_info()