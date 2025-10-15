from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import docx
import fitz  # PyMuPDF
import time
from groq import Groq
from neo4j import GraphDatabase
from dotenv import load_dotenv
import uuid
import logging
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# === Config ===
load_dotenv()
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
NEO4J_URI = os.getenv('NEO4J_URI', 'neo4j://localhost:7687')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', 'password')

if not GROQ_API_KEY:
    raise ValueError("❌ GROQ_API_KEY not set in environment variables.")

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Neo4j Driver ===
@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30),
       retry=retry_if_exception_type(Exception))
def init_neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    with driver.session() as session:
        session.run("RETURN 1")
    logger.info("✅ Connected to Neo4j")
    return driver

neo4j_driver = init_neo4j_driver()
groq_client = Groq(api_key=GROQ_API_KEY)

UPLOAD_FOLDER = 'Uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# === In-memory memory store ===
memory_store = {}

# === Neo4j Helper ===
def store_case_data(tx, case_data):
    case_id = str(uuid.uuid4())
    created_at = time.strftime("%Y-%m-%d")

    query = """
    CREATE (c:Case {
        case_id: $case_id,
        title: $title,
        judge: $judge,
        date: $date,
        case_type: $case_type,
        parties: $parties,
        created_at: $created_at
    })

    CREATE (s:Summary {id: $sid, text: $summary, created_at: $created_at})
    CREATE (c)-[:HAS_SUMMARY]->(s)

    CREATE (v:Verdict {id: $vid, text: $verdict, created_at: $created_at})
    CREATE (c)-[:HAS_VERDICT]->(v)

    CREATE (i:Issue {id: $iid, text: $issues, created_at: $created_at})
    CREATE (c)-[:HAS_ISSUE]->(i)

    CREATE (e:Entity {id: $eid, text: $entities, created_at: $created_at})
    CREATE (c)-[:INVOLVES_PARTY]->(e)

    CREATE (d:Damages {id: $did, text: $damages, amount: $damages_amount, created_at: $created_at})
    CREATE (c)-[:HAS_DAMAGES]->(d)
    """
    tx.run(query,
           case_id=case_id, title=case_data["title"], judge=case_data["judge"],
           date=case_data["date"], case_type=case_data["case_type"], parties=case_data["parties"],
           sid=str(uuid.uuid4()), summary=case_data["summary"],
           vid=str(uuid.uuid4()), verdict=case_data["verdict"],
           iid=str(uuid.uuid4()), issues=case_data["issues"],
           eid=str(uuid.uuid4()), entities=case_data["entities"],
           did=str(uuid.uuid4()), damages=case_data["damages"],
           damages_amount=case_data["damages_amount"], created_at=created_at)
    return case_id

# === Routes ===
@app.route("/")
def home():
    return "⚖️ Legal Case Analysis Chatbot API is running."

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200

@app.route("/upload", methods=["POST"])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename.lower().endswith(('.pdf', '.docx')):
        return jsonify({'error': 'Unsupported file type'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    try:
        text = extract_text(filepath)
        chunks = chunk_text(text)
        case_data = extract_case_data(chunks)

        with neo4j_driver.session() as session:
            case_id = session.execute_write(store_case_data, case_data)

        return jsonify({
            "message": "✅ File processed successfully",
            "case_id": case_id,
            "summary": case_data["summary"]
        })

    except Exception as e:
        logger.error(f"❌ Error in upload_file: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "").strip()
    case_id = data.get("case_id")
    session_id = data.get("session_id", str(uuid.uuid4()))

    if not message or not case_id:
        return jsonify({"error": "Message and case_id are required"}), 400

    # Initialize memory for this session
    if session_id not in memory_store:
        memory_store[session_id] = []

    # Check for "first question" before appending current message
    if "first question" in message.lower():
        if len(memory_store[session_id]) > 0:
            first_q = memory_store[session_id][0]
            reply = f"Your first question was: \"{first_q}\""
        else:
            reply = "You haven't asked any previous questions yet."
        return jsonify({"reply": reply, "session_id": session_id})

    # Neo4j query
    query = """
    MATCH (c:Case {case_id: $case_id})
    OPTIONAL MATCH (c)-[:HAS_SUMMARY]->(s:Summary)
    OPTIONAL MATCH (c)-[:HAS_VERDICT]->(v:Verdict)
    OPTIONAL MATCH (c)-[:HAS_ISSUE]->(i:Issue)
    OPTIONAL MATCH (c)-[:INVOLVES_PARTY]->(e:Entity)
    OPTIONAL MATCH (c)-[:HAS_DAMAGES]->(d:Damages)
    RETURN c.title AS title, c.date AS date, c.judge AS judge,
           s.text AS summary, v.text AS verdict, i.text AS issues,
           e.text AS entities, d.text AS damages, d.amount AS damages_amount
    """

    with neo4j_driver.session() as session:
        result = session.run(query, case_id=case_id).data()

    if not result:
        return jsonify({"reply": "No case found for the given ID."})

    context = json.dumps(result[0], indent=2)

    # Append current message to memory
    memory_store[session_id].append({"question": message})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a legal assistant. Answer only based on the case data."},
                {"role": "user", "content": f"Case Data:\n{context}\n\nUser Question: {message}"}
            ],
            temperature=0.4,
            max_tokens=500
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"❌ Groq API error: {e}")
        reply = "Sorry, I could not process your request."

    # Save bot's reply in memory
    memory_store[session_id][-1]["answer"] = reply

    return jsonify({"reply": reply, "session_id": session_id})

# === Summarize conversation ===
@app.route("/conversation_summary", methods=["POST"])
def conversation_summary():
    data = request.get_json()
    chat_log = data.get("chat", [])
    if not chat_log:
        return jsonify({"summary": "No conversations made yet."})

    conversation_text = ""
    for msg in chat_log:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        conversation_text += f"{role.capitalize()}: {content}\n"

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

# === Helpers ===
def extract_text(filepath):
    if filepath.endswith(".pdf"):
        doc = fitz.open(filepath)
        text = "\n".join([page.get_text() for page in doc])
        doc.close()
    elif filepath.endswith(".docx"):
        doc = docx.Document(filepath)
        text = "\n".join([p.text for p in doc.paragraphs])
    else:
        text = ""
    return text

def chunk_text(text, size=500):
    words = text.split()
    return [' '.join(words[i:i+size]) for i in range(0, len(words), size)]

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def extract_case_data(chunks):
    combined = " ".join(chunks)
    prompt = """
    Extract the following legal case fields as JSON:
    - title, judge, date (YYYY-MM-DD), case_type, parties
    - summary (5 sentences), verdict, issues, entities
    - damages (text) and damages_amount (total string, e.g., "$500,000")
    If unknown, return "Unknown".
    """
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": combined}
        ],
        temperature=0.3,
        max_tokens=800,
        response_format={"type": "json_object"}
    )
    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"⚠️ Failed to parse JSON from Groq: {e}")
        return {
            "title": "Unknown", "judge": "Unknown", "date": time.strftime("%Y-%m-%d"),
            "case_type": "Unknown", "parties": "Unknown", "summary": "Unknown",
            "verdict": "Unknown", "issues": "Unknown", "entities": "Unknown",
            "damages": "Unknown", "damages_amount": "Unknown"
        }

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
