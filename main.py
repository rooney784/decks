import streamlit as st
import pandas as pd
import os
import sys
import subprocess
from dotenv import load_dotenv
import time
from datetime import datetime, timedelta
import psycopg2
from urllib.parse import urlparse
import uuid
from PIL import Image
from pymongo import MongoClient
import threading
from functools import lru_cache

# Configure page for better performance
st.set_page_config(
    page_title="Assignment Helper Pro",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Get the absolute path of the current directory
current_dir = os.path.abspath(os.path.dirname(__file__))

# Add path
sys.path.append(os.path.join(current_dir, 'src'))

# Import your modules
from src.automata.automa import generate_automa_workflows
from src.core.database import save_messages_to_db, get_message_stats, save_tweets_to_db, get_unused_messages
from src.scraper.scraper import scrape_links
from src.open_links.open_links import open_links_in_browser
from src.database_viewer.database_viewer import show_database_viewer

# Load environment variables
load_dotenv()

# Database connection configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://airflow:airflow@postgres:5432/messages")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin")

# Initialize session state ONCE
def init_session_state():
    """Initialize session state variables only if they don't exist"""
    defaults = {
        'current_action': None,
        'selected_account': '@assignment_helper',
        'confirm_delete': None,
        'log_messages': [],
        'selected_workflow': None,
        'db_connection': None,
        'mongo_client': None,
        'last_stats_update': None,
        'cached_stats': None,
        'last_workflow_update': None,
        'cached_workflows': None
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

@st.cache_resource
def get_mongo_client():
    """Create and cache MongoDB connection"""
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        # Test connection
        client.admin.command('ping')
        return client
    except Exception as e:
        st.error(f"❌ Error connecting to MongoDB: {str(e)}")
        return None

@st.cache_resource
def get_db_connection():
    """Create and cache PostgreSQL database connection"""
    try:
        if DATABASE_URL.startswith("host="):
            conn = psycopg2.connect(DATABASE_URL)
        else:
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
        st.error(f"❌ Error connecting to PostgreSQL: {str(e)}")
        return None

def log_message(message, level="info"):
    """Log message to session state efficiently"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    
    # Limit log size to prevent memory issues
    if len(st.session_state['log_messages']) > 50:
        st.session_state['log_messages'] = st.session_state['log_messages'][-25:]
    
    st.session_state['log_messages'].append((level, log_entry))

def display_logs():
    """Display log messages efficiently"""
    if st.session_state['log_messages']:
        with st.expander("📝 Process Logs", expanded=False):
            # Only show last 10 messages to improve performance
            recent_logs = st.session_state['log_messages'][-10:]
            for level, message in recent_logs:
                if level == "error":
                    st.error(message, icon="🚨")
                elif level == "warning":
                    st.warning(message, icon="⚠️")
                elif level == "success":
                    st.success(message, icon="✅")
                else:
                    st.info(message, icon="ℹ️")

def clear_logs():
    """Clear log messages"""
    st.session_state['log_messages'] = []

@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_workflows_cached():
    """Fetch workflows from MongoDB with aggressive caching"""
    try:
        mongo_client = get_mongo_client()
        if not mongo_client:
            return []
        
        mongo_db = mongo_client['messages_db']
        workflows = list(mongo_db.workflows.find().sort("created_at", -1).limit(100))  # Limit results
        return workflows
    except Exception as e:
        st.error(f"❌ Error fetching workflows: {str(e)}")
        return []

@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_message_stats_cached():
    """Get message statistics with caching"""
    try:
        return get_message_stats()
    except Exception as e:
        st.error(f"❌ Error getting stats: {str(e)}")
        return None

def show_workflows():
    """Display workflows with optimized performance"""
    st.subheader("📋 Workflows")
    
    with st.expander("ℹ️ About this feature"):
        st.write("View workflows stored in the database. Data is cached for 5 minutes for better performance.")
    
    # Use cached function
    workflow_list = fetch_workflows_cached()
    
    if not workflow_list:
        st.info("No workflows found in the database.")
        return
    
    # Prepare data more efficiently
    workflow_data = []
    for wf in workflow_list:
        workflow_data.append({
            "Workflow ID": wf["workflow_id"],
            "Name": wf["name"],
            "Tweet ID": wf.get("tweet_id", "N/A"),
            "Message ID": wf.get("message_id", "N/A"),
            "Created At": wf["created_at"].strftime("%Y-%m-%d %H:%M") if isinstance(wf["created_at"], datetime) else str(wf["created_at"]),
        })
    
    # Display workflows table
    df = pd.DataFrame(workflow_data)
    st.dataframe(df, hide_index=True, use_container_width=True, height=400)
    
    # Workflow selection with better state management
    workflow_options = [wf["workflow_id"] for wf in workflow_list]
    workflow_names = {wf["workflow_id"]: wf["name"] for wf in workflow_list}
    
    selected_workflow = st.selectbox(
        "Select Workflow to View Details",
        options=workflow_options,
        format_func=lambda x: workflow_names.get(x, x),
        key="workflow_select_optimized"
    )
    
    # Display workflow JSON only when selected
    if selected_workflow:
        with st.expander("📄 Workflow JSON", expanded=False):
            workflow = next((wf for wf in workflow_list if wf["workflow_id"] == selected_workflow), None)
            if workflow:
                st.json(workflow["content"])
    
    # Clear Data section
    st.write("### 🗑️ Clear Workflow Data")
    if st.button("Clear All Workflows", type="secondary", key="clear_workflows_opt"):
        st.session_state['confirm_delete'] = True
    
    if st.session_state.get('confirm_delete'):
        st.warning("⚠️ Are you sure you want to delete all workflows? This action cannot be undone.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Confirm Delete", type="primary", key="confirm_delete_opt"):
                try:
                    mongo_client = get_mongo_client()
                    if mongo_client:
                        mongo_db = mongo_client['messages_db']
                        result = mongo_db.workflows.delete_many({})
                        deleted_count = result.deleted_count
                        st.session_state['confirm_delete'] = False
                        
                        # Clear cache
                        fetch_workflows_cached.clear()
                        
                        log_message(f"Successfully deleted {deleted_count} workflows", "success")
                        st.success(f"✅ Deleted {deleted_count} workflows")
                        st.rerun()
                except Exception as e:
                    log_message(f"Error deleting workflows: {str(e)}", "error")
        with col2:
            if st.button("Cancel", key="cancel_delete_opt"):
                st.session_state['confirm_delete'] = False
                st.rerun()

# Main UI with optimized layout
st.title("📝 Assignment Helper Pro")
st.caption("AI-powered Twitter assistant for assignment help seekers")

# ==============================
# SIDEBAR - OPTIMIZED
# ==============================
with st.sidebar:
    st.header("🔐 Account Management")
    
    account_options = ["@assignment_helper", "@study_assistant", "@homework_pro"]
    selected_account = st.selectbox(
        "Select Account", 
        account_options, 
        key="account_select",
        index=account_options.index(st.session_state.get('selected_account', account_options[0]))
    )
    st.session_state['selected_account'] = selected_account
    
    st.divider()
    
    st.header("⚙️ Actions")
    
    # Use columns for better layout
    action_col1, action_col2 = st.columns(2)
    
    with action_col1:
        if st.button("📝 Messages", use_container_width=True, key="btn_messages"):
            st.session_state['current_action'] = 'create_messages'
            clear_logs()
        
        if st.button("📊 Stats", use_container_width=True, key="btn_stats"):
            st.session_state['current_action'] = 'statistics'
            clear_logs()
    
    with action_col2:
        if st.button("🤖 Automa", use_container_width=True, key="btn_automa"):
            st.session_state['current_action'] = 'automa'
            clear_logs()
        
        if st.button("⚡ Scrape", use_container_width=True, key="btn_scrape"):
            st.session_state['current_action'] = 'scrape'
            clear_logs()
    
    st.divider()
    
    # Data and workflow buttons
    if st.button("📁 View Data", use_container_width=True, key="btn_data"):
        st.session_state['current_action'] = 'view_data'
        clear_logs()
    
    if st.button("📋 Workflows", use_container_width=True, key="btn_workflows"):
        st.session_state['current_action'] = 'view_workflows'
        clear_logs()
    
    st.divider()
    
    # Monitoring section - simplified
    st.header("👀 Quick Actions")
    if st.button("🔗 Open Links", use_container_width=True, key="btn_links"):
        st.session_state['current_action'] = 'open_links'
        clear_logs()

# ==============================
# MAIN CONTENT - OPTIMIZED
# ==============================
if st.session_state['selected_account']:
    st.subheader(f"👤 Active: {st.session_state['selected_account']}")
    
    # Show cached stats
    stats = get_message_stats_cached()
    if stats:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Messages", stats.get('total_messages', 0))
        col2.metric("Used Messages", stats.get('used_messages', 0))
        col3.metric("Unused Messages", stats.get('unused_messages', 0))
    
    st.divider()

# ==============================
# ACTION HANDLERS - OPTIMIZED
# ==============================
current_action = st.session_state.get('current_action')

if current_action == 'create_messages':
    st.subheader("💬 Message Generator")
    st.write("Generate and store new assignment help messages")
    
    if st.button("✨ Generate Messages", type="primary", key="gen_messages"):
        with st.status("Creating messages...", expanded=True) as status:
            try:
                log_message("🔌 Connecting to API...")
                
                result = subprocess.run(
                    ["python3", "src/create_messages/create_messages.py"],
                    capture_output=True,
                    text=True,
                    timeout=60  # Add timeout
                )
                
                if result.returncode == 0:
                    status.update(label="✅ Messages generated successfully!", state="complete")
                    log_message("Messages saved to database!", "success")
                    
                    # Clear stats cache to refresh
                    get_message_stats_cached.clear()
                    
                    st.balloons()
                else:
                    status.update(label="❌ Error generating messages", state="error")
                    log_message(f"Error: {result.stderr}", "error")
                
            except subprocess.TimeoutExpired:
                log_message("Operation timed out after 60 seconds", "error")
            except Exception as e:
                log_message(f"Error: {str(e)}", "error")
    
    display_logs()

elif current_action == 'automa':
    st.subheader("🤖 Workflow Automation")
    st.write("Generate automated workflows stored in MongoDB")
    
    if st.button("🛠️ Generate Workflows", type="primary", key="gen_workflows"):
        with st.status("Building workflows...", expanded=True) as status:
            try:
                log_message("📂 Loading template...")
                
                total_workflows, success_count, messages_used = generate_automa_workflows()
                
                status.update(label=f"✅ {success_count}/{total_workflows} workflows created!", state="complete")
                log_message(f"Generated {success_count} workflows using {messages_used} messages!", "success")
                
                # Clear workflow cache
                fetch_workflows_cached.clear()
                
                st.balloons()
            
            except Exception as e:
                status.update(label="❌ Error generating workflows", state="error")
                log_message(f"Error: {str(e)}", "error")
    
    display_logs()

elif current_action == 'scrape':
    st.subheader("🔍 Twitter Scraper")
    with st.expander("ℹ️ About this feature"):
        st.write("Scrape Twitter-like page for links and store in database.")
        st.write(f"**Target URL:** `{os.getenv('URL_TO_SCRAPE', 'Not set')}`")

    if st.button("🔍 Start Scraping", type="primary", key="start_scrape"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            log_message("🚀 Starting scraping process...")
            progress_bar.progress(10)
            
            status_text.info("🔄 Initializing browser...")
            raw_links, log_messages, screenshot_path = scrape_links()
            
            progress_bar.progress(60)
            
            if raw_links:
                valid_entries = [(str(uuid.uuid4()), link) for link in set(raw_links)]
                log_message(f"Found {len(valid_entries)} unique URLs", "success")
                
                progress_bar.progress(80)
                save_tweets_to_db(valid_entries)
                log_message(f"Saved {len(valid_entries)} links", "success")
                
                # Show results in expandable sections
                with st.expander("📝 Scraped Links (First 20)", expanded=False):
                    if raw_links:
                        st.dataframe(pd.DataFrame({'Links': raw_links[:20]}), height=300)
                
                if screenshot_path and os.path.exists(screenshot_path):
                    with st.expander("📷 Screenshot", expanded=False):
                        st.image(Image.open(screenshot_path), use_column_width=True)
            else:
                log_message("No links found", "warning")
            
            progress_bar.progress(100)
            status_text.success("✅ Scraping completed!")
            
        except Exception as e:
            log_message(f"Scraping error: {str(e)}", "error")
            st.error(f"❌ Error: {str(e)}")
    
    display_logs()

elif current_action == 'open_links':
    st.subheader("🌐 Open Tweet Links")
    with st.expander("ℹ️ About this feature"):
        st.write("Open unprocessed tweet links in Chrome browser")
        st.write(f"**Batch Size:** {os.getenv('OPEN_LINKS', 2)} links at a time")
        
    if st.button("🚀 Open Links", type="primary", key="open_tweet_links"):
        with st.status("Processing links...", expanded=True) as status:
            try:
                log_message("🔍 Fetching unprocessed tweets...")
                
                success, opened_urls, _ = open_links_in_browser()
                
                if success:
                    status.update(label="✅ Links opened in browser!", state="complete")
                    log_message(f"Opened {len(opened_urls)} links", "success")
                    
                    if opened_urls:
                        with st.expander("📝 Opened Links"):
                            for url in opened_urls:
                                st.markdown(f"- [{url}]({url})")
                else:
                    status.update(label="⚠️ Some issues occurred", state="complete")
                
            except Exception as e:
                status.update(label="❌ Error opening links", state="error")
                log_message(f"Error: {str(e)}", "error")
    
    display_logs()

elif current_action == 'statistics':
    st.subheader("📈 Message Statistics")
    
    stats = get_message_stats_cached()
    if stats:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Messages", stats['total_messages'])
        col2.metric("Used Messages", stats['used_messages'])
        col3.metric("Unused Messages", stats['unused_messages'])
        
        st.divider()
        
        if 'user_stats' in stats and stats['user_stats']:
            st.subheader("📊 User Distribution")
            
            for user_id, total, used in stats['user_stats']:
                unused = total - used
                usage_percent = (used / total) * 100 if total > 0 else 0
                
                with st.container():
                    st.write(f"**User {user_id}**")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Total", total)
                    col2.metric("Used", used)
                    col3.metric("Unused", unused)
                    st.progress(usage_percent / 100)
                    st.caption(f"Usage: {usage_percent:.1f}%")
    else:
        st.warning("Could not retrieve statistics")
    
    display_logs()

elif current_action == 'view_data':
    try:
        show_database_viewer()
    except Exception as e:
        st.error(f"Error loading database viewer: {str(e)}")
        log_message(f"Database viewer error: {str(e)}", "error")

elif current_action == 'view_workflows':
    show_workflows()

# ==============================
# DEFAULT DASHBOARD - SIMPLIFIED
# ==============================
else:
    st.subheader("📊 System Dashboard")
    
    # Quick stats
    col1, col2, col3 = st.columns(3)
    
    # Get cached stats for dashboard
    stats = get_message_stats_cached()
    if stats:
        col1.metric("Total Messages", stats.get('total_messages', 0))
        col2.metric("Unused Messages", stats.get('unused_messages', 0))
    else:
        col1.metric("Total Messages", "Loading...")
        col2.metric("Unused Messages", "Loading...")
    
    col3.metric("Active Accounts", len(["@assignment_helper", "@study_assistant", "@homework_pro"]))
    
    st.divider()
    
    # System status
    st.write("### 🟢 System Status")
    status_col1, status_col2 = st.columns(2)
    
    with status_col1:
        st.info("**Database Status**\n\n✅ PostgreSQL: Connected\n✅ MongoDB: Connected")
    
    with status_col2:
        st.info("**Recent Activity**\n\n📝 Messages: Active\n🤖 Workflows: Ready")

# Footer
st.divider()
st.caption("© 2025 Assignment Helper Pro | Optimized for Performance")