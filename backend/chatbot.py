from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
import os
from dotenv import load_dotenv
import uuid
import logging

# === Config ===
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY in .env")

app = Flask(__name__)
CORS(app)
groq_client = Groq(api_key=GROQ_API_KEY)

memory_store = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return "Groq Chatbot server running. Use POST /chat and /summarize."

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    session_id = data.get("session_id", str(uuid.uuid4()))

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    if session_id not in memory_store:
        memory_store[session_id] = []

    # Handle first question check
    if "first question" in user_message.lower():
        if len(memory_store[session_id]) > 0:
            first_q = memory_store[session_id][0]["question"]
            ai_reply = f"Your first question was: \"{first_q}\""
        else:
            ai_reply = "You haven't asked any previous questions yet."
        return jsonify({"reply": ai_reply, "session_id": session_id})

    # Add current message to memory
    memory_store[session_id].append({"question": user_message})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helpful legal chatbot."},
                {"role": "user", "content": f"Previous questions: {[q['question'] for q in memory_store[session_id][:-1]]}\nCurrent question: {user_message}"}
            ],
            temperature=0.5,
            max_tokens=400
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"❌ Groq API error: {e}")
        ai_reply = "Error processing request."

    memory_store[session_id][-1]["answer"] = ai_reply

    return jsonify({"reply": ai_reply, "session_id": session_id})

@app.route('/summarize', methods=['POST'])
def summarize():
    data = request.get_json()
    session_id = data.get("session_id")
    if not session_id or session_id not in memory_store or len(memory_store[session_id]) == 0:
        return jsonify({"summary": "No conversations made yet."})

    conversation_text = ""
    for qa in memory_store[session_id]:
        conversation_text += f"Q: {qa['question']}\nA: {qa.get('answer', 'No answer')}\n"

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Summarize the following legal conversation briefly."},
                {"role": "user", "content": conversation_text}
            ],
            temperature=0.3,
            max_tokens=300
        )
        summary = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"❌ Groq API error during summarization: {e}")
        summary = "Could not generate summary."

    return jsonify({"summary": summary})

if __name__ == "__main__":
    app.run(debug=True, port=5002)





