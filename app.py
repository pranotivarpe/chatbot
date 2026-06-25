from flask import Flask, request, render_template, Response, stream_with_context, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from groq import Groq
from pypdf import PdfReader
from dotenv import load_dotenv
from mysql.connector import pooling
import os
import json
import re
import mysql.connector

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

db_pool = pooling.MySQLConnectionPool(
    pool_name="chatpool",
    pool_size=5,
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)

def get_db():
    return db_pool.get_connection()

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access the chatbot."

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return User(row["id"], row["username"])
    except Exception:
        pass
    return None

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Add emojis to your responses and keep answers concise."

def build_messages(history, user_input, system_prompt=None):
    messages = [{"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT}]
    for item in history:
        messages.append({"role": "user", "content": item["user_message"]})
        messages.append({"role": "assistant", "content": item["bot_response"]})
    messages.append({"role": "user", "content": user_input})
    return messages


def fix_character_spacing(text):
    # Some PDFs extract as "F a m i l y  D e t a i l s" — collapse it back.
    # Multi-space gaps are word boundaries; single spaces are character spacers.
    text = re.sub(r'  +', '\x00', text)
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'([A-Za-z]) ([A-Za-z])', r'\1\2', text)
    return text.replace('\x00', ' ')


def chunk_text(text, size=1500, overlap=150):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def find_relevant_chunks(query, chunks, top_k=3):
    words = set(re.sub(r'[^\w\s]', '', query.lower()).split())
    scored = sorted(
        enumerate(chunks),
        key=lambda ic: len(words & set(re.sub(r'[^\w\s]', '', ic[1].lower()).split())),
        reverse=True
    )
    return [chunks[i] for i, chunk in scored[:top_k]
            if len(words & set(re.sub(r'[^\w\s]', '', chunk.lower()).split())) > 0]


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            error = "All fields are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, generate_password_hash(password))
                )
                conn.commit()
                cur.close()
                conn.close()
                return redirect(url_for("login"))
            except mysql.connector.IntegrityError:
                error = "Username already taken. Choose another."
            except Exception as e:
                app.logger.error(f"Register error: {e}")
                error = "Something went wrong. Please try again."

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        try:
            conn = get_db()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row and check_password_hash(row["password_hash"], password):
                login_user(User(row["id"], row["username"]), remember=True)
                return redirect(url_for("home"))
            else:
                error = "Invalid username or password."
        except Exception as e:
            app.logger.error(f"Login error: {e}")
            error = "Something went wrong. Please try again."

    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Session management routes ─────────────────────────────────────────────────

@app.route("/session/new", methods=["POST"])
@login_required
def new_session():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_sessions (user_id, title) VALUES (%s, %s)",
            (current_user.id, "New Chat")
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.close()
        conn.close()
        return redirect(url_for("home", s=new_id))
    except Exception as e:
        app.logger.error(f"New session error: {e}")
        return redirect(url_for("home"))


@app.route("/session/<int:sid>/delete", methods=["POST"])
@login_required
def delete_session(sid):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM chat_sessions WHERE id = %s AND user_id = %s",
            (sid, current_user.id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"Delete session error: {e}")
    return redirect(url_for("home"))


@app.route("/session/<int:sid>/persona", methods=["POST"])
@login_required
def update_persona(sid):
    system_prompt = request.form.get("system_prompt", "").strip() or None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE chat_sessions SET system_prompt = %s WHERE id = %s AND user_id = %s",
            (system_prompt, sid, current_user.id)
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"success": True}
    except Exception as e:
        app.logger.error(f"Persona update error: {e}")
        return {"success": False}, 500


