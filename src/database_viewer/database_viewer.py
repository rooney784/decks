import streamlit as st
import pandas as pd
import psycopg2
from urllib.parse import urlparse
from datetime import datetime, timedelta
import plotly.express as px
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database connection configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://airflow:airflow@postgres:5432/messages")

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

def show_database_viewer():
    """Main function to display the database viewer interface"""
    st.subheader("📊 Database Viewer")
    
    # Add refresh button
    col1, col2 = st.columns([3, 1])
    with col1:
        st.info("View and analyze your database contents")
    with col2:
        if st.button("🔄 Refresh Data", use_container_width=True, key="db_refresh"):
            st.rerun()
    
    try:
        conn = get_db_connection()
        if not conn:
            st.error("❌ Failed to connect to database")
            return
        with conn.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            tables = [table[0] for table in cursor.fetchall()]
        conn.close()
    except Exception as e:
        st.error(f"❌ Error accessing database: {str(e)}")
        tables = []
    
    if not tables:
        st.warning("⚠️ No tables found in the database")
        return
    
    tabs = st.tabs(tables)
    
    for i, table_name in enumerate(tables):
        with tabs[i]:
            row_count = get_table_row_count(table_name)
            schema = get_table_schema(table_name)
            
            st.subheader(f"Table: {table_name}")
            st.caption(f"📊 {row_count} rows | 💾 {len(schema)} columns")
            
            with st.expander("🔍 View Schema"):
                if schema:
                    schema_df = pd.DataFrame(
                        schema, 
                        columns=["column_name", "data_type", "is_nullable", "column_default"]
                    )
                    st.dataframe(
                        schema_df[['column_name', 'data_type', 'is_nullable']], 
                        hide_index=True,
                        column_config={
                            "column_name": "Column Name",
                            "data_type": "Data Type",
                            "is_nullable": "Nullable"
                        }
                    )
                else:
                    st.warning("⚠️ No schema information available")
            
            if row_count > 0:
                data_df = get_table_data(table_name)
                
                with st.expander("📈 Summary Statistics"):
                    if not data_df.empty:
                        try:
                            numeric_cols = data_df.select_dtypes(include=['number']).columns
                            if len(numeric_cols) > 0:
                                st.write("**Numeric Columns:**")
                                st.write(data_df[numeric_cols].describe())
                            
                            string_cols = data_df.select_dtypes(include=['object']).columns
                            if len(string_cols) > 0:
                                st.write("**Text Columns:**")
                                for col in string_cols:
                                    unique_count = data_df[col].nunique()
                                    st.write(f"- {col}: {unique_count} unique values")
                        except Exception as e:
                            st.warning(f"⚠️ Could not generate statistics: {str(e)}")
                
                st.subheader("Data Preview")
                st.dataframe(data_df, height=400, use_container_width=True)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.download_button(
                        label="📥 Download as CSV",
                        data=data_df.to_csv(index=False).encode('utf-8'),
                        file_name=f"{table_name}_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime='text/csv',
                        use_container_width=True,
                        key=f"download_{table_name}"
                    ):
                        st.success(f"✅ Downloaded {table_name}.csv")
                
                with col2:
                    if st.button("🗑️ Delete All Rows", type="secondary", 
                                 use_container_width=True, key=f"delete_{table_name}"):
                        if st.session_state.get('confirm_delete') == table_name:
                            try:
                                clear_table(table_name)
                                st.session_state['confirm_delete'] = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error deleting rows: {str(e)}")
                        else:
                            st.session_state['confirm_delete'] = table_name
                            st.warning(f"⚠️ Are you sure you want to delete all {row_count} rows? Click again to confirm.")
                
                if table_name == "messages":
                    show_message_actions()
                elif table_name == "tweets_scraped":
                    show_tweet_actions()
                elif table_name == "workflow_limits":
                    show_workflow_limit_actions()
                elif table_name == "workflow_generation_log":
                    show_workflow_generation_actions()
                elif table_name == "workflow_runs":
                    show_workflow_run_actions()
            else:
                st.info("ℹ️ No data available in this table")

