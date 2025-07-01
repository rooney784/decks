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

# Get the absolute path of the current directory
current_dir = os.path.abspath(os.path.dirname(__file__))

# Add pathස

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

# MongoDB connection
mongo_client = MongoClient(MONGODB_URI)
mongo_db = mongo_client['messages_db']

def get_db_connection():
    """Create a connection to the PostgreSQL database"""
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
        st.error(f"❌ Error connecting to database: {str(e)}")
        return None

# Initialize session state
if 'current_action' not in st.session_state:
    st.session_state['current_action'] = None
if 'selected_account' not in st.session_state:
    st.session_state['selected_account'] = None
if 'confirm_delete' not in st.session_state:
    st.session_state['confirm_delete'] = None
if 'log_messages' not in st.session_state:
    st.session_state['log_messages'] = []
if 'selected_workflow' not in st.session_state:
    st.session_state['selected_workflow'] = None

def log_message(message, level="info"):
    """Log message to session state and print to console"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    st.session_state['log_messages'].append((level, log_entry))
    print(log_entry)

def display_logs():
    """Display log messages in the UI"""
    if st.session_state['log_messages']:
        with st.expander("📝 Process Logs", expanded=True):
            for level, message in st.session_state['log_messages']:
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

@st.cache_data
def fetch_workflows():
    """Fetch workflows from MongoDB with caching"""
    try:
        workflows = mongo_db.workflows.find().sort("created_at", -1)
        return list(workflows)
    except Exception as e:
        st.error(f"❌ Error fetching workflows: {str(e)}")
        log_message(f"Error fetching workflows: {str(e)}", "error")
        return []

def show_workflows():
    """Display workflows stored in MongoDB with clear data functionality"""
    st.subheader("📋 Workflows")
    with st.expander("ℹ️ About this feature"):
        st.write("View all workflows stored in the database, including their name, associated tweet and message, and creation date. Use the 'Clear Data' button to delete all workflows (requires confirmation).")
    
    # Fetch workflows using cached function
    workflow_list = fetch_workflows()
    
    if workflow_list:
        # Prepare data for display
        workflow_data = [
            {
                "Workflow ID": wf["workflow_id"],
                "Name": wf["name"],
                "Tweet ID": wf.get("tweet_id", "N/A"),
                "Message ID": wf.get("message_id", "N/A"),
                "Created At": wf["created_at"],
            }
            for wf in workflow_list
        ]
        
        # Display workflows in a table without key parameter
        st.dataframe(
            pd.DataFrame(workflow_data),
            hide_index=True,
            use_container_width=True
        )
        
        # Workflow selection dropdown with stable state
        selected_workflow = st.selectbox(
            "Select Workflow to View Details",
            options=[wf["workflow_id"] for wf in workflow_list],
            format_func=lambda x: next(wf["name"] for wf in workflow_list if wf["workflow_id"] == x),
            key="workflow_select",
            index=workflow_list.index(next((wf for wf in workflow_list if wf["workflow_id"] == st.session_state['selected_workflow']), workflow_list[0])) if st.session_state['selected_workflow'] in [wf["workflow_id"] for wf in workflow_list] else 0
        )
        
        # Update session state
        if selected_workflow != st.session_state['selected_workflow']:
            st.session_state['selected_workflow'] = selected_workflow
        
        # Display workflow JSON
        if selected_workflow:
            with st.expander("📄 Workflow JSON", expanded=False):
                workflow = next(wf for wf in workflow_list if wf["workflow_id"] == selected_workflow)
                st.json(workflow["content"])
        
        # Clear Data button with confirmation
        st.write("### 🗑️ Clear Workflow Data")
        if st.button("Clear All Workflows", type="secondary", key="clear_workflows"):
            st.session_state['confirm_delete'] = True
        
        if st.session_state['confirm_delete']:
            st.warning("⚠️ Are you sure you want to delete all workflows? This action cannot be undone.")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Confirm Delete", type="primary"):
                    try:
                        result = mongo_db.workflows.delete_many({})
                        deleted_count = result.deleted_count
                        st.session_state['confirm_delete'] = None
                        log_message(f"Successfully deleted {deleted_count} workflows from MongoDB", "success")
                        st.success(f"✅ Deleted {deleted_count} workflows")
                        # Clear cache to refresh table
                        fetch_workflows.clear()
                        st.rerun()
                    except Exception as e:
                        log_message(f"Error deleting workflows: {str(e)}", "error")
                        st.error(f"❌ Error deleting workflows: {str(e)}")
            with col2:
                if st.button("Cancel"):
                    st.session_state['confirm_delete'] = None
                    log_message("Clear workflows action cancelled", "info")
                    st.rerun()
        
        log_message("Successfully retrieved workflows from MongoDB", "success")
    else:
        st.info("No workflows found in the database.")
        log_message("No workflows found in MongoDB", "warning")
    
    display_logs()

st.title("📝 Assignment Helper Pro")
st.caption("AI-powered Twitter assistant for assignment help seekers")

# ==============================
# SIDEBAR - ACCOUNT MANAGEMENT
# ==============================
with st.sidebar:
    st.header("🔐 Account Management")
    
    account_options = ["@assignment_helper", "@study_assistant", "@homework_pro"]
    selected_account = st.selectbox("Select Account", account_options, key="account_select")
    st.session_state['selected_account'] = selected_account
    
    st.divider()
    
    st.header("⚙️ Actions")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📝 Create Messages", use_container_width=True):
            st.session_state['current_action'] = 'create_messages'
            clear_logs()
        if st.button("🤖 Create Automa", use_container_width=True):
            st.session_state['current_action'] = 'automa'
            clear_logs()
    with col2:
        if st.button("📊 Check Stats", use_container_width=True):
            st.session_state['current_action'] = 'statistics'
            clear_logs()
        if st.button("⚡ Run Scrape", use_container_width=True):
            st.session_state['current_action'] = 'scrape'
            clear_logs()
    
    st.divider()
    
    if st.button("📁 View Data", use_container_width=True):
        st.session_state['current_action'] = 'view_data'
        clear_logs()
    
    if st.button("📋 View Workflows", use_container_width=True):
        st.session_state['current_action'] = 'view_workflows'
        clear_logs()
    
    st.divider()
    
    st.header("👀 Monitoring")
    monitoring_col1, monitoring_col2 = st.columns(2)
    with monitoring_col1:
        if st.button("🧠 Model", use_container_width=True):
            st.session_state['current_action'] = 'monitor_model'
            clear_logs()
    with monitoring_col2:
        if st.button("📬 Notifications", use_container_width=True):
            st.session_state['current_action'] = 'monitor_notifications'
            clear_logs()
    
    if st.button("🎯 Accuracy", use_container_width=True):
        st.session_state['current_action'] = 'monitor_accuracy'
        clear_logs()
    
    st.divider()
    
    st.header("🌐 Browser Actions")
    if st.button("🔗 Open Links", use_container_width=True, help="Open unprocessed tweet links in your browser"):
        st.session_state['current_action'] = 'open_links'
        clear_logs()

# ==============================
# MAIN CONTENT AREA
# ==============================
if st.session_state['selected_account']:
    st.subheader(f"👤 Active Account: {st.session_state['selected_account']}")
    
    stats_col1, stats_col2, stats_col3 = st.columns(3)
    with stats_col1:
        st.metric("📤 Posts Sent", "142", "+12 today")
    with stats_col2:
        st.metric("🔄 Retweets", "87", "+5 today")
    with stats_col3:
        st.metric("💬 Messages", "203")
    
    st.divider()

# ==============================
# ACTION-SPECIFIC CONTENT
# ==============================
if st.session_state['current_action'] == 'create_messages':
    st.subheader("💬 Message Generator")
    st.write("Click the button below to generate and store new assignment help messages")
    
    if st.button("✨ Generate Messages", type="primary"):
        with st.status("Creating messages...", expanded=True) as status:
            try:
                log_message("🔌 Connecting to API...")
                
                result = subprocess.run(
                    ["python3", "src/create_messages/create_messages.py"],
                    capture_output=True,
                    text=True
                )
                
                log_message(result.stdout)
                
                if result.returncode == 0:
                    status.update(label="✅ Messages generated successfully!", state="complete")
                    log_message("Messages saved to database!", "success")
                    
                    # Show generated messages
                    latest_messages = get_unused_messages(limit=10)
                    if latest_messages:
                        with st.expander("📋 Generated Messages Preview"):
                            for idx, (message_id, content) in enumerate(latest_messages, 1):
                                st.write(f"{idx}. {content}")
                    
                    st.balloons()
                else:
                    status.update(label="❌ Error generating messages", state="error")
                    log_message(f"Error generating messages: {result.stderr}", "error")
                
            except Exception as e:
                status.update(label="❌ Error in message generation", state="error")
                log_message(f"An error occurred: {str(e)}", "error")
        
        display_logs()

elif st.session_state['current_action'] == 'automa':
    st.subheader("🤖 Workflow Automation")
    with st.expander("ℹ️ About this feature"):
        st.write("Generate automated workflows that are stored in MongoDB. Each workflow uses a tweet and a message.")
    
    if st.button("🛠️ Generate Workflows", type="primary"):
        with st.status("Building workflows...", expanded=True) as status:
            try:
                log_message("📂 Loading template...")
                
                # Generate the workflows
                total_workflows, success_count, messages_used = generate_automa_workflows()
                
                status.update(label=f"✅ {success_count}/{total_workflows} workflows created!", state="complete")
                log_message(f"Successfully generated {success_count} workflows using {messages_used} messages!", "success")
                st.balloons()
                
                # Show generated workflows
                workflows = mongo_db.workflows.find().sort("created_at", -1).limit(success_count)
                if workflows:
                    with st.expander("📂 Generated Workflows"):
                        for wf in workflows:
                            st.write(f"- {wf['name']} (ID: {wf['workflow_id']}) created at {wf['created_at']}")
            
            except Exception as e:
                status.update(label="❌ Error generating workflows", state="error")
                log_message(f"An error occurred: {str(e)}", "error")
        
        display_logs()

elif st.session_state['current_action'] == 'scrape':
    st.subheader("🔍 Twitter Scraper")
    with st.expander("ℹ️ About this feature"):
        st.write("Scrape a predefined Twitter-like page for links and store them in the database.")
        st.write(f"**Target URL:** `{os.getenv('URL_TO_SCRAPE')}`")
        st.info("Note: This may take 15-30 seconds as it loads the page dynamically")

    if st.button("🔍 Scrape Tweets", type="primary", key="scrape_button"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        result_container = st.container()
        
        log_message("🚀 Starting scraping process...")
        progress_bar.progress(5)
        time.sleep(0.5)
        
        try:
            status_text.info("🔄 Initializing browser...")
            progress_bar.progress(10)
            time.sleep(0.5)
            
            raw_links, log_messages, screenshot_path = scrape_links()
            
            for msg in log_messages:
                if "❌" in msg:
                    log_message(msg.replace("❌", "").strip(), "error")
                elif "✅" in msg:
                    log_message(msg.replace("✅", "").strip(), "success")
                else:
                    log_message(msg)
            
            progress_bar.progress(40)
            status_text.info("Processing links...")
            time.sleep(1)
            
            if raw_links:
                valid_entries = [(str(uuid.uuid4()), link) for link in set(raw_links)]
                log_message(f"Total {len(valid_entries)} unique URLs", "success")
                
                progress_bar.progress(70)
                status_text.info("Saving to database...")
                time.sleep(1)
                
                if valid_entries:
                    save_tweets_to_db(valid_entries)
                    log_message(f"Saved {len(valid_entries)} links to database", "success")
                    
                    with result_container:
                        with st.expander("📝 Raw Links (First 20)"):
                            st.dataframe(pd.DataFrame({'Raw Links': raw_links[:20]}), 
                                        hide_index=True, height=400)
                        
                        if screenshot_path and os.path.exists(screenshot_path):
                            with st.expander("📷 Page Screenshot"):
                                st.image(Image.open(screenshot_path), 
                                        caption="Scraped Page", 
                                        use_column_width=True)
                        
                        with st.expander("📈 Database Stats"):
                            try:
                                conn = get_db_connection()
                                if conn:
                                    with conn.cursor() as cursor:
                                        cursor.execute("SELECT COUNT(*) FROM tweets_scraped")
                                        tweet_count = cursor.fetchone()[0]
                                        cursor.execute("SELECT * FROM tweets_scraped ORDER BY scraped_time DESC LIMIT 10")
                                        recent_tweets = pd.DataFrame(
                                            cursor.fetchall(),
                                            columns=[desc[0] for desc in cursor.description]
                                        )
                                    conn.close()
                                    
                                    st.metric("Total Links in Database", tweet_count)
                                    st.write("Recent Additions:")
                                    st.dataframe(recent_tweets)
                                else:
                                    st.error("❌ Failed to connect to database")
                            except Exception as e:
                                st.error(f"❌ Error fetching DB stats: {str(e)}")
                else:
                    log_message("⚠️ No links found during scraping!", "warning")
            else:
                log_message("⚠️ No links found during scraping!", "warning")
                
        except Exception as e:
            log_message(f"⚠️ Processing error: {str(e)}", "error")
            st.exception(e)
        
        finally:
            progress_bar.progress(100)
            status_text.success("✅ Scraping completed!")
            time.sleep(1)
            st.balloons()
        
        display_logs()

elif st.session_state['current_action'] == 'open_links':
    st.subheader("🌐 Open Tweet Links")
    with st.expander("ℹ️ About this feature", expanded=True):
        st.write("""
        **A Chrome browser window will open on your host machine!**
        - Chrome browser will open with all links in separate tabs
        - The browser will remain open for your inspection
        - Close browser manually when you're done
        """)
        st.write(f"**Batch Size:** `{os.getenv('OPEN_LINKS', 2)}` links at a time")
        st.warning("🔐 Ensure you have an X11 server running on your host machine")
        st.info("📡 On Windows: Use VcXsrv\nOn Mac: Use XQuartz\nOn Linux: X11 should already be installed")
        
    if st.button("🚀 Open Links Now", type="primary", key="open_links_button", use_container_width=True):
        with st.status("Processing links...", expanded=True) as status:
            try:
                log_message("🔍 Fetching unprocessed tweets...")
                time.sleep(0.5)
                
                success, opened_urls, _ = open_links_in_browser()
                
                if success:
                    status.update(label="✅ Links opened in browser!", state="complete")
                    log_message(f"Opened {len(opened_urls)} links in browser", "success")
                    
                    if opened_urls:
                        with st.expander("📝 Opened Links"):
                            for url in opened_urls:
                                st.markdown(f"- [{url}]({url})")
                    
                    st.success("✅ A Chrome window should now be visible on your host machine!")
                    st.info("ℹ Keep browser open until manually closed")
                else:
                    status.update(label="⚠️ Some issues occurred", state="complete")
                    log_message("⚠️ Some issues occurred", "warning")
                
            except Exception as e:
                status.update(label="❌ Error opening links", state="error")
                log_message(f"Error opening links: {str(e)}", "error")
                st.exception(e)
            
        display_logs()

elif st.session_state['current_action'] == 'statistics':
    st.subheader("📈 Message Statistics")
    
    try:
        stats = get_message_stats()
        if stats:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Messages", stats['total_messages'])
            col2.metric("Used Messages", stats['used_messages'])
            col3.metric("Unused Messages", stats['unused_messages'])
            
            st.divider()
            st.subheader("Distribution by User")
            
            for user_id, total, used in stats['user_stats']:
                unused = total - used
                st.write(f"### User {user_id}")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total", total)
                col2.metric("Used", used)
                col3.metric("Unused", unused)
                
                usage_percent = (used / total) * 100 if total > 0 else 0
                st.progress(int(usage_percent))
                st.caption(f"Usage: {used}/{total} ({usage_percent:.1f}%)")
                
                log_message("Successfully retrieved message statistics", "success")
        else:
            log_message("⚠️ Could not retrieve message statistics", "warning")
    except Exception as e:
        log_message(f"⚠️ Error getting message stats: {str(e)}", "error")
    
    display_logs()

elif st.session_state['current_action'] == 'view_data':
    show_database_viewer()

elif st.session_state['current_action'] == 'view_workflows':
    show_workflows()

elif st.session_state['current_action'] == 'monitor_model':
    st.subheader("🧠 Model Performance Monitoring")
    
    st.write("### 📈 Key Metrics")
    col1, col2, col3 = st.columns(3)
    col1.metric("Response Quality", "8.7/10", "+0.2 from last week")
    col2.metric("Relevance Score", "92%", "3% improvement")
    col3.metric("Engagement Rate", "74.2%", "-2% from last month")
    
    st.divider()
    
    st.write("### 🔍 Response Analysis")
    with st.expander("Top Performing Messages"):
        st.markdown("1. I can help with your assignment! Send me the details. (95%)")
        st.markdown("2. Professional assignment help available. DM me (92%)")
    with st.expander("Messages Needing Improvement"):
        st.markdown("- Homework help - cheap rates! (42%)")

elif st.session_state['current_action'] == 'monitor_notifications':
    st.subheader("📬 Notification Center")
    st.markdown("### 🔔 Notify")
    notifications = [
        {"time": "2023-10-10 14:30", "type": "success", "content": "✅ Generated 30 new messages"},
        {"time": "2023-10-10 12:15", "type": "info", "content": "📊 Daily stats report ready"},
    ]
    for note in notifications:
        with st.container(border=True):
            st.markdown(f"**{note['time']}** ({note['type']})")
            st.write(note['content'])

elif st.session_state['current_action'] == 'monitor_accuracy':
    st.subheader("🎯 Accuracy Monitoring")
    
    st.write("### 📈 Performance Metrics")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Correct Responses", "89%", "2% improvement")
    with col2:
        st.metric("User Satisfaction", "4.5★", "0.3★ increase")
    
    st.divider()
    
    st.write("### 🔍 Accuracy Trends")
    accuracy_data = pd.DataFrame({
        'Week': ['May 1', 'May 8', 'May 15', 'May 22'],
        'Accuracy': [82, 85, 84, 87],
        'Satisfaction': [3.9, 4.0, 4.1, 4.3]
    })
    st.line_chart(accuracy_data.set_index('Week'))

# ==============================
# DEFAULT DASHBOARD VIEW
# ==============================
else:
    st.subheader("📊 System Dashboard")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Accounts", "3")
    col2.metric("Messages Available", "142")
    col3.metric("Active Workflows", "18")
    
    st.divider()
    
    st.write("### ⏱️ Recent Activity")
    activity = pd.DataFrame({
        'Time': ['2023-10-10 14:30', '2023-10-10 12:15', '2023-10-10 09:45'],
        'Account': ['@assignment_helper', '@study_assistant', '@homework_pro'],
        'Action': ['Generated messages', 'Posted workflow', 'Responded to query'],
        'Status': ['✅ Completed', '🔄 Running', '✅ Completed']
    })
    st.dataframe(activity, hide_index=True)

    st.divider()
    st.write("### 🟢 System Status")
    status_col1, status_col2, status_col3 = st.columns(3)
    with status_col1:
        st.info("**API Connections**\n\nAll services operational")
    with status_col2:
        st.info("**Database**\n\n24.7 MB used\nLast backup: 6h ago")
    with status_col3:
        st.info("**Scheduler**\n\nNext run in 32m")

# Footer
st.divider()
st.caption("© 2025 Assignment Helper Pro | AI-powered Twitter assistant")