@app.route("/session/<int:sid>/upload", methods=["POST"])
@login_required
def upload_pdf(sid):
    if 'pdf' not in request.files:
        return {"success": False, "error": "No file provided."}, 400
    file = request.files['pdf']
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        return {"success": False, "error": "Only PDF files are supported."}, 400

    filename = secure_filename(file.filename)
    try:
        reader = PdfReader(file)
        raw = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        if not raw.strip():
            return {"success": False, "error": "No text could be extracted from this PDF."}, 400
        text = fix_character_spacing(raw)

        chunks = chunk_text(text)
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        # Delete old chunks first, then the document record
        cur.execute(
            "SELECT id FROM session_documents WHERE chat_session_id = %s AND user_id = %s",
            (sid, current_user.id)
        )
        old = cur.fetchone()
        if old:
            cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (old["id"],))
        cur.execute(
            "DELETE FROM session_documents WHERE chat_session_id = %s AND user_id = %s",
            (sid, current_user.id)
        )
        cur.execute(
            "INSERT INTO session_documents (chat_session_id, user_id, filename) VALUES (%s, %s, %s)",
            (sid, current_user.id, filename)
        )
        doc_id = cur.lastrowid
        cur.executemany(
            "INSERT INTO document_chunks (document_id, chunk_index, content) VALUES (%s, %s, %s)",
            [(doc_id, i, c) for i, c in enumerate(chunks)]
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"success": True, "filename": filename, "chunks": len(chunks)}
    except Exception as e:
        app.logger.error(f"PDF upload error: {e}")
        return {"success": False, "error": "Failed to process PDF."}, 500


@app.route("/session/<int:sid>/doc/remove", methods=["POST"])
@login_required
def remove_doc(sid):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id FROM session_documents WHERE chat_session_id = %s AND user_id = %s",
            (sid, current_user.id)
        )
        doc = cur.fetchone()
        if doc:
            cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc["id"],))
            cur.execute("DELETE FROM session_documents WHERE id = %s", (doc["id"],))
        conn.commit()
        cur.close()
        conn.close()
        return {"success": True}
    except Exception as e:
        app.logger.error(f"Doc remove error: {e}")
        return {"success": False}, 500