def show_message_actions():
    st.subheader("📝 Message Actions")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔄 Reset All Messages to Unused", use_container_width=True):
            try:
                conn = get_db_connection()
                if conn:
                    with conn.cursor() as cursor:
                        cursor.execute("UPDATE messages SET used = FALSE, used_time = NULL")
                        conn.commit()
                    conn.close()
                    st.success("✅ All messages reset to unused status")
                    st.rerun()
                else:
                    st.error("❌ Failed to connect to database")
            except Exception as e:
                st.error(f"❌ Error resetting messages: {str(e)}")
    
    with col2:
        if st.button("📊 Show Usage Stats", use_container_width=True):
            try:
                conn = get_db_connection()
                if conn:
                    stats_df = pd.read_sql("""
                        SELECT 
                            user_id,
                            COUNT(*) as total_messages,
                            SUM(CASE WHEN used = TRUE THEN 1 ELSE 0 END) as used_messages,
                            SUM(CASE WHEN used = FALSE THEN 1 ELSE 0 END) as unused_messages
                        FROM messages 
                        GROUP BY user_id
                    """, conn)
                    conn.close()
                    
                    if not stats_df.empty:
                        st.dataframe(stats_df, use_container_width=True)
                        fig = px.pie(
                            stats_df, 
                            values='total_messages', 
                            names='user_id',
                            title='Message Distribution by User',
                            hole=0.3
                        )
                        st.plotly_chart(fig)
                    else:
                        st.info("ℹ️ No message statistics available")
                else:
                    st.error("❌ Failed to connect to database")
            except Exception as e:
                st.error(f"❌ Error getting stats: {str(e)}")

