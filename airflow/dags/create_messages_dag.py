import os, sys, logging
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from dotenv import load_dotenv
from google import genai

sys.path.append('/opt/airflow/src')
from core.database import save_messages_to_db, ensure_database

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def generate_messages():
    load_dotenv()
    logger.info("📌 Starting message generation task")
    if not ensure_database():
        raise Exception("Database initialization failed")

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise Exception("GEMINI_API_KEY not found")

    try:
        num_messages = int(os.getenv("NUM_MESSAGES", "10"))
    except ValueError:
        raise Exception("Invalid NUM_MESSAGES configuration")

    client = genai.Client(api_key=key)
    model_name = "gemini-2.5-flash"
    prompt_path = '/opt/airflow/src/create_messages/reply.txt'
    try:
        with open(prompt_path) as f:
            prompt_template = f.read().strip()
    except FileNotFoundError:
        return "Prompt template file not found"

    full_prompt = (prompt_template +
                   f"\nCreate {num_messages} messages that reply "
                   "to people needing assignment help, "
                   "returned as a numbered list.")

    resp = client.models.generate_content(model=model_name, contents=full_prompt)
    lines = [l.strip().lstrip("0123456789. ").strip()
             for l in resp.text.splitlines() if l.strip()]
    messages = lines[:num_messages]
    save_messages_to_db(messages)
    return f"Successfully generated and saved {len(messages)} messages."

default_args = {
    "owner": "airflow", "depends_on_past": False,
    "start_date": datetime(2023, 1, 1), "retries": 2,
    "retry_delay": timedelta(seconds=0),
    "email_on_failure": False, "email_on_retry": False,
}

dag = DAG(
    "create_messages", default_args=default_args,
    description="Generate assignment-help messages via Gemini",
    schedule_interval=None, catchup=False, max_active_runs=1,
    tags=["ai", "messages", "gemini"],
)

PythonOperator(
    task_id="generate_messages", python_callable=generate_messages, dag=dag
)