# ── Chat routes ───────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
@login_required
def home():
    user_id = current_user.id
    search_query = request.args.get("search", "").strip()
    active_session_id = request.args.get("s", type=int)
    error = None

    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)

        # Load all sessions for the sidebar
        cur.execute(
            "SELECT * FROM chat_sessions WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,)
        )
        sessions = cur.fetchall()

        # Auto-create a first session if the user has none
        if not sessions:
            cur.execute(
                "INSERT INTO chat_sessions (user_id, title) VALUES (%s, %s)",
                (user_id, "New Chat")
            )
            conn.commit()
            active_session_id = cur.lastrowid
            cur.execute(
                "SELECT * FROM chat_sessions WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,)
            )
            sessions = cur.fetchall()

        # Fall back to latest session if requested one doesn't belong to user
        session_ids = {s["id"] for s in sessions}
        if not active_session_id or active_session_id not in session_ids:
            active_session_id = sessions[0]["id"]

        # Load active session's system_prompt and attached document
        cur.execute(
            "SELECT system_prompt FROM chat_sessions WHERE id = %s",
            (active_session_id,)
        )
        session_row = cur.fetchone()
        active_system_prompt = (session_row.get("system_prompt") or "") if session_row else ""

        cur.execute(
            "SELECT id, filename FROM session_documents WHERE chat_session_id = %s AND user_id = %s",
            (active_session_id, user_id)
        )
        active_doc = cur.fetchone()

        # Load chat history for the active session
        if search_query:
            cur.execute(
                "SELECT * FROM chat_history WHERE chat_session_id = %s "
                "AND (user_message LIKE %s OR bot_response LIKE %s)",
                (active_session_id, f"%{search_query}%", f"%{search_query}%")
            )
        else:
            cur.execute(
                "SELECT * FROM chat_history WHERE chat_session_id = %s ORDER BY id",
                (active_session_id,)
            )
        chat_history = cur.fetchall()
        cur.close()
        conn.close()

    except Exception as e:
        app.logger.error(f"DB load error: {e}")
        chat_history = []
        sessions = []
        active_session_id = None
        active_system_prompt = ""
        active_doc = None
        error = "Could not load chat history. Please refresh."

    return render_template("index.html",
        chat_history=chat_history,
        sessions=sessions,
        active_session_id=active_session_id,
        active_system_prompt=active_system_prompt,
        active_doc=active_doc,
        search_query=search_query,
        error=error
    )


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    user_id = current_user.id
    user_input = request.form.get("user_input", "").strip()
    chat_session_id = request.form.get("session_id", type=int)

    def generate():
        if not user_input:
            yield f"data: {json.dumps({'error': 'Message cannot be empty.'})}\n\n"
            return
        if not chat_session_id:
            yield f"data: {json.dumps({'error': 'No session selected.'})}\n\n"
            return
        try:
            conn = get_db()
            cur = conn.cursor(dictionary=True)

            # Fetch session persona
            cur.execute(
                "SELECT system_prompt FROM chat_sessions WHERE id = %s AND user_id = %s",
                (chat_session_id, user_id)
            )
            sess = cur.fetchone()
            system_prompt = sess.get("system_prompt") if sess else None

            # Fetch attached document chunks for RAG
            cur.execute(
                "SELECT id FROM session_documents WHERE chat_session_id = %s AND user_id = %s",
                (chat_session_id, user_id)
            )
            doc_row = cur.fetchone()
            relevant_chunks = []
            if doc_row:
                cur.execute(
                    "SELECT content FROM document_chunks WHERE document_id = %s ORDER BY chunk_index",
                    (doc_row["id"],)
                )
                all_chunks = [r["content"] for r in cur.fetchall()]
                relevant_chunks = find_relevant_chunks(user_input, all_chunks)

            # Fetch last 20 messages for context
            cur.execute(
                "SELECT user_message, bot_response FROM chat_history "
                "WHERE chat_session_id = %s ORDER BY id DESC LIMIT 20",
                (chat_session_id,)
            )
            history = list(reversed(cur.fetchall()))
            cur.close()
            conn.close()

            # Inject document context into system prompt when relevant
            if relevant_chunks:
                context = "\n\n---\n\n".join(relevant_chunks)
                effective_prompt = (
                    f"{system_prompt or DEFAULT_SYSTEM_PROMPT}\n\n"
                    f"Use the following document excerpt to answer questions when relevant:\n\n{context}"
                )
            else:
                effective_prompt = system_prompt

            messages = build_messages(history, user_input, effective_prompt)
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                stream=True,
                extra_body={"stream_options": {"include_usage": True}}
            )

            full_response = ""
            usage_data = None
            for chunk in response:
                if chunk.usage:
                    usage_data = chunk.usage
                    continue
                token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"

            # Save to DB
            conn = get_db()
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "INSERT INTO chat_history (user_id, chat_session_id, user_message, bot_response) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, chat_session_id, user_input, full_response)
            )
            conn.commit()

            # Auto-title session from first message
            cur.execute(
                "SELECT title FROM chat_sessions WHERE id = %s AND user_id = %s",
                (chat_session_id, user_id)
            )
            row = cur.fetchone()
            if row and row["title"] == "New Chat":
                title = user_input[:45] + ("..." if len(user_input) > 45 else "")
                cur.execute(
                    "UPDATE chat_sessions SET title = %s WHERE id = %s",
                    (title, chat_session_id)
                )
                conn.commit()
                yield f"data: {json.dumps({'title': title})}\n\n"

            cur.close()
            conn.close()

            done_payload = {"done": True}
            if usage_data:
                done_payload["usage"] = {
                    "prompt": usage_data.prompt_tokens,
                    "completion": usage_data.completion_tokens,
                    "total": usage_data.total_tokens
                }
            yield f"data: {json.dumps(done_payload)}\n\n"

        except Exception as e:
            app.logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'error': 'Something went wrong. Please try again.'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


if __name__ == "__main__":
    app.run(debug=True)