def show_tweet_actions():
    st.subheader("🐦 Tweet Actions")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔄 Reset All Tweets to Unused", use_container_width=True):
            try:
                conn = get_db_connection()
                if conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            UPDATE tweets_scraped 
                            SET used = FALSE, used_time = NULL,
                                follow = FALSE, message = FALSE, 
                                reply = FALSE, retweet = FALSE
                        """)
                        conn.commit()
                    conn.close()
                    st.success("✅ All tweets reset to unused status")
                    st.rerun()
                else:
                    st.error("❌ Failed to connect to database")
            except Exception as e:
                st.error(f"❌ Error resetting tweets: {str(e)}")
    
    with col2:
        if st.button("📊 Show Tweet Stats", use_container_width=True):
            try:
                conn = get_db_connection()
                if conn:
                    stats_df = pd.read_sql("""
                        SELECT 
                            user_id,
                            COUNT(*) as total_tweets,
                            SUM(CASE WHEN used = TRUE THEN 1 ELSE 0 END) as used_tweets,
                            SUM(CASE WHEN follow = TRUE THEN 1 ELSE 0 END) as followed,
                            SUM(CASE WHEN message = TRUE THEN 1 ELSE 0 END) as messaged,
                            SUM(CASE WHEN reply = TRUE THEN 1 ELSE 0 END) as replied,
                            SUM(CASE WHEN retweet = TRUE THEN 1 ELSE 0 END) as retweeted
                        FROM tweets_scraped 
                        GROUP BY user_id
                    """, conn)
                    conn.close()
                    
                    if not stats_df.empty:
                        st.dataframe(stats_df, use_container_width=True)
                        fig = px.bar(
                            stats_df, 
                            x='user_id', 
                            y=['followed', 'messaged', 'replied', 'retweeted'],
                            title='Tweet Engagement by User',
                            barmode='group',
                            labels={'value': 'Count', 'variable': 'Action'}
                        )
                        st.plotly_chart(fig)
                    else:
                        st.info("ℹ️ No tweet statistics available")
                else:
                    st.error("❌ Failed to connect to database")
            except Exception as e:
                st.error(f"❌ Error getting tweet stats: {str(e)}")

def show_workflow_limit_actions():
    st.subheader("⚙️ Workflow Limit Actions")
    if st.button("🔄 Reset Workflow Limits", use_container_width=True):
        try:
            conn = get_db_connection()
            if conn:
                with conn.cursor() as cursor:
                    daily_reset = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    cursor.execute("""
                        UPDATE workflow_limits 
                        SET current_count = 0, reset_time = %s
                        WHERE limit_type = 'daily'
                    """, (daily_reset.isoformat(),))
                    hourly_reset = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                    cursor.execute("""
                        UPDATE workflow_limits 
                        SET current_count = 0, reset_time = %s
                        WHERE limit_type = 'hourly'
                    """, (hourly_reset.isoformat(),))
                    conn.commit()
                conn.close()
                st.success("✅ Workflow limits reset successfully")
                st.rerun()
            else:
                st.error("❌ Failed to connect to database")
        except Exception as e:
            st.error(f"❌ Error resetting limits: {str(e)}")

def show_workflow_generation_actions():
    st.subheader("📝 Workflow Generation Actions")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 Show Generation Stats", use_container_width=True):
            try:
                conn = get_db_connection()
                if conn:
                    stats_df = pd.read_sql("""
                        SELECT 
                            workflow_name,
                            COUNT(*) as count,
                            TO_CHAR(generated_time, 'YYYY-MM-DD') as date
                        FROM workflow_generation_log 
                        GROUP BY workflow_name, date
                        ORDER BY date DESC
                    """, conn)
                    conn.close()
                    
                    if not stats_df.empty:
                        st.dataframe(stats_df, use_container_width=True)
                        fig = px.bar(
                            stats_df, 
                            x='date', 
                            y='count',
                            color='workflow_name',
                            title='Workflow Generation by Date',
                            labels={'count': 'Number of Workflows'}
                        )
                        st.plotly_chart(fig)
                    else:
                        st.info("ℹ️ No workflow generation data available")
                else:
                    st.error("❌ Failed to connect to database")
            except Exception as e:
                st.error(f"❌ Error getting generation stats: {str(e)}")

def show_workflow_run_actions():
    st.subheader("⚙️ Workflow Run Actions")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 Show Success Rate", use_container_width=True):
            try:
                conn = get_db_connection()
                if conn:
                    stats_df = pd.read_sql("""
                        SELECT 
                            workflow_name,
                            COUNT(*) as total_runs,
                            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_runs,
                            SUM(CASE WHEN status = 'failure' THEN 1 ELSE 0 END) as failure_runs
                        FROM workflow_runs 
                        GROUP BY workflow_name
                    """, conn)
                    conn.close()
                    
                    if not stats_df.empty:
                        stats_df['success_rate'] = (stats_df['success_runs'] / stats_df['total_runs']) * 100
                        st.dataframe(stats_df, use_container_width=True)
                        fig = px.bar(
                            stats_df, 
                            x='workflow_name', 
                            y=['success_runs', 'failure_runs'],
                            title='Workflow Run Success Rate',
                            barmode='group',
                            labels={'value': 'Count', 'variable': 'Status'}
                        )
                        st.plotly_chart(fig)
                    else:
                        st.info("ℹ️ No workflow run data available")
                else:
                    st.error("❌ Failed to connect to database")
            except Exception as e:
                st.error(f"❌ Error getting run stats: {str(e)}")

def get_table_data(table_name, limit=1000):
    try:
        conn = get_db_connection()
        if conn:
            query = f"SELECT * FROM {table_name} ORDER BY row_number() OVER () DESC LIMIT %s"
            df = pd.read_sql(query, conn, params=(limit,))
            conn.close()
            return df
        else:
            st.error("❌ Failed to connect to database")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Error reading table {table_name}: {str(e)}")
        return pd.DataFrame()

def get_table_schema(table_name):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_name = %s
                """, (table_name,))
                schema = cursor.fetchall()
            conn.close()
            return schema
        else:
            st.error("❌ Failed to connect to database")
            return []
    except Exception as e:
        st.error(f"❌ Error reading schema for {table_name}: {str(e)}")
        return []

def get_table_row_count(table_name):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
            conn.close()
            return count
        else:
            return 0
    except Exception as e:
        return 0

def clear_table(table_name):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                
                if count == 0:
                    st.warning(f"⚠️ Table {table_name} is already empty")
                    return
                
                cursor.execute(f"DELETE FROM {table_name}")
                conn.commit()
                
                reset_tables = [
                    "messages", "workflow_runs", "workflow_generation_log", 
                    "processed_tweets", "workflow_limits"
                ]
                
                if table_name in reset_tables:
                    cursor.execute(f"ALTER SEQUENCE {table_name}_id_seq RESTART WITH 1")
                    conn.commit()
                
            conn.close()
            st.success(f"✅ Successfully deleted all {count} rows from {table_name}")
            st.rerun()
        else:
            st.error("❌ Failed to connect to database")
    except Exception as e:
        st.error(f"❌ Error clearing table: {str(e)}")