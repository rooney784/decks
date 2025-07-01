import os
import sys
from dotenv import load_dotenv
import google.generativeai as genai

# Get the absolute path of the current directory
current_dir = os.path.abspath(os.path.dirname(__file__))

# Add path to src directory
sys.path.append(os.path.join(current_dir, 'src'))

from src.core.database import save_messages_to_db

def main():
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY")
    num_messages = int(os.getenv("NUM_MESSAGES", 10))

    if not key:
        print("GEMINI_API_KEY missing in .env")
        return

    genai.configure(api_key=key)

    # Confirm the model you want
    model_name = "gemini-2.5-flash-preview-05-20"
    model = genai.GenerativeModel(model_name)

    prompt_path = os.path.join(os.path.dirname(__file__), "reply.txt")
    try:
        with open(prompt_path) as f:
            prompt_template = f.read().strip()
    except FileNotFoundError:
        print(f"{prompt_path} not found.")
        return

    full_prompt = f"Create {num_messages} messages that reply to people that need help with their assignments. Provide them as a numbered list."
    try:
        resp = model.generate_content(full_prompt)
        lines = [l.strip().lstrip("0123456789. ").strip() for l in resp.text.splitlines() if l.strip()]
        messages = lines[:num_messages]
        print(f"Generated {len(messages)} messages.")
    except Exception as e:
        print("Error generating content:", e)
        return

    try:
        save_messages_to_db(messages)
        print("Saved to database.")
    except Exception as e:
        print("Database error:", e)

if __name__ == "__main__":
    main()