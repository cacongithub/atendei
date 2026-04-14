"""
╔══════════════════════════════════════════════════════════════╗
║  ATENDE.AI v2.0 — Sistema de Atendente IA para WhatsApp    ║
║  SaaS completo com painel admin + mídia + Mercado Pago      ║
╚══════════════════════════════════════════════════════════════╝

Requisitos:
  pip install flask mercadopago requests openai

Configuração (variáveis de ambiente):
  SECRET_KEY=sua_chave_secreta
  MERCADOPAGO_ACCESS_TOKEN=seu_token_mp
  WHATSAPP_VERIFY_TOKEN=seu_token_verificacao
  ANTHROPIC_API_KEY=sua_chave_anthropic
  OPENAI_API_KEY=sua_chave_openai (fallback para transcrição de áudio)
  GROQ_API_KEY=sua_chave_groq (transcrição de áudio — mais barato)
  BASE_URL=https://seudominio.com
  ADMIN_EMAIL=admin@atende.ai
  ADMIN_PASSWORD=admin123

Rodar:
  python app.py
"""

import os, json, sqlite3, hashlib, secrets, time, re, base64, tempfile, io
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, request, jsonify, redirect, url_for,
    session, g, make_response, abort, send_file
)

# ─── CONFIG ────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

MERCADOPAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "TEST-xxxx")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "meu_token_verificacao")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@atende.ai")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
DATABASE = "atendeia.db"
MEDIA_FOLDER = "media_files"

os.makedirs(MEDIA_FOLDER, exist_ok=True)

# ─── SECURITY ──────────────────────────────────────────────────
login_attempts = {}  # {ip: {"count": n, "last": timestamp}}

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

def check_rate_limit(ip, max_attempts=5, window=300):
    """Bloqueia login após 5 tentativas em 5 minutos"""
    now = time.time()
    if ip in login_attempts:
        data = login_attempts[ip]
        if now - data["last"] > window:
            login_attempts[ip] = {"count": 0, "last": now}
            return True
        if data["count"] >= max_attempts:
            return False
    return True

def record_login_attempt(ip):
    now = time.time()
    if ip not in login_attempts:
        login_attempts[ip] = {"count": 0, "last": now}
    login_attempts[ip]["count"] += 1
    login_attempts[ip]["last"] = now

def reset_login_attempts(ip):
    if ip in login_attempts:
        del login_attempts[ip]

# ─── LOGO (base64 inline) ─────────────────────────────────────
LOGO_NAV_B64 = "iVBORw0KGgoAAAANSUhEUgAAAEsAAAAyCAIAAACbAbG0AAABCGlDQ1BJQ0MgUHJvZmlsZQAAeJxjYGA8wQAELAYMDLl5JUVB7k4KEZFRCuwPGBiBEAwSk4sLGHADoKpv1yBqL+viUYcLcKakFicD6Q9ArFIEtBxopAiQLZIOYWuA2EkQtg2IXV5SUAJkB4DYRSFBzkB2CpCtkY7ETkJiJxcUgdT3ANk2uTmlyQh3M/Ck5oUGA2kOIJZhKGYIYnBncAL5H6IkfxEDg8VXBgbmCQixpJkMDNtbGRgkbiHEVBYwMPC3MDBsO48QQ4RJQWJRIliIBYiZ0tIYGD4tZ2DgjWRgEL7AwMAVDQsIHG5TALvNnSEfCNMZchhSgSKeDHkMyQx6QJYRgwGDIYMZAKbWPz9HbOBQAAAGJklEQVR42u2YXWwc1RXHz7l3ZvZrZne9H97d2LC2cewksuvWWIktQl1InGKlRWoFAfFVlAekSn3oh9S3IiEhqlIe+tBKFa1a8dLSVGqVlocYAmooJCEUkhiHEDuxvYmdON7v3Znd2Zm59/KwJg4SUu0QFIPmp3mZO6M799xzzj3/OQAuLi4uLi4uLi4uLl88+LknuG4GIRBRgADxFdkcXP+TWwD9XDYqihyJSdEYjbUiCG6aoSjKYdWqWkhwg3jyhnYbiaQGZS0geSQS1FANQrJdSndZddtrXDInXiEoSkv1L60PkYDgskwY9TqRDivSZUkheylrHnsT9Xw90b9taOmhF7cW5qzsdJVQFLfak9K6c09w9Gts95OifxezZag3gEgQDpIWvzP1mv2HXxR/PnTC7qybpwA2RJziOs0TJH47feJZu2ThewfTgXPtKUORIZf3TOc6zR37lS1p5/nHJdXG4R9Yf3lB2A0AvGYpEhRc/J/liM88uG78fMZ1mAeAvpC0/wX7w6ke86/7fubvu0uVJSJRISy2fE4/8Hz2sPVD5d497OkHlId/ZB+bcGbeb64PEQRf+SAiCiEQEVYWjiAEIELTePLJbTMGEFbGm3Zee+3m5yGhILi880G7YPbhn598qduTUM+dskDzFCpYsmTSGhx9tBWOvTI53yO1J53Df1PGHmOTR1b2XgAApIYi+uX66si1CwAEqGktfk+qera0+hQABPi7o0gJMyy4obina3W14MTjg/7x0Ae/+86LAxaRXnpq5tAvM1pPKLolYNSFXofFEvnGdxOZPx5car2fTE0QIbFKQVaszfvSyaGQmvIN/LjDWLDDd6jpvUkEEtseT+1p86c1M9toe3RL+O5N4CFApOh4F1IaGGrT7umSWjVtT6+yOc4L9eC3tyrpqJUpAOc320IkiCDf95RTx97ts+1j6dyMefQ3M2AzmtA2jUT1mrAErdtYlgMqGpOZQZpMwdUMyF5qFZSU1jIQRi8tzdVL03r3/q7StJEYTXi6whdfnlW3b2oZ6ygfvVx8eymwq9vbGTEXa4GdnRjXyv/6yDfS5VSd2n8v+Hdv5Q0udyecyyVWMGDN9ZasMT7p4Djb9wxaedqTdAyvrgX9HZpAjN/bttyQc6ZSQF/e9iyUaCkRlViJPfYrDMdE8ao63KYMbFpewEpVNn1BoQYKJaVqSBf+nc0VlMr5arlM9QphkTDpTtbrUs2gZlUUX503K2DOFxs6ZxZgKmqXHCZ7jLfm2JVKUyHePB8iASFw2zdF56A4/o9IP/cnY4sml2Ja4XAmP637h9tNr29xqmEGVF0oxSvm0v+8vPcuPDnBF85aubplobmol95dNvMN1hD5w3Mk6q9n9NqFCivWWI1V/zOHEVXYTH/9vDl5BcIBJ1O05/K8ZPBKwzqzSFpU88hZQYgwbWexAOspsrjGEk8S3eTxX7O3D7YOzwTHe3i5qgSV3D9ns78/7kn41Tvb8hNz6lCq/Zm7zXcymaM7aP8I++1+YVY/IyY270Am+MKHwtI3iKYRACCMApw9gkbJzuWdwR7BuNMQnr4E7UzWTi0bJxdBcCYUee9g+eWTtm8HvvUnvjwPACQUl0YfIclOEknRke+RYAwTtxEtiJEUvXOcRFLoU6WdD6JtivIyELJSMABXMg0REFdHcN1yV1p7PeTFJSgu2VmpPA9yW8QnqqTm0IG2lueSjTPLrNiQRnv1N6eNd3W6q+HMnQZCkUikb4xfvQREIv17+fEDePvXwGFceDHRzs6fwHgH2f4A5i6hNwRcNEXF9QVmJSCvH/kCNQ2lwDn9ei/85GF+/hKNeOSYRJiFMhEeGUybvX7aPjBFxn7K3vs7vzgFALT1DgwlhS8ElgF6QVSzqMVB8gB3QFJ4/iL6wqh4sOU2PvsOr2ZXLLyFqg0BpN3D3GqIo5MQDeNAF7YGhW1jxYIrligHSN+3+NQhNnuimb1fwr8nBLxOITZVZGo0mXzivtOHRkjmDXbmVWEUP2Xe6u9wU459OsHxk2nEhuoLNM8DRJAIEFS3xWPfH0AtsXr2fnWbPuQmNH42ZsMGKdlYzRkXFxcXFxcXFxcXFxeXdfIx37bOK7RWD8oAAAAASUVORK5CYII="

# Planos
PLANS = {
    "starter":  {"name": "Starter",       "price": 97.00,  "msgs": 500,   "desc": "Ideal para começar"},
    "pro":      {"name": "Profissional",   "price": 197.00, "msgs": 2000,  "desc": "Para negócios em crescimento"},
    "business": {"name": "Business",       "price": 397.00, "msgs": 10000, "desc": "Volume máximo"},
}

# ─── DATABASE ──────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL,
        company TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        plan TEXT DEFAULT 'starter',
        plan_status TEXT DEFAULT 'trial',
        mp_subscription_id TEXT DEFAULT '',
        msgs_used INTEGER DEFAULT 0,
        msgs_limit INTEGER DEFAULT 500,
        trial_ends_at TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        whatsapp_phone_id TEXT DEFAULT '',
        whatsapp_token TEXT DEFAULT '',
        ai_system_prompt TEXT DEFAULT 'Você é um atendente virtual simpático e prestativo. Responda de forma clara e objetiva.',
        ai_tone TEXT DEFAULT 'profissional',
        ai_greeting TEXT DEFAULT 'Olá! 👋 Como posso ajudar você hoje?',
        business_hours TEXT DEFAULT '08:00-18:00',
        auto_reply_off_hours TEXT DEFAULT 'Nosso horário de atendimento é de 08h às 18h. Deixe sua mensagem!',
        is_active INTEGER DEFAULT 1,
        last_login TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS knowledge_base (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT DEFAULT 'geral',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        customer_phone TEXT NOT NULL,
        customer_name TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        is_human_takeover INTEGER DEFAULT 0,
        satisfaction_rating INTEGER DEFAULT 0,
        tags TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        last_message_at TEXT DEFAULT (datetime('now')),
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        sender TEXT NOT NULL,
        content TEXT NOT NULL,
        msg_type TEXT DEFAULT 'text',
        media_url TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mp_payment_id TEXT DEFAULT '',
        amount REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        plan TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS quick_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        shortcut TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT DEFAULT 'geral',
        times_used INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS blocked_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        phone TEXT NOT NULL,
        reason TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS api_usage_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        api_name TEXT NOT NULL,
        tokens_in INTEGER DEFAULT 0,
        tokens_out INTEGER DEFAULT 0,
        cost_estimate REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS admin_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        details TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    );
    """)
    # ── MIGRAÇÃO AUTOMÁTICA ──
    migrations = [
        ("users", "is_active", "INTEGER DEFAULT 1"),
        ("users", "last_login", "TEXT DEFAULT ''"),
        ("conversations", "satisfaction_rating", "INTEGER DEFAULT 0"),
        ("conversations", "tags", "TEXT DEFAULT ''"),
        ("conversations", "notes", "TEXT DEFAULT ''"),
        ("messages", "media_url", "TEXT DEFAULT ''"),
    ]
    for table, column, col_type in migrations:
        try:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass
    db.commit()
    db.close()


def get_setting(key, default=""):
    """Busca config do banco, se não existir usa variável de ambiente"""
    try:
        db_conn = sqlite3.connect(DATABASE)
        row = db_conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
        db_conn.close()
        if row and row[0]:
            return row[0]
    except:
        pass
    return os.getenv(key, default)


def set_setting(key, value):
    """Salva config no banco"""
    db_conn = sqlite3.connect(DATABASE)
    db_conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, value))
    db_conn.commit()
    db_conn.close()

# ─── AUTH ──────────────────────────────────────────────────────
def hash_password(pw):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000)
    return f"{salt}:{h.hex()}"

def check_password(pw, stored):
    salt, h = stored.split(":")
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000).hex() == h

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not user:
            session.clear()
            return redirect("/login")
        g.user = user
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated

# ─── MEDIA HANDLING ────────────────────────────────────────────

def download_whatsapp_media(media_id, token):
    """Baixa mídia do WhatsApp e retorna o caminho local"""
    try:
        import requests as req
        # Passo 1: pegar a URL do media
        url = f"https://graph.facebook.com/v18.0/{media_id}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = req.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        media_url = resp.json().get("url")
        
        # Passo 2: baixar o arquivo
        resp2 = req.get(media_url, headers=headers, timeout=30)
        if resp2.status_code != 200:
            return None
        
        # Salvar localmente
        content_type = resp2.headers.get("Content-Type", "")
        ext = ".bin"
        if "image" in content_type: ext = ".jpg"
        elif "audio" in content_type or "ogg" in content_type: ext = ".ogg"
        elif "pdf" in content_type: ext = ".pdf"
        elif "document" in content_type: ext = ".doc"
        elif "video" in content_type: ext = ".mp4"
        
        filename = f"{media_id}{ext}"
        filepath = os.path.join(MEDIA_FOLDER, filename)
        with open(filepath, "wb") as f:
            f.write(resp2.content)
        return filepath
    except Exception as e:
        print(f"Erro ao baixar mídia: {e}")
        return None


def transcribe_audio(filepath):
    """Transcreve áudio usando Groq (primário) ou OpenAI Whisper (fallback)"""
    
    groq_key = get_setting("GROQ_API_KEY")
    openai_key = get_setting("OPENAI_API_KEY")
    
    # Tenta Groq primeiro (mais barato)
    if groq_key:
        try:
            import requests as req
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {groq_key}"}
            with open(filepath, "rb") as audio_file:
                files = {"file": (os.path.basename(filepath), audio_file)}
                data = {"model": "whisper-large-v3", "language": "pt"}
                resp = req.post(url, headers=headers, files=files, data=data, timeout=60)
            if resp.status_code == 200:
                text = resp.json().get("text", "")
                print(f"[GROQ] Áudio transcrito: {text[:80]}...")
                return text if text else "[Não foi possível transcrever]"
            else:
                print(f"Groq API error: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"Groq transcription error: {e}")
    
    # Fallback para OpenAI
    if openai_key:
        try:
            import requests as req
            url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {openai_key}"}
            with open(filepath, "rb") as audio_file:
                files = {"file": (os.path.basename(filepath), audio_file)}
                data = {"model": "whisper-1", "language": "pt"}
                resp = req.post(url, headers=headers, files=files, data=data, timeout=60)
            if resp.status_code == 200:
                text = resp.json().get("text", "")
                print(f"[OPENAI] Áudio transcrito: {text[:80]}...")
                return text if text else "[Não foi possível transcrever]"
            else:
                print(f"Whisper API error: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"OpenAI transcription error: {e}")
    
    print("[AUDIO] Nenhuma API de transcrição configurada")
    return "[Transcrição indisponível — configure GROQ_API_KEY no painel admin]"


def analyze_image_with_claude(filepath, user_question=""):
    """Analisa imagem usando Claude Vision"""
    api_key = get_setting("ANTHROPIC_API_KEY")
    if not api_key:
        return "[Análise de imagem indisponível — configure ANTHROPIC_API_KEY no painel admin]"
    try:
        import requests as req
        with open(filepath, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        ext = os.path.splitext(filepath)[1].lower()
        media_type = {"jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                      ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")
        
        prompt = user_question if user_question else "Descreva esta imagem em detalhes. Se for um produto, diga o que é. Se tiver texto, transcreva."
        
        resp = req.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": prompt}
                ]}]
            }, timeout=30)
        
        if resp.status_code == 200:
            return resp.json()["content"][0]["text"]
        return "[Não foi possível analisar a imagem]"
    except Exception as e:
        print(f"Image analysis error: {e}")
        return "[Erro ao analisar imagem]"


def extract_pdf_text(filepath):
    """Extrai texto de PDF"""
    try:
        # Tenta com PyPDF2 ou pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(filepath) as pdf:
                text = ""
                for page in pdf.pages[:10]:  # Limita a 10 páginas
                    text += (page.extract_text() or "") + "\n"
                return text.strip() if text.strip() else "[PDF sem texto extraível]"
        except ImportError:
            pass
        
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(filepath)
            text = ""
            for page in reader.pages[:10]:
                text += (page.extract_text() or "") + "\n"
            return text.strip() if text.strip() else "[PDF sem texto extraível]"
        except ImportError:
            pass
        
        return "[Instale pdfplumber ou PyPDF2 para ler PDFs: pip install pdfplumber]"
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return "[Erro ao extrair texto do PDF]"


def process_whatsapp_media(msg, token):
    """Processa qualquer tipo de mídia recebida no WhatsApp"""
    msg_type = msg.get("type", "text")
    result = {"type": msg_type, "content": "", "description": "", "media_path": ""}
    
    if msg_type == "text":
        result["content"] = msg.get("text", {}).get("body", "")
        result["description"] = result["content"]
        
    elif msg_type == "audio":
        media_id = msg.get("audio", {}).get("id", "")
        if media_id:
            filepath = download_whatsapp_media(media_id, token)
            if filepath:
                result["media_path"] = filepath
                transcription = transcribe_audio(filepath)
                result["content"] = f"🎤 [Áudio transcrito]: {transcription}"
                result["description"] = transcription
            else:
                result["content"] = "🎤 [Áudio recebido — não foi possível baixar]"
                result["description"] = result["content"]
                
    elif msg_type == "image":
        media_id = msg.get("image", {}).get("id", "")
        caption = msg.get("image", {}).get("caption", "")
        if media_id:
            filepath = download_whatsapp_media(media_id, token)
            if filepath:
                result["media_path"] = filepath
                analysis = analyze_image_with_claude(filepath, caption)
                caption_text = f' (legenda: "{caption}")' if caption else ""
                result["content"] = f"📷 [Imagem recebida{caption_text}]: {analysis}"
                result["description"] = analysis
            else:
                result["content"] = "📷 [Imagem recebida — não foi possível baixar]"
                result["description"] = result["content"]
                
    elif msg_type == "document":
        media_id = msg.get("document", {}).get("id", "")
        filename = msg.get("document", {}).get("filename", "documento")
        mime = msg.get("document", {}).get("mime_type", "")
        if media_id:
            filepath = download_whatsapp_media(media_id, token)
            if filepath:
                result["media_path"] = filepath
                if "pdf" in mime:
                    text = extract_pdf_text(filepath)
                    result["content"] = f"📄 [PDF: {filename}]: {text[:2000]}"
                    result["description"] = text[:2000]
                else:
                    result["content"] = f"📄 [Documento: {filename}] — recebido e salvo"
                    result["description"] = f"Documento {filename} recebido"
            else:
                result["content"] = f"📄 [Documento: {filename}] — não foi possível baixar"
                result["description"] = result["content"]
                
    elif msg_type == "video":
        media_id = msg.get("video", {}).get("id", "")
        caption = msg.get("video", {}).get("caption", "")
        result["content"] = f"🎥 [Vídeo recebido]{': ' + caption if caption else ''}"
        result["description"] = result["content"]
        if media_id:
            filepath = download_whatsapp_media(media_id, token)
            if filepath:
                result["media_path"] = filepath
                
    elif msg_type == "location":
        lat = msg.get("location", {}).get("latitude", "")
        lon = msg.get("location", {}).get("longitude", "")
        loc_name = msg.get("location", {}).get("name", "")
        address = msg.get("location", {}).get("address", "")
        loc_text = f"📍 Localização: {loc_name} {address}".strip() if loc_name or address else f"📍 Localização: {lat}, {lon}"
        result["content"] = loc_text
        result["description"] = loc_text
        
    elif msg_type == "contacts":
        contacts = msg.get("contacts", [])
        names = [c.get("name", {}).get("formatted_name", "?") for c in contacts]
        result["content"] = f"👤 [Contato(s) compartilhado(s)]: {', '.join(names)}"
        result["description"] = result["content"]
        
    elif msg_type == "sticker":
        result["content"] = "😀 [Sticker recebido]"
        result["description"] = "Cliente enviou um sticker"
        
    elif msg_type == "reaction":
        emoji = msg.get("reaction", {}).get("emoji", "")
        result["content"] = f"[Reação: {emoji}]"
        result["description"] = result["content"]
        
    else:
        result["content"] = f"[{msg_type}] Tipo de mensagem não suportado"
        result["description"] = result["content"]
    
    return result


# ─── CSS GLOBAL ────────────────────────────────────────────────

GLOBAL_CSS = """
:root {
    --bg:#0a0e14; --bg2:#111827; --bg3:#1a2235; --bg4:#243049;
    --text:#f0f4f8; --text2:#94a3b8; --text3:#64748b;
    --accent:#00c896; --accent2:#34d399; --accent-glow:rgba(0,200,150,0.12);
    --green:#00b894; --green2:#00e6b0; --red:#ef4444; --orange:#f59e0b; --blue:#0ea5e9;
    --radius:12px; --radius-sm:8px;
    --font:'DM Sans',-apple-system,sans-serif; --mono:'JetBrains Mono',monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg);color:var(--text);min-height:100vh;-webkit-font-smoothing:antialiased}
a{color:var(--accent2);text-decoration:none}
a:hover{color:#5eead4}

.nav-main{background:rgba(10,14,20,0.9);border-bottom:1px solid rgba(255,255,255,0.06);position:sticky;top:0;z-index:100;backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px)}
.nav-inner{max-width:1200px;margin:0 auto;padding:0 24px;height:72px;display:flex;align-items:center;justify-content:space-between}
.logo{font-size:22px;font-weight:700;color:var(--text);letter-spacing:-0.5px}
.logo span{color:var(--accent)}
.nav-logo-img{height:50px;width:auto;display:block;transition:transform 0.2s}
.nav-logo-img:hover{transform:scale(1.03)}
.nav-links{display:flex;gap:4px}
.nav-link{padding:8px 16px;border-radius:var(--radius-sm);color:var(--text2);font-size:14px;font-weight:500;transition:all 0.2s}
.nav-link:hover{color:var(--text);background:var(--bg3)}
.nav-link-accent{color:var(--accent2)!important}
.nav-user{display:flex;align-items:center;gap:12px;font-size:13px}
.user-plan{background:var(--accent-glow);color:var(--accent2);padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
.user-name{color:var(--text2)}
.btn-logout{color:var(--text3);font-size:12px;padding:4px 8px}

.container{max-width:1200px;margin:0 auto;padding:32px 24px}
.page-header{margin-bottom:32px}
.page-header h1{font-size:28px;font-weight:700;letter-spacing:-0.5px}
.page-header p{color:var(--text2);margin-top:4px;font-size:15px}

.card{background:var(--bg2);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);padding:24px}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.card-title{font-size:16px;font-weight:600}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:32px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:32px}
.grid-4{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:32px}
.grid-5{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:32px}

.stat-card{background:var(--bg2);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);padding:20px 24px}
.stat-card .stat-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:12px}
.stat-card .stat-value{font-size:28px;font-weight:700;letter-spacing:-1px}
.stat-card .stat-label{color:var(--text2);font-size:13px;margin-top:2px}
.stat-icon-green{background:rgba(0,184,148,0.15);color:var(--green2)}
.stat-icon-blue{background:rgba(9,132,227,0.15);color:var(--blue)}
.stat-icon-purple{background:var(--accent-glow);color:var(--accent2)}
.stat-icon-orange{background:rgba(243,156,18,0.15);color:var(--orange)}
.stat-icon-red{background:rgba(231,76,60,0.15);color:var(--red)}

.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border-radius:var(--radius-sm);font-size:14px;font-weight:500;border:none;cursor:pointer;transition:all 0.2s;font-family:var(--font)}
.btn-primary{background:var(--accent);color:white}
.btn-primary:hover{background:#00a87d;transform:translateY(-1px);box-shadow:0 4px 20px rgba(0,200,150,0.3)}
.btn-secondary{background:var(--bg3);color:var(--text);border:1px solid rgba(255,255,255,0.08)}
.btn-secondary:hover{background:var(--bg4)}
.btn-success{background:var(--green);color:white}
.btn-danger{background:var(--red);color:white}
.btn-sm{padding:6px 14px;font-size:13px}
.btn-lg{padding:14px 28px;font-size:16px}
.btn-block{width:100%;justify-content:center}

.form-group{margin-bottom:20px}
.form-label{display:block;font-size:13px;font-weight:500;color:var(--text2);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px}
.form-input{width:100%;padding:12px 16px;background:var(--bg3);border:1px solid rgba(255,255,255,0.08);border-radius:var(--radius-sm);color:var(--text);font-size:14px;font-family:var(--font);transition:border-color 0.2s}
.form-input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
textarea.form-input{min-height:120px;resize:vertical;line-height:1.6}

.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:12px 16px;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid rgba(255,255,255,0.06)}
td{padding:14px 16px;border-bottom:1px solid rgba(255,255,255,0.04);font-size:14px}
tr:hover td{background:rgba(255,255,255,0.02)}

.badge{display:inline-flex;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.3px}
.badge-green{background:rgba(0,184,148,0.15);color:var(--green2)}
.badge-orange{background:rgba(243,156,18,0.15);color:var(--orange)}
.badge-red{background:rgba(231,76,60,0.15);color:var(--red)}
.badge-purple{background:var(--accent-glow);color:var(--accent2)}
.badge-blue{background:rgba(9,132,227,0.15);color:var(--blue)}

.plan-card{background:var(--bg2);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);padding:32px;text-align:center;transition:all 0.3s;position:relative}
.plan-card:hover{border-color:var(--accent);transform:translateY(-4px);box-shadow:0 8px 32px rgba(0,200,150,0.12)}
.plan-card.popular{border-color:var(--accent)}
.plan-card.popular::before{content:'MAIS POPULAR';position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:var(--accent);color:white;padding:4px 16px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:1px}
.plan-name{font-size:20px;font-weight:700;margin-bottom:8px}
.plan-price{font-size:40px;font-weight:700;color:var(--accent2);margin:16px 0}
.plan-price small{font-size:16px;color:var(--text2);font-weight:400}
.plan-desc{color:var(--text2);font-size:14px;margin-bottom:20px}
.plan-features{list-style:none;text-align:left;margin-bottom:24px}
.plan-features li{padding:8px 0;font-size:14px;color:var(--text2);border-bottom:1px solid rgba(255,255,255,0.04)}
.plan-features li::before{content:'✓';color:var(--green2);margin-right:8px;font-weight:700}

.chat-container{display:flex;height:calc(100vh - 160px);gap:0;background:var(--bg2);border-radius:var(--radius);overflow:hidden;border:1px solid rgba(255,255,255,0.06)}
.chat-sidebar{width:320px;border-right:1px solid rgba(255,255,255,0.06);overflow-y:auto}
.chat-sidebar-header{padding:20px;border-bottom:1px solid rgba(255,255,255,0.06)}
.chat-item{padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;transition:background 0.2s}
.chat-item:hover{background:var(--bg3)}
.chat-item.active{background:var(--accent-glow);border-left:3px solid var(--accent)}
.chat-item-name{font-weight:600;font-size:14px}
.chat-item-preview{color:var(--text3);font-size:13px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-item-time{color:var(--text3);font-size:11px;float:right}
.chat-main{flex:1;display:flex;flex-direction:column}
.chat-header{padding:16px 24px;border-bottom:1px solid rgba(255,255,255,0.06);display:flex;justify-content:space-between;align-items:center}
.chat-messages{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:70%;padding:12px 16px;border-radius:16px;font-size:14px;line-height:1.5}
.msg-customer{background:var(--bg4);align-self:flex-start;border-bottom-left-radius:4px}
.msg-bot{background:var(--accent);color:white;align-self:flex-end;border-bottom-right-radius:4px}
.msg-time{font-size:10px;opacity:0.6;margin-top:4px}
.msg-media{font-size:12px;opacity:0.8;font-style:italic}

.auth-container{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.auth-card{background:var(--bg2);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:40px;width:100%;max-width:420px;box-shadow:0 4px 24px rgba(0,0,0,0.3)}
.auth-card .logo{font-size:28px;text-align:center;display:block;margin-bottom:32px}
.auth-card h2{font-size:22px;margin-bottom:24px;text-align:center}
.auth-divider{text-align:center;color:var(--text3);font-size:13px;margin:20px 0}

.hero{text-align:center;padding:80px 24px 40px;max-width:800px;margin:0 auto}
.hero h1{font-size:48px;font-weight:700;letter-spacing:-1.5px;line-height:1.1;margin-bottom:20px}
.hero h1 .gradient{background:linear-gradient(135deg,#00c896,#0ea5e9);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{font-size:18px;color:var(--text2);max-width:560px;margin:0 auto 32px;line-height:1.6}
.hero-badges{display:flex;gap:12px;justify-content:center;margin-bottom:40px;flex-wrap:wrap}
.hero-badge{display:flex;align-items:center;gap:6px;padding:6px 14px;background:rgba(0,200,150,0.08);border:1px solid rgba(0,200,150,0.15);border-radius:20px;font-size:13px;color:var(--accent2);font-weight:500}
.features-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:1000px;margin:0 auto 80px;padding:0 24px}
.feature-card{background:var(--bg2);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);padding:28px;transition:all 0.3s;position:relative;overflow:hidden}
.feature-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:0;transition:opacity 0.3s}
.feature-card:hover{border-color:rgba(0,200,150,0.2);transform:translateY(-3px);box-shadow:0 8px 32px rgba(0,0,0,0.2)}
.feature-card:hover::before{opacity:1}
.feature-icon{font-size:28px;margin-bottom:14px;width:48px;height:48px;display:flex;align-items:center;justify-content:center;background:rgba(0,200,150,0.08);border-radius:12px}
.feature-card h3{font-size:17px;font-weight:600;margin-bottom:8px}
.feature-card p{font-size:14px;color:var(--text2);line-height:1.6}

.alert{padding:14px 20px;border-radius:var(--radius-sm);margin-bottom:20px;font-size:14px}
.alert-success{background:rgba(0,184,148,0.1);border:1px solid rgba(0,184,148,0.2);color:var(--green2)}
.alert-error{background:rgba(231,76,60,0.1);border:1px solid rgba(231,76,60,0.2);color:var(--red)}
.alert-info{background:var(--accent-glow);border:1px solid rgba(108,92,231,0.2);color:var(--accent2)}

.empty-state{text-align:center;padding:60px 24px;color:var(--text3)}
.empty-state .icon{font-size:48px;margin-bottom:16px}
.empty-state h3{color:var(--text2);margin-bottom:8px}

.usage-bar-bg{background:var(--bg4);border-radius:20px;height:8px;overflow:hidden}
.usage-bar-fill{height:100%;border-radius:20px;transition:width 0.5s ease}

/* ADMIN SPECIFIC */
.admin-nav{background:linear-gradient(135deg,#0a1628,#0a0e14);border-bottom:2px solid var(--accent)}
.admin-badge{background:var(--red);color:white;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:700;letter-spacing:1px;margin-left:8px}
.metric-card{background:var(--bg2);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);padding:24px;text-align:center}
.metric-value{font-size:32px;font-weight:700;margin:8px 0 4px}
.metric-label{font-size:13px;color:var(--text2)}
.metric-trend{font-size:12px;margin-top:4px}
.trend-up{color:var(--green2)}
.trend-down{color:var(--red)}

@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.fade-in{animation:fadeIn 0.4s ease-out forwards}
.fade-in-1{animation-delay:0.1s;opacity:0}
.fade-in-2{animation-delay:0.2s;opacity:0}
.fade-in-3{animation-delay:0.3s;opacity:0}
.fade-in-4{animation-delay:0.4s;opacity:0}

@media(max-width:768px){
    .grid-2,.grid-3,.grid-4,.grid-5{grid-template-columns:1fr}
    .features-grid{grid-template-columns:1fr}
    .hero h1{font-size:32px}
    .chat-sidebar{width:100%}
    .nav-links{display:none}
}
"""

# ─── HTML BUILDERS ─────────────────────────────────────────────

def base_html(title, content, user=None):
    nav = ""
    if user:
        plan_name = PLANS.get(user['plan'],{}).get('name','')
        nav = f"""<nav class="nav-main"><div class="nav-inner">
            <a href="/dashboard"><img src="data:image/png;base64,{LOGO_NAV_B64}" alt="atendente.online" class="nav-logo-img"></a>
            <div class="nav-links">
                <a href="/dashboard" class="nav-link">Dashboard</a>
                <a href="/dashboard/conversations" class="nav-link">Conversas</a>
                <a href="/dashboard/training" class="nav-link">Treinamento</a>
                <a href="/dashboard/quick-replies" class="nav-link">Respostas rápidas</a>
                <a href="/dashboard/settings" class="nav-link">Config</a>
                <a href="/dashboard/billing" class="nav-link nav-link-accent">Plano</a>
            </div>
            <div class="nav-user">
                <span class="user-plan">{plan_name}</span>
                <span class="user-name">{user['name']}</span>
                <a href="/logout" class="btn-logout">Sair</a>
            </div></div></nav>"""
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} — atendente.online</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{GLOBAL_CSS}</style></head><body>{nav}{content}</body></html>"""


def admin_html(title, content):
    nav = f"""<nav class="nav-main admin-nav"><div class="nav-inner">
        <a href="/admin" style="display:flex;align-items:center;gap:10px"><img src="data:image/png;base64,{LOGO_NAV_B64}" alt="atendente.online" class="nav-logo-img"><span class="admin-badge">ADMIN</span></a>
        <div class="nav-links">
            <a href="/admin" class="nav-link">Dashboard</a>
            <a href="/admin/users" class="nav-link">Clientes</a>
            <a href="/admin/payments" class="nav-link">Pagamentos</a>
            <a href="/admin/usage" class="nav-link">Uso de API</a>
            <a href="/admin/logs" class="nav-link">Logs</a>
            <a href="/admin/api-settings" class="nav-link nav-link-accent">APIs</a>
        </div>
        <div class="nav-user">
            <span class="user-plan" style="background:rgba(239,68,68,0.15);color:var(--red)">ADMIN</span>
            <a href="/admin/logout" class="btn-logout">Sair</a>
        </div></div></nav>"""
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} — Admin Atende.AI</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{GLOBAL_CSS}</style></head><body>{nav}{content}</body></html>"""


# ─── HELPER FUNCTIONS ──────────────────────────────────────────

def get_user_stats(user_id):
    db = get_db()
    convos = db.execute("SELECT COUNT(*) as c FROM conversations WHERE user_id=?", (user_id,)).fetchone()["c"]
    msgs = db.execute("SELECT COUNT(*) as c FROM messages m JOIN conversations c ON m.conversation_id=c.id WHERE c.user_id=?", (user_id,)).fetchone()["c"]
    today_msgs = db.execute("SELECT COUNT(*) as c FROM messages m JOIN conversations c ON m.conversation_id=c.id WHERE c.user_id=? AND m.created_at >= date('now')", (user_id,)).fetchone()["c"]
    kb = db.execute("SELECT COUNT(*) as c FROM knowledge_base WHERE user_id=?", (user_id,)).fetchone()["c"]
    return {"conversations": convos, "messages": msgs, "today_messages": today_msgs, "knowledge_items": kb}


def get_admin_stats():
    db = get_db()
    total_users = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    active_users = db.execute("SELECT COUNT(*) as c FROM users WHERE plan_status='active'").fetchone()["c"]
    trial_users = db.execute("SELECT COUNT(*) as c FROM users WHERE plan_status='trial'").fetchone()["c"]
    inactive_users = db.execute("SELECT COUNT(*) as c FROM users WHERE plan_status='inactive' OR plan_status='cancelled'").fetchone()["c"]
    
    # MRR
    mrr_rows = db.execute("SELECT plan FROM users WHERE plan_status='active'").fetchall()
    mrr = sum(PLANS.get(r["plan"], {}).get("price", 0) for r in mrr_rows)
    
    # Receita total
    total_revenue = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM payments WHERE status='approved'").fetchone()["s"]
    
    # Conversas e mensagens totais
    total_conversations = db.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
    total_messages = db.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
    
    # Hoje
    new_users_today = db.execute("SELECT COUNT(*) as c FROM users WHERE created_at >= date('now')").fetchone()["c"]
    msgs_today = db.execute("SELECT COUNT(*) as c FROM messages WHERE created_at >= date('now')").fetchone()["c"]
    payments_today = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM payments WHERE status='approved' AND created_at >= date('now')").fetchone()["s"]
    
    # Por plano
    by_plan = {}
    for key in PLANS:
        count = db.execute("SELECT COUNT(*) as c FROM users WHERE plan=? AND plan_status='active'", (key,)).fetchone()["c"]
        by_plan[key] = count
    
    # Custo estimado de API
    total_api_cost = db.execute("SELECT COALESCE(SUM(cost_estimate),0) as s FROM api_usage_log").fetchone()["s"]
    
    return {
        "total_users": total_users, "active_users": active_users, "trial_users": trial_users,
        "inactive_users": inactive_users, "mrr": mrr, "total_revenue": total_revenue,
        "total_conversations": total_conversations, "total_messages": total_messages,
        "new_users_today": new_users_today, "msgs_today": msgs_today,
        "payments_today": payments_today, "by_plan": by_plan, "total_api_cost": total_api_cost
    }


# ═══════════════════════════════════════════════════════════════
#  ROTAS DO CLIENTE (mesmo de antes, com melhorias)
# ═══════════════════════════════════════════════════════════════

@app.route("/privacy")
def privacy_policy():
    content = """
    <div class="container" style="max-width:800px">
        <div class="card" style="margin-top:40px;padding:40px">
            <h1 style="font-size:28px;font-weight:700;margin-bottom:24px">Política de Privacidade</h1>
            <p style="color:var(--text2);margin-bottom:16px">Última atualização: abril de 2026</p>
            
            <div style="color:var(--text2);font-size:15px;line-height:1.8">
                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">1. Informações que coletamos</h2>
                <p>O Atende.AI coleta as seguintes informações para fornecer nossos serviços:</p>
                <p>• <strong style="color:var(--text)">Dados de cadastro:</strong> nome, email, empresa e telefone fornecidos durante o registro.</p>
                <p>• <strong style="color:var(--text)">Dados do WhatsApp Business:</strong> Phone Number ID e tokens de acesso necessários para a integração com a API do WhatsApp Cloud.</p>
                <p>• <strong style="color:var(--text)">Mensagens:</strong> conteúdo das conversas entre sua empresa e seus clientes via WhatsApp, incluindo texto, áudio, imagens e documentos, para processamento pela inteligência artificial.</p>
                <p>• <strong style="color:var(--text)">Dados de uso:</strong> métricas de utilização do serviço, como quantidade de mensagens processadas.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">2. Como usamos suas informações</h2>
                <p>Utilizamos os dados coletados para:</p>
                <p>• Fornecer e manter o serviço de atendimento automatizado via WhatsApp.</p>
                <p>• Processar mensagens recebidas e gerar respostas inteligentes através de IA.</p>
                <p>• Transcrever mensagens de áudio para texto.</p>
                <p>• Analisar imagens e documentos enviados pelos clientes.</p>
                <p>• Exibir conversas e métricas no painel administrativo.</p>
                <p>• Processar pagamentos de assinatura.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">3. Compartilhamento de dados</h2>
                <p>Seus dados podem ser compartilhados com os seguintes serviços terceiros, exclusivamente para o funcionamento do sistema:</p>
                <p>• <strong style="color:var(--text)">Meta (WhatsApp Cloud API):</strong> para envio e recebimento de mensagens.</p>
                <p>• <strong style="color:var(--text)">Anthropic (Claude):</strong> para processamento de linguagem natural e geração de respostas.</p>
                <p>• <strong style="color:var(--text)">Groq:</strong> para transcrição de mensagens de áudio.</p>
                <p>• <strong style="color:var(--text)">Mercado Pago:</strong> para processamento de pagamentos.</p>
                <p>Não vendemos, alugamos ou compartilhamos seus dados pessoais com terceiros para fins de marketing.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">4. Armazenamento e segurança</h2>
                <p>Os dados são armazenados em servidores seguros. Senhas são criptografadas usando PBKDF2 com salt. Tokens de API são armazenados de forma segura no banco de dados. Utilizamos HTTPS para toda comunicação.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">5. Retenção de dados</h2>
                <p>Mantemos seus dados enquanto sua conta estiver ativa. Ao cancelar sua conta, seus dados serão excluídos em até 30 dias, exceto quando houver obrigação legal de retenção.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">6. Direitos do usuário</h2>
                <p>Conforme a LGPD (Lei Geral de Proteção de Dados), você tem direito a:</p>
                <p>• Acessar seus dados pessoais.</p>
                <p>• Corrigir dados incompletos ou incorretos.</p>
                <p>• Solicitar a exclusão dos seus dados.</p>
                <p>• Revogar o consentimento a qualquer momento.</p>
                <p>• Solicitar a portabilidade dos seus dados.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">7. Contato</h2>
                <p>Para dúvidas sobre esta política ou para exercer seus direitos, entre em contato pelo email do administrador do sistema.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">8. Alterações</h2>
                <p>Esta política pode ser atualizada periodicamente. Notificaremos sobre mudanças significativas por email ou pelo painel do sistema.</p>
            </div>
            
            <div style="margin-top:32px;text-align:center">
                <a href="/" class="btn btn-secondary">← Voltar ao início</a>
            </div>
        </div>
    </div>"""
    return base_html("Política de Privacidade", content)


@app.route("/terms")
def terms_of_service():
    content = """
    <div class="container" style="max-width:800px">
        <div class="card" style="margin-top:40px;padding:40px">
            <h1 style="font-size:28px;font-weight:700;margin-bottom:24px">Termos de Serviço</h1>
            <p style="color:var(--text2);margin-bottom:16px">Última atualização: abril de 2026</p>
            
            <div style="color:var(--text2);font-size:15px;line-height:1.8">
                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">1. Aceitação dos termos</h2>
                <p>Ao utilizar o Atende.AI, você concorda com estes Termos de Serviço. Se não concordar, não utilize o serviço.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">2. Descrição do serviço</h2>
                <p>O Atende.AI é uma plataforma SaaS de atendimento automatizado via WhatsApp com inteligência artificial. O serviço inclui: recebimento e resposta automática de mensagens, transcrição de áudios, análise de imagens, painel administrativo e integração com a API do WhatsApp Business.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">3. Planos e pagamento</h2>
                <p>Oferecemos planos de assinatura mensal com período de teste gratuito de 7 dias. Os pagamentos são processados via Mercado Pago. Os preços podem ser atualizados com aviso prévio de 30 dias.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">4. Responsabilidades do usuário</h2>
                <p>O usuário é responsável por: manter a confidencialidade de suas credenciais, cumprir as políticas do WhatsApp Business, garantir que possui consentimento dos seus clientes para comunicação via WhatsApp, e não utilizar o serviço para envio de spam ou conteúdo ilegal.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">5. Limitação de responsabilidade</h2>
                <p>O Atende.AI não se responsabiliza por: indisponibilidade temporária dos serviços de terceiros (WhatsApp, Anthropic, Groq), conteúdo gerado pela IA que possa conter imprecisões, ou perdas decorrentes do uso inadequado do serviço.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">6. Cancelamento</h2>
                <p>Você pode cancelar sua assinatura a qualquer momento pelo painel. O acesso continuará até o final do período pago. Não há reembolso proporcional.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">7. Propriedade intelectual</h2>
                <p>O Atende.AI e todo seu conteúdo, funcionalidades e tecnologia são de propriedade exclusiva da empresa. Os dados e conversas dos clientes pertencem ao usuário.</p>

                <h2 style="color:var(--text);font-size:18px;margin:24px 0 12px">8. Contato</h2>
                <p>Para dúvidas sobre estes termos, entre em contato pelo email do administrador do sistema.</p>
            </div>
            
            <div style="margin-top:32px;text-align:center">
                <a href="/" class="btn btn-secondary">← Voltar ao início</a>
            </div>
        </div>
    </div>"""
    return base_html("Termos de Serviço", content)


@app.route("/")
def landing():
    if "user_id" in session: return redirect("/dashboard")
    nav_logo = LOGO_NAV_B64
    content = f"""
    <nav class="nav-main"><div class="nav-inner">
        <a href="/"><img src="data:image/png;base64,{nav_logo}" alt="atendente.online" class="nav-logo-img"></a>
        <div class="nav-links">
            <a href="#features" class="nav-link">Recursos</a>
            <a href="#pricing" class="nav-link">Planos</a>
            <a href="/login" class="nav-link">Entrar</a>
            <a href="/register" class="btn btn-primary btn-sm" style="margin-left:8px">Começar grátis</a>
        </div>
    </div></nav>

    <div class="hero fade-in">
        <h1>Seu atendente de vendas<br><span class="gradient">com inteligência artificial</span></h1>
        <p>Automatize seu WhatsApp com IA treinável. Entende texto, áudio, imagens e documentos. Responda clientes 24/7.</p>
        <div class="hero-badges">
            <span class="hero-badge">✓ WhatsApp Business API</span>
            <span class="hero-badge">✓ IA Avançada</span>
            <span class="hero-badge">✓ 7 dias grátis</span>
        </div>
        <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
            <a href="/register" class="btn btn-primary btn-lg">Começar grátis →</a>
            <a href="/login" class="btn btn-secondary btn-lg">Já tenho conta</a>
        </div>
    </div>

    <div id="features" class="features-grid">
        <div class="feature-card fade-in fade-in-1"><div class="feature-icon">🤖</div><h3>IA Treinável</h3><p>Ensine sobre seus produtos, preços e jeito de atender. A IA aprende o DNA do seu negócio.</p></div>
        <div class="feature-card fade-in fade-in-2"><div class="feature-icon">🎤</div><h3>Entende Áudio</h3><p>Transcreve e responde áudios automaticamente. Seu cliente fala, a IA entende.</p></div>
        <div class="feature-card fade-in fade-in-3"><div class="feature-icon">📷</div><h3>Analisa Imagens</h3><p>Entende fotos de produtos, comprovantes e documentos enviados.</p></div>
        <div class="feature-card fade-in fade-in-1"><div class="feature-icon">📄</div><h3>Lê PDFs</h3><p>Extrai e processa texto de documentos. Orçamentos, contratos e mais.</p></div>
        <div class="feature-card fade-in fade-in-2"><div class="feature-icon">📊</div><h3>Painel Completo</h3><p>Conversas em tempo real, métricas de atendimento e controle total.</p></div>
        <div class="feature-card fade-in fade-in-3"><div class="feature-icon">⚡</div><h3>Respostas Rápidas</h3><p>Atalhos para mensagens frequentes. Atenda em segundos.</p></div>
    </div>

    <div style="text-align:center;padding:40px 24px 20px">
        <p style="color:var(--accent2);font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:2px;margin-bottom:12px">Como funciona</p>
        <h2 style="font-size:32px;margin-bottom:48px;letter-spacing:-0.5px">Simples como 1, 2, 3</h2>
        <div class="grid-3" style="max-width:900px;margin:0 auto 60px;text-align:center">
            <div class="card fade-in fade-in-1" style="text-align:center;padding:32px">
                <div style="font-size:36px;font-weight:800;color:var(--accent);margin-bottom:12px">1</div>
                <h3 style="margin-bottom:8px">Conecte seu WhatsApp</h3>
                <p style="color:var(--text2);font-size:14px">Vincule seu número do WhatsApp Business em poucos cliques.</p></div>
            <div class="card fade-in fade-in-2" style="text-align:center;padding:32px">
                <div style="font-size:36px;font-weight:800;color:var(--accent);margin-bottom:12px">2</div>
                <h3 style="margin-bottom:8px">Treine a IA</h3>
                <p style="color:var(--text2);font-size:14px">Cadastre produtos, preços, FAQ e o tom de voz da sua empresa.</p></div>
            <div class="card fade-in fade-in-3" style="text-align:center;padding:32px">
                <div style="font-size:36px;font-weight:800;color:var(--accent);margin-bottom:12px">3</div>
                <h3 style="margin-bottom:8px">Venda no automático</h3>
                <p style="color:var(--text2);font-size:14px">A IA atende seus clientes 24/7 enquanto você foca no que importa.</p></div>
        </div>
    </div>

    <div id="pricing" style="text-align:center;padding:20px 24px 80px">
        <p style="color:var(--accent2);font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:2px;margin-bottom:12px">Planos</p>
        <h2 style="font-size:32px;margin-bottom:12px;letter-spacing:-0.5px">Invista no crescimento do seu negócio</h2>
        <p style="color:var(--text2);margin-bottom:40px">7 dias grátis em todos os planos. Cancele quando quiser.</p>
        <div class="grid-3" style="max-width:900px;margin:0 auto">
            <div class="plan-card fade-in fade-in-1"><div class="plan-name">Starter</div><div class="plan-price">R$ 97<small>/mês</small></div><div class="plan-desc">Ideal para começar</div>
                <ul class="plan-features"><li>500 mensagens/mês</li><li>Áudio + Imagem + PDF</li><li>Base de conhecimento</li><li>Painel de conversas</li></ul>
                <a href="/register?plan=starter" class="btn btn-secondary btn-block">Começar grátis</a></div>
            <div class="plan-card popular fade-in fade-in-2"><div class="plan-name">Profissional</div><div class="plan-price">R$ 197<small>/mês</small></div><div class="plan-desc">Para negócios em crescimento</div>
                <ul class="plan-features"><li>2.000 mensagens/mês</li><li>Tudo do Starter</li><li>Respostas rápidas</li><li>CRM básico</li><li>Suporte prioritário</li></ul>
                <a href="/register?plan=pro" class="btn btn-primary btn-block">Começar grátis</a></div>
            <div class="plan-card fade-in fade-in-3"><div class="plan-name">Business</div><div class="plan-price">R$ 397<small>/mês</small></div><div class="plan-desc">Volume máximo</div>
                <ul class="plan-features"><li>10.000 mensagens/mês</li><li>Tudo do Pro</li><li>Múltiplos números</li><li>API personalizada</li><li>Gerente de conta</li></ul>
                <a href="/register?plan=business" class="btn btn-secondary btn-block">Começar grátis</a></div>
        </div>
    </div>

    <footer style="text-align:center;padding:40px 24px;border-top:1px solid rgba(255,255,255,0.06);color:var(--text3);font-size:13px">
        <p>© 2026 atendente.online — Todos os direitos reservados</p>
        <p style="margin-top:8px"><a href="/privacy">Política de Privacidade</a> · <a href="/terms">Termos de Serviço</a></p>
    </footer>"""
    return base_html("Atendente IA para WhatsApp", content)


@app.route("/register", methods=["GET","POST"])
def register():
    error = ""
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        company = request.form.get("company","").strip()
        plan = request.form.get("plan","starter")
        if not name or not email or not password:
            error = "Preencha todos os campos obrigatórios."
        elif len(password) < 6:
            error = "Senha deve ter pelo menos 6 caracteres."
        else:
            db = get_db()
            if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                error = "Este email já está cadastrado."
            else:
                trial_end = (datetime.now() + timedelta(days=7)).isoformat()
                msgs_limit = PLANS.get(plan, PLANS["starter"])["msgs"]
                db.execute("INSERT INTO users (email,password_hash,name,company,plan,plan_status,msgs_limit,trial_ends_at) VALUES (?,?,?,?,?,?,?,?)",
                    (email, hash_password(password), name, company, plan, "trial", msgs_limit, trial_end))
                db.commit()
                user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                session["user_id"] = user["id"]
                return redirect("/dashboard")
    plan = request.args.get("plan","starter")
    alert = f'<div class="alert alert-error">{error}</div>' if error else ""
    content = f"""<div class="auth-container"><div class="auth-card">
        <a href="/" style="display:block;text-align:center;margin-bottom:24px"><img src="data:image/png;base64,{LOGO_NAV_B64}" alt="atendente.online" style="height:50px"></a><h2>Criar conta grátis</h2>{alert}
        <form method="POST"><input type="hidden" name="plan" value="{plan}">
        <div class="form-group"><label class="form-label">Seu nome *</label><input type="text" name="name" class="form-input" required></div>
        <div class="form-group"><label class="form-label">Email *</label><input type="email" name="email" class="form-input" required></div>
        <div class="form-group"><label class="form-label">Empresa</label><input type="text" name="company" class="form-input"></div>
        <div class="form-group"><label class="form-label">Senha *</label><input type="password" name="password" class="form-input" required></div>
        <button type="submit" class="btn btn-primary btn-block btn-lg">Criar conta →</button></form>
        <div class="auth-divider">Já tem conta? <a href="/login">Entrar</a></div></div></div>"""
    return base_html("Criar Conta", content)


@app.route("/login", methods=["GET","POST"])
def login():
    error = ""
    client_ip = request.remote_addr or "unknown"
    if request.method == "POST":
        if not check_rate_limit(client_ip):
            error = "Muitas tentativas de login. Aguarde 5 minutos."
        else:
            email = request.form.get("email","").strip().lower()
            password = request.form.get("password","")
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user and check_password(password, user["password_hash"]):
                reset_login_attempts(client_ip)
                session["user_id"] = user["id"]
                db.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user["id"],))
                db.commit()
                return redirect("/dashboard")
            else:
                record_login_attempt(client_ip)
                error = "Email ou senha incorretos."
    alert = f'<div class="alert alert-error">{error}</div>' if error else ""
    content = f"""<div class="auth-container"><div class="auth-card">
        <a href="/" style="display:block;text-align:center;margin-bottom:24px"><img src="data:image/png;base64,{LOGO_NAV_B64}" alt="atendente.online" style="height:50px"></a><h2>Entrar</h2>{alert}
        <form method="POST">
        <div class="form-group"><label class="form-label">Email</label><input type="email" name="email" class="form-input" required></div>
        <div class="form-group"><label class="form-label">Senha</label><input type="password" name="password" class="form-input" required></div>
        <button type="submit" class="btn btn-primary btn-block btn-lg">Entrar</button></form>
        <div class="auth-divider">Não tem conta? <a href="/register">Criar conta grátis</a></div></div></div>"""
    return base_html("Login", content)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ─── DASHBOARD ─────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    user = g.user
    stats = get_user_stats(user["id"])
    plan = PLANS.get(user["plan"], PLANS["starter"])
    usage_pct = min(100, int((user["msgs_used"] / max(user["msgs_limit"],1)) * 100))
    usage_color = "var(--green)" if usage_pct < 70 else "var(--orange)" if usage_pct < 90 else "var(--red)"
    plan_badge = '<span class="badge badge-green">ATIVO</span>' if user["plan_status"]=="active" else '<span class="badge badge-orange">TRIAL</span>' if user["plan_status"]=="trial" else '<span class="badge badge-red">INATIVO</span>'

    db = get_db()
    recent = db.execute("""SELECT c.*, (SELECT content FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) as last_msg
        FROM conversations c WHERE c.user_id=? ORDER BY c.last_message_at DESC LIMIT 5""", (user["id"],)).fetchall()
    convos_html = ""
    if recent:
        rows = "".join(f"""<tr><td><strong>{c['customer_phone']}</strong><br><span style="color:var(--text3);font-size:12px">{c['customer_name'] or 'Sem nome'}</span></td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{(c['last_msg'] or '—')[:60]}</td>
            <td>{'<span class="badge badge-green">Ativa</span>' if c['status']=='active' else '<span class="badge badge-orange">Finalizada</span>'}{' <span class="badge badge-purple">Humano</span>' if c['is_human_takeover'] else ''}</td>
            <td style="color:var(--text3);font-size:12px">{(c['last_message_at'] or '')[:16]}</td></tr>""" for c in recent)
        convos_html = f'<div class="card"><div class="card-header"><span class="card-title">Conversas recentes</span><a href="/dashboard/conversations" class="btn btn-secondary btn-sm">Ver todas →</a></div><div class="table-wrap"><table><thead><tr><th>Cliente</th><th>Última msg</th><th>Status</th><th>Hora</th></tr></thead><tbody>{rows}</tbody></table></div></div>'
    else:
        convos_html = '<div class="card"><div class="empty-state"><div class="icon">💬</div><h3>Nenhuma conversa ainda</h3><p>Configure seu WhatsApp para começar.</p><a href="/dashboard/settings" class="btn btn-primary" style="margin-top:16px">Configurar →</a></div></div>'

    content = f"""<div class="container">
        <div class="page-header fade-in"><h1>Olá, {user['name'].split()[0]}! 👋</h1><p>Plano {plan['name']} {plan_badge}</p></div>
        <div class="grid-4">
            <div class="stat-card fade-in fade-in-1"><div class="stat-icon stat-icon-green">💬</div><div class="stat-value">{stats['conversations']}</div><div class="stat-label">Conversas totais</div></div>
            <div class="stat-card fade-in fade-in-2"><div class="stat-icon stat-icon-blue">📨</div><div class="stat-value">{stats['today_messages']}</div><div class="stat-label">Mensagens hoje</div></div>
            <div class="stat-card fade-in fade-in-3"><div class="stat-icon stat-icon-purple">🧠</div><div class="stat-value">{stats['knowledge_items']}</div><div class="stat-label">Base de conhecimento</div></div>
            <div class="stat-card fade-in fade-in-4"><div class="stat-icon stat-icon-orange">📊</div><div class="stat-value">{usage_pct}%</div><div class="stat-label">Uso ({user['msgs_used']}/{user['msgs_limit']})</div>
                <div class="usage-bar-bg" style="margin-top:8px"><div class="usage-bar-fill" style="width:{usage_pct}%;background:{usage_color}"></div></div></div>
        </div>{convos_html}</div>"""
    return base_html("Dashboard", content, dict(user))


# ─── CONVERSATIONS ─────────────────────────────────────────────
@app.route("/dashboard/conversations")
@login_required
def conversations():
    db = get_db()
    user = g.user
    convos = db.execute("""SELECT c.*,(SELECT content FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) as last_msg,
        (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id) as msg_count FROM conversations c WHERE c.user_id=? ORDER BY c.last_message_at DESC""", (user["id"],)).fetchall()

    sidebar_items = ""
    first_id = None
    msgs_html = ""
    for c in convos:
        if not first_id: first_id = c["id"]
        active = "active" if c["id"] == first_id else ""
        sidebar_items += f'<div class="chat-item {active}" onclick="loadConversation({c["id"]},this)"><span class="chat-item-time">{(c["last_message_at"] or "")[:10]}</span><div class="chat-item-name">{c["customer_name"] or c["customer_phone"]}</div><div class="chat-item-preview">{(c["last_msg"] or "Sem mensagens")[:50]}</div></div>'

    if first_id:
        messages = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (first_id,)).fetchall()
        for m in messages:
            cls = "msg-bot" if m["sender"]=="bot" else "msg-customer"
            media_tag = f'<div class="msg-media">{m["msg_type"]}</div>' if m["msg_type"] not in ("text","") else ""
            msgs_html += f'<div class="msg {cls}">{m["content"]}{media_tag}<div class="msg-time">{(m["created_at"] or "")[11:16]}</div></div>'

    if not convos:
        return base_html("Conversas", '<div class="container"><div class="card"><div class="empty-state"><div class="icon">💬</div><h3>Nenhuma conversa ainda</h3><p>As conversas aparecerão aqui quando clientes enviarem mensagens.</p></div></div></div>', dict(user))

    content = f"""<div class="container"><div class="page-header"><h1>Conversas <span style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--green2);font-weight:500;background:rgba(0,200,150,0.1);padding:4px 12px;border-radius:20px;vertical-align:middle"><span style="width:8px;height:8px;border-radius:50%;background:var(--green2);display:inline-block;animation:pulse 2s infinite"></span> ao vivo</span></h1><p>{len(convos)} conversas</p></div>
    <style>@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.3}}}}</style>
        <div class="chat-container"><div class="chat-sidebar"><div class="chat-sidebar-header">
            <input type="text" class="form-input" placeholder="Buscar..." style="font-size:13px;padding:8px 12px" oninput="filterChats(this.value)">
            </div><div id="chat-list">{sidebar_items}</div></div>
            <div class="chat-main"><div class="chat-header"><div><strong id="chat-name">{convos[0]['customer_name'] or convos[0]['customer_phone']}</strong>
                <span style="color:var(--text3);font-size:12px" id="chat-phone">{convos[0]['customer_phone']}</span></div>
                <button class="btn btn-secondary btn-sm" onclick="toggleHuman()">🙋 Assumir</button></div>
                <div class="chat-messages" id="chat-messages">{msgs_html}</div>
                <div style="padding:16px 24px;border-top:1px solid rgba(255,255,255,0.06);display:flex;gap:8px">
                    <input type="text" class="form-input" id="msg-input" placeholder="Digite..." style="flex:1" onkeydown="if(event.key==='Enter')sendMsg()">
                    <button class="btn btn-primary" onclick="sendMsg()">Enviar</button></div></div></div></div>
    <script>
    let activeConvId = {first_id or 0};
    let lastMsgCount = 0;

    function loadConversation(id,el){{
        activeConvId = id;
        document.querySelectorAll('.chat-item').forEach(i=>i.classList.remove('active'));
        if(el) el.classList.add('active');
        fetch('/api/conversations/'+id+'/messages').then(r=>r.json()).then(data=>{{
            const box=document.getElementById('chat-messages');
            box.innerHTML=data.messages.map(m=>'<div class="msg '+(m.sender==='bot'?'msg-bot':'msg-customer')+'">'+m.content+'<div class="msg-time">'+((m.created_at||'').substring(11,16))+'</div></div>').join('');
            box.scrollTop=box.scrollHeight;
            lastMsgCount = data.messages.length;
            document.getElementById('chat-name').textContent=data.customer_name||data.customer_phone;
            document.getElementById('chat-phone').textContent=data.customer_phone;
        }});
    }}

    function refreshMessages(){{
        if(!activeConvId) return;
        fetch('/api/conversations/'+activeConvId+'/messages').then(r=>r.json()).then(data=>{{
            if(data.messages.length !== lastMsgCount){{
                const box=document.getElementById('chat-messages');
                box.innerHTML=data.messages.map(m=>'<div class="msg '+(m.sender==='bot'?'msg-bot':'msg-customer')+'">'+m.content+'<div class="msg-time">'+((m.created_at||'').substring(11,16))+'</div></div>').join('');
                box.scrollTop=box.scrollHeight;
                lastMsgCount = data.messages.length;
            }}
        }}).catch(()=>{{}});
    }}

    function refreshSidebar(){{
        fetch('/api/conversations').then(r=>r.json()).then(data=>{{
            const list = document.getElementById('chat-list');
            if(!data.conversations) return;
            list.innerHTML = data.conversations.map(c=>{{
                const isActive = c.id === activeConvId ? 'active' : '';
                const name = c.customer_name || c.customer_phone;
                const preview = (c.last_msg || 'Sem mensagens').substring(0,50);
                const date = (c.last_message_at || '').substring(0,10);
                return '<div class="chat-item '+isActive+'" onclick="loadConversation('+c.id+',this)"><span class="chat-item-time">'+date+'</span><div class="chat-item-name">'+name+'</div><div class="chat-item-preview">'+preview+'</div></div>';
            }}).join('');
        }}).catch(()=>{{}});
    }}

    // Auto-refresh: mensagens a cada 3s, sidebar a cada 10s
    setInterval(refreshMessages, 3000);
    setInterval(refreshSidebar, 10000);

    function sendMsg(){{const i=document.getElementById('msg-input');if(!i.value.trim())return;const b=document.getElementById('chat-messages');
        b.innerHTML+='<div class="msg msg-bot">'+i.value+'<div class="msg-time">agora</div></div>';b.scrollTop=b.scrollHeight;i.value=''}}
    function filterChats(q){{document.querySelectorAll('.chat-item').forEach(i=>{{i.style.display=i.textContent.toLowerCase().includes(q.toLowerCase())?'':'none'}})}}
    function toggleHuman(){{alert('Você assumiu o atendimento desta conversa!')}}

    // Scroll inicial
    const box=document.getElementById('chat-messages');
    if(box) box.scrollTop=box.scrollHeight;
    </script>"""
    return base_html("Conversas", content, dict(user))


# ─── TRAINING ──────────────────────────────────────────────────
@app.route("/dashboard/training", methods=["GET","POST"])
@login_required
def training():
    user = g.user; db = get_db(); msg = ""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_knowledge":
            title = request.form.get("title","").strip()
            ct = request.form.get("content","").strip()
            cat = request.form.get("category","geral")
            if title and ct:
                db.execute("INSERT INTO knowledge_base (user_id,title,content,category) VALUES (?,?,?,?)", (user["id"],title,ct,cat))
                db.commit(); msg = '<div class="alert alert-success">Item adicionado!</div>'
        elif action == "update_prompt":
            db.execute("UPDATE users SET ai_system_prompt=?,ai_tone=?,ai_greeting=? WHERE id=?",
                (request.form.get("system_prompt",""), request.form.get("tone","profissional"), request.form.get("greeting",""), user["id"]))
            db.commit(); msg = '<div class="alert alert-success">IA atualizada!</div>'
            user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        elif action == "delete_kb":
            db.execute("DELETE FROM knowledge_base WHERE id=? AND user_id=?", (request.form.get("kb_id"), user["id"]))
            db.commit(); msg = '<div class="alert alert-success">Removido!</div>'

    kb = db.execute("SELECT * FROM knowledge_base WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    kb_rows = "".join(f'<tr><td><strong>{i["title"]}</strong></td><td><span class="badge badge-purple">{i["category"]}</span></td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2)">{i["content"][:100]}</td><td><form method="POST" style="display:inline"><input type="hidden" name="action" value="delete_kb"><input type="hidden" name="kb_id" value="{i["id"]}"><button type="submit" class="btn btn-danger btn-sm">✕</button></form></td></tr>' for i in kb)

    content = f"""<div class="container"><div class="page-header fade-in"><h1>Treinamento da IA 🧠</h1><p>Configure personalidade e base de conhecimento.</p></div>{msg}
        <div class="grid-2"><div class="card fade-in fade-in-1"><div class="card-header"><span class="card-title">Personalidade da IA</span></div>
            <form method="POST"><input type="hidden" name="action" value="update_prompt">
            <div class="form-group"><label class="form-label">System prompt</label><textarea name="system_prompt" class="form-input" rows="6">{user['ai_system_prompt']}</textarea></div>
            <div class="form-group"><label class="form-label">Tom de voz</label><select name="tone" class="form-input">
                <option value="profissional" {'selected' if user['ai_tone']=='profissional' else ''}>Profissional</option>
                <option value="descontraido" {'selected' if user['ai_tone']=='descontraido' else ''}>Descontraído</option>
                <option value="formal" {'selected' if user['ai_tone']=='formal' else ''}>Formal</option>
                <option value="amigavel" {'selected' if user['ai_tone']=='amigavel' else ''}>Amigável</option></select></div>
            <div class="form-group"><label class="form-label">Saudação</label><input type="text" name="greeting" class="form-input" value="{user['ai_greeting']}"></div>
            <button type="submit" class="btn btn-primary">Salvar</button></form></div>
        <div class="card fade-in fade-in-2"><div class="card-header"><span class="card-title">Adicionar conhecimento</span></div>
            <form method="POST"><input type="hidden" name="action" value="add_knowledge">
            <div class="form-group"><label class="form-label">Título</label><input type="text" name="title" class="form-input" placeholder="Ex: Tabela de preços" required></div>
            <div class="form-group"><label class="form-label">Categoria</label><select name="category" class="form-input">
                <option value="produtos">Produtos</option><option value="precos">Preços</option><option value="faq">FAQ</option><option value="politicas">Políticas</option><option value="geral">Geral</option></select></div>
            <div class="form-group"><label class="form-label">Conteúdo</label><textarea name="content" class="form-input" rows="6" placeholder="Informações que a IA deve saber..." required></textarea></div>
            <button type="submit" class="btn btn-success">+ Adicionar</button></form></div></div>
        <div class="card fade-in fade-in-3"><div class="card-header"><span class="card-title">Base de conhecimento ({len(kb)} itens)</span></div>
            {'<div class="table-wrap"><table><thead><tr><th>Título</th><th>Categoria</th><th>Conteúdo</th><th></th></tr></thead><tbody>'+kb_rows+'</tbody></table></div>' if kb else '<div class="empty-state"><div class="icon">📚</div><h3>Base vazia</h3><p>Adicione informações sobre seus produtos.</p></div>'}</div></div>"""
    return base_html("Treinamento", content, dict(user))


# ─── QUICK REPLIES (NOVO) ─────────────────────────────────────
@app.route("/dashboard/quick-replies", methods=["GET","POST"])
@login_required
def quick_replies():
    user = g.user; db = get_db(); msg = ""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            shortcut = request.form.get("shortcut","").strip()
            content_text = request.form.get("content","").strip()
            if shortcut and content_text:
                db.execute("INSERT INTO quick_replies (user_id,shortcut,content) VALUES (?,?,?)", (user["id"],shortcut,content_text))
                db.commit(); msg = '<div class="alert alert-success">Resposta rápida adicionada!</div>'
        elif action == "delete":
            db.execute("DELETE FROM quick_replies WHERE id=? AND user_id=?", (request.form.get("qr_id"), user["id"]))
            db.commit(); msg = '<div class="alert alert-success">Removida!</div>'

    qrs = db.execute("SELECT * FROM quick_replies WHERE user_id=? ORDER BY times_used DESC", (user["id"],)).fetchall()
    rows = "".join(f'<tr><td><code style="color:var(--accent2)">/{q["shortcut"]}</code></td><td>{q["content"][:80]}</td><td>{q["times_used"]}</td><td><form method="POST" style="display:inline"><input type="hidden" name="action" value="delete"><input type="hidden" name="qr_id" value="{q["id"]}"><button type="submit" class="btn btn-danger btn-sm">✕</button></form></td></tr>' for q in qrs)

    content = f"""<div class="container"><div class="page-header"><h1>Respostas Rápidas ⚡</h1><p>Atalhos para mensagens que você usa com frequência.</p></div>{msg}
        <div class="grid-2"><div class="card"><div class="card-header"><span class="card-title">Nova resposta rápida</span></div>
            <form method="POST"><input type="hidden" name="action" value="add">
            <div class="form-group"><label class="form-label">Atalho (ex: preco, horario)</label><input type="text" name="shortcut" class="form-input" placeholder="preco" required></div>
            <div class="form-group"><label class="form-label">Mensagem</label><textarea name="content" class="form-input" rows="4" placeholder="Nossos preços começam a partir de..." required></textarea></div>
            <button type="submit" class="btn btn-success">+ Adicionar</button></form></div>
        <div class="card"><div class="card-header"><span class="card-title">Como funciona</span></div>
            <div style="color:var(--text2);font-size:14px;line-height:1.8;padding:8px 0">
                <p>Quando você está atendendo manualmente no painel, digite <code style="color:var(--accent2)">/atalho</code> para inserir a mensagem rapidamente.</p>
                <p style="margin-top:12px">A IA também pode usar essas respostas como referência para responder perguntas frequentes de forma consistente.</p>
                <p style="margin-top:12px"><strong>Exemplos úteis:</strong></p>
                <p><code style="color:var(--accent2)">/preco</code> → Tabela de preços</p>
                <p><code style="color:var(--accent2)">/horario</code> → Horário de funcionamento</p>
                <p><code style="color:var(--accent2)">/pix</code> → Chave PIX e instruções</p>
                <p><code style="color:var(--accent2)">/frete</code> → Informações de entrega</p>
            </div></div></div>
        <div class="card"><div class="card-header"><span class="card-title">Respostas cadastradas ({len(qrs)})</span></div>
            {'<div class="table-wrap"><table><thead><tr><th>Atalho</th><th>Mensagem</th><th>Usos</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>' if qrs else '<div class="empty-state"><div class="icon">⚡</div><h3>Nenhuma resposta rápida</h3><p>Crie atalhos para agilizar seu atendimento.</p></div>'}</div></div>"""
    return base_html("Respostas Rápidas", content, dict(user))


# ─── SETTINGS ──────────────────────────────────────────────────
@app.route("/dashboard/settings", methods=["GET","POST"])
@login_required
def settings():
    user = g.user; db = get_db(); msg = ""
    if request.method == "POST":
        db.execute("""UPDATE users SET whatsapp_phone_id=?,whatsapp_token=?,business_hours=?,auto_reply_off_hours=?,name=?,company=?,phone=? WHERE id=?""",
            (request.form.get("whatsapp_phone_id","").strip(), request.form.get("whatsapp_token","").strip(),
             request.form.get("business_hours","08:00-18:00").strip(), request.form.get("auto_reply_off_hours","").strip(),
             request.form.get("name","").strip(), request.form.get("company","").strip(), request.form.get("phone","").strip(), user["id"]))
        db.commit(); msg = '<div class="alert alert-success">Configurações salvas!</div>'
        user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()

    webhook_url = f"{BASE_URL}/webhook/whatsapp/{user['id']}"
    content = f"""<div class="container"><div class="page-header fade-in"><h1>Configurações ⚙️</h1></div>{msg}
        <div class="grid-2"><div class="card fade-in fade-in-1"><div class="card-header"><span class="card-title">Perfil e WhatsApp</span></div>
            <form method="POST">
            <div class="form-group"><label class="form-label">Nome</label><input type="text" name="name" class="form-input" value="{user['name']}"></div>
            <div class="form-group"><label class="form-label">Empresa</label><input type="text" name="company" class="form-input" value="{user['company']}"></div>
            <div class="form-group"><label class="form-label">Telefone</label><input type="text" name="phone" class="form-input" value="{user['phone']}"></div>
            <div class="form-group"><label class="form-label">Horário de atendimento</label><input type="text" name="business_hours" class="form-input" value="{user['business_hours']}"></div>
            <div class="form-group"><label class="form-label">Resposta fora do horário</label><textarea name="auto_reply_off_hours" class="form-input" rows="3">{user['auto_reply_off_hours']}</textarea></div>
            <div class="form-group"><label class="form-label">WhatsApp Phone ID</label><input type="text" id="wp_phone_id" name="whatsapp_phone_id" class="form-input" value="{user['whatsapp_phone_id'] or ''}" placeholder="Cole aqui o Phone Number ID" autocomplete="off" style="background:#2a2a3a;border:2px solid #6c5ce7;color:#fff;cursor:text"></div>
            <div class="form-group"><label class="form-label">WhatsApp Token</label><input type="text" id="wp_token" name="whatsapp_token" class="form-input" value="{user['whatsapp_token'] or ''}" placeholder="Cole aqui o Access Token" autocomplete="off" style="background:#2a2a3a;border:2px solid #6c5ce7;color:#fff;cursor:text"></div>
            <button type="submit" class="btn btn-primary">Salvar</button></form>
            <script>
            document.addEventListener('DOMContentLoaded', function() {{
                ['wp_phone_id','wp_token'].forEach(function(id) {{
                    var el = document.getElementById(id);
                    if(el) {{
                        el.removeAttribute('readonly');
                        el.removeAttribute('disabled');
                        el.style.pointerEvents = 'auto';
                        el.style.userSelect = 'text';
                        el.addEventListener('click', function() {{ this.focus(); this.select(); }});
                    }}
                }});
            }});
            </script></div>
        <div><div class="card fade-in fade-in-2" style="margin-bottom:24px"><div class="card-header"><span class="card-title">Webhook URL</span></div>
            <p style="color:var(--text2);font-size:14px;margin-bottom:12px">Configure no Meta Business:</p>
            <div style="background:var(--bg4);padding:12px 16px;border-radius:var(--radius-sm);font-family:var(--mono);font-size:13px;word-break:break-all;color:var(--accent2)">{webhook_url}</div>
            <p style="color:var(--text3);font-size:12px;margin-top:8px">Token: <code style="color:var(--accent2)">{WHATSAPP_VERIFY_TOKEN}</code></p></div>
        <div class="card fade-in fade-in-3"><div class="card-header"><span class="card-title">Mídias suportadas</span></div>
            <div style="color:var(--text2);font-size:14px;line-height:1.8">
                <p>✅ <strong style="color:var(--text)">Texto</strong> — lê e responde normalmente</p>
                <p>✅ <strong style="color:var(--text)">Áudio</strong> — transcreve com Groq/Whisper e responde</p>
                <p>✅ <strong style="color:var(--text)">Imagens</strong> — analisa com Claude Vision</p>
                <p>✅ <strong style="color:var(--text)">PDFs</strong> — extrai texto e interpreta</p>
                <p>✅ <strong style="color:var(--text)">Localização</strong> — recebe e processa</p>
                <p>✅ <strong style="color:var(--text)">Contatos</strong> — recebe dados do contato</p>
                <p>✅ <strong style="color:var(--text)">Stickers/Reações</strong> — registra</p>
            </div></div></div></div></div>"""
    return base_html("Configurações", content, dict(user))


# ─── BILLING ───────────────────────────────────────────────────
@app.route("/dashboard/billing")
@login_required
def billing():
    user = g.user; db = get_db()
    plan = PLANS.get(user["plan"], PLANS["starter"])
    payments = db.execute("SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user["id"],)).fetchall()
    payment_rows = ""
    for p in payments:
        p_date = (p["created_at"] or "")[:10]
        p_plan = PLANS.get(p["plan"], {}).get("name", p["plan"])
        p_cls = "badge-green" if p["status"]=="approved" else "badge-orange" if p["status"]=="pending" else "badge-red"
        p_label = {"approved":"Aprovado","pending":"Pendente","rejected":"Rejeitado"}.get(p["status"], p["status"])
        payment_rows += f'<tr><td>{p_date}</td><td>R$ {p["amount"]:.2f}</td><td>{p_plan}</td><td><span class="badge {p_cls}">{p_label}</span></td></tr>'

    plans_html = ""
    for key, p in PLANS.items():
        is_current = key == user["plan"]
        popular = "popular" if key == "pro" else ""
        btn = '<span class="badge badge-green" style="font-size:13px;padding:8px 20px">Plano atual</span>' if is_current else f'<a href="/api/mercadopago/create-preference?plan={key}" class="btn btn-primary btn-block">Assinar →</a>'
        feats = {"starter":["500 msgs/mês","Áudio+Imagem+PDF","Base de conhecimento","Painel conversas"],"pro":["2.000 msgs/mês","Tudo do Starter","Respostas rápidas","CRM básico","Suporte prioritário"],"business":["10.000 msgs/mês","Tudo do Pro","Múltiplos números","API personalizada","Gerente de conta"]}
        fl = "".join(f"<li>{f}</li>" for f in feats.get(key,[]))
        plans_html += f'<div class="plan-card {popular}"><div class="plan-name">{p["name"]}</div><div class="plan-price">R$ {p["price"]:.0f}<small>/mês</small></div><div class="plan-desc">{p["desc"]}</div><ul class="plan-features">{fl}</ul>{btn}</div>'

    status_map = {"active":"Ativo","trial":"Período de teste","inactive":"Inativo","cancelled":"Cancelado"}
    cls_map = {"active":"badge-green","trial":"badge-orange","inactive":"badge-red","cancelled":"badge-red"}

    content = f"""<div class="container"><div class="page-header fade-in"><h1>Plano e Pagamento 💳</h1></div>
        <div class="card fade-in" style="margin-bottom:32px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px">
            <div><div style="font-size:13px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px">Plano atual</div>
                <div style="font-size:24px;font-weight:700;margin-top:4px">{plan['name']} <span class="badge {cls_map.get(user['plan_status'],'badge-orange')}">{status_map.get(user['plan_status'],user['plan_status'])}</span></div>
                <div style="color:var(--text2);margin-top:4px">R$ {plan['price']:.0f}/mês · {user['msgs_used']}/{user['msgs_limit']} mensagens</div></div>
            <a href="#plans" class="btn btn-primary">Alterar plano</a></div></div>
        <div id="plans" class="grid-3 fade-in fade-in-1">{plans_html}</div>
        <div class="card fade-in fade-in-2"><div class="card-header"><span class="card-title">Histórico de pagamentos</span></div>
            {'<div class="table-wrap"><table><thead><tr><th>Data</th><th>Valor</th><th>Plano</th><th>Status</th></tr></thead><tbody>'+payment_rows+'</tbody></table></div>' if payments else '<div class="empty-state"><div class="icon">📋</div><h3>Nenhum pagamento</h3></div>'}</div></div>"""
    return base_html("Pagamento", content, dict(user))


# ─── MERCADO PAGO ──────────────────────────────────────────────
@app.route("/api/mercadopago/create-preference")
@login_required
def mp_create_preference():
    plan_key = request.args.get("plan","starter")
    plan = PLANS.get(plan_key)
    if not plan: return jsonify({"error":"Plano inválido"}), 400
    user = g.user
    try:
        import mercadopago
        sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)
        pref = sdk.preference().create({"items":[{"title":f"Atende.AI — {plan['name']}","quantity":1,"unit_price":plan["price"],"currency_id":"BRL"}],
            "payer":{"email":user["email"],"name":user["name"]},
            "back_urls":{"success":f"{BASE_URL}/api/mercadopago/callback?status=success&plan={plan_key}","failure":f"{BASE_URL}/api/mercadopago/callback?status=failure&plan={plan_key}","pending":f"{BASE_URL}/api/mercadopago/callback?status=pending&plan={plan_key}"},
            "auto_return":"approved","notification_url":f"{BASE_URL}/api/mercadopago/webhook","external_reference":f"user_{user['id']}_plan_{plan_key}_{int(time.time())}","statement_descriptor":"ATENDE.AI"})
        checkout_url = pref["response"].get("sandbox_init_point", pref["response"].get("init_point",""))
        if checkout_url: return redirect(checkout_url)
        return redirect("/dashboard/billing?error=Erro ao criar pagamento")
    except ImportError:
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Checkout Simulado</title>
        <style>body{{font-family:'DM Sans',sans-serif;background:#0a0a0f;color:#e8e6e3;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
        .box{{background:#12121a;padding:40px;border-radius:16px;max-width:400px;text-align:center;border:1px solid rgba(255,255,255,0.1)}}
        .price{{font-size:36px;font-weight:700;color:#a29bfe;margin:16px 0}}.btn{{display:inline-block;padding:14px 32px;background:#6c5ce7;color:white;border-radius:8px;text-decoration:none;font-weight:600}}</style></head>
        <body><div class="box"><h2>Checkout Simulado</h2><p style="color:#9b97a0">Plano {plan['name']}</p>
        <div class="price">R$ {plan['price']:.0f}<small style="font-size:14px;color:#9b97a0">/mês</small></div>
        <p style="color:#9b97a0;font-size:13px;margin-bottom:24px">SDK não instalado. Simulação de teste.</p>
        <a href="{BASE_URL}/api/mercadopago/callback?status=success&plan={plan_key}&simulated=1" class="btn">Simular aprovação ✓</a><br><br>
        <a href="/dashboard/billing" style="color:#9b97a0;font-size:13px">← Voltar</a></div></body></html>"""
    except Exception as e:
        return redirect(f"/dashboard/billing?error={str(e)}")

@app.route("/api/mercadopago/callback")
@login_required
def mp_callback():
    status = request.args.get("status",""); plan_key = request.args.get("plan","starter")
    plan = PLANS.get(plan_key, PLANS["starter"]); user = g.user; db = get_db()
    if status == "success":
        pid = request.args.get("payment_id", f"sim_{int(time.time())}")
        db.execute("UPDATE users SET plan=?,plan_status='active',msgs_limit=?,msgs_used=0 WHERE id=?", (plan_key, plan["msgs"], user["id"]))
        db.execute("INSERT INTO payments (user_id,mp_payment_id,amount,status,plan) VALUES (?,?,?,?,?)", (user["id"],pid,plan["price"],"approved",plan_key))
        db.commit()
    return redirect("/dashboard/billing")

@app.route("/api/mercadopago/webhook", methods=["POST"])
def mp_webhook():
    data = request.json or {}
    if data.get("type") == "payment":
        pid = data.get("data",{}).get("id")
        if pid:
            try:
                import mercadopago
                sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)
                payment = sdk.payment().get(pid)["response"]
                ext = payment.get("external_reference",""); parts = ext.split("_")
                if len(parts) >= 4:
                    uid = int(parts[1]); pk = parts[3]; plan = PLANS.get(pk)
                    db_c = sqlite3.connect(DATABASE); db_c.row_factory = sqlite3.Row
                    if payment.get("status") == "approved" and plan:
                        db_c.execute("UPDATE users SET plan=?,plan_status='active',msgs_limit=?,msgs_used=0 WHERE id=?", (pk,plan["msgs"],uid))
                        db_c.execute("INSERT INTO payments (user_id,mp_payment_id,amount,status,plan) VALUES (?,?,?,?,?)", (uid,str(pid),payment.get("transaction_amount",0),"approved",pk))
                    db_c.commit(); db_c.close()
            except Exception as e: print(f"MP webhook error: {e}")
    return jsonify({"status":"ok"}), 200


# ─── API ───────────────────────────────────────────────────────
@app.route("/api/conversations/<int:conv_id>/messages")
@login_required
def api_conv_messages(conv_id):
    db = get_db()
    conv = db.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conv_id, g.user["id"])).fetchone()
    if not conv: return jsonify({"error":"Não encontrada"}), 404
    messages = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (conv_id,)).fetchall()
    return jsonify({"customer_phone":conv["customer_phone"],"customer_name":conv["customer_name"],"messages":[dict(m) for m in messages]})


@app.route("/api/conversations")
@login_required
def api_conversations_list():
    db = get_db()
    convos = db.execute("""SELECT c.id, c.customer_phone, c.customer_name, c.last_message_at,
        (SELECT content FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) as last_msg,
        (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id) as msg_count
        FROM conversations c WHERE c.user_id=? ORDER BY c.last_message_at DESC""", (g.user["id"],)).fetchall()
    return jsonify({"conversations": [dict(c) for c in convos]})


# ─── WHATSAPP WEBHOOK ─────────────────────────────────────────
@app.route("/webhook/whatsapp/<int:user_id>", methods=["GET","POST"])
def whatsapp_webhook(user_id):
    if request.method == "GET":
        if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == WHATSAPP_VERIFY_TOKEN:
            return request.args.get("hub.challenge",""), 200
        return "Forbidden", 403

    data = request.json or {}
    try:
        db_conn = sqlite3.connect(DATABASE); db_conn.row_factory = sqlite3.Row
        user = db_conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user: db_conn.close(); return jsonify({"status":"user not found"}), 404

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    sender_phone = msg.get("from", "")
                    
                    # Check blocked
                    blocked = db_conn.execute("SELECT id FROM blocked_contacts WHERE user_id=? AND phone=?", (user_id, sender_phone)).fetchone()
                    if blocked: continue

                    # Process media (TEXT, AUDIO, IMAGE, PDF, LOCATION, etc.)
                    media_result = process_whatsapp_media(msg, user["whatsapp_token"])

                    if not media_result["content"]: continue

                    # Find or create conversation
                    conv = db_conn.execute("SELECT * FROM conversations WHERE user_id=? AND customer_phone=? AND status='active'", (user_id, sender_phone)).fetchone()
                    if not conv:
                        contact_name = ""
                        contacts = value.get("contacts", [])
                        if contacts: contact_name = contacts[0].get("profile",{}).get("name","")
                        db_conn.execute("INSERT INTO conversations (user_id,customer_phone,customer_name) VALUES (?,?,?)", (user_id, sender_phone, contact_name))
                        db_conn.commit()
                        conv = db_conn.execute("SELECT * FROM conversations WHERE user_id=? AND customer_phone=? AND status='active'", (user_id, sender_phone)).fetchone()

                    # Save message
                    db_conn.execute("INSERT INTO messages (conversation_id,sender,content,msg_type,media_url) VALUES (?,?,?,?,?)",
                        (conv["id"], "customer", media_result["content"], media_result["type"], media_result.get("media_path","")))
                    db_conn.execute("UPDATE conversations SET last_message_at=datetime('now') WHERE id=?", (conv["id"],))

                    if conv["is_human_takeover"]: db_conn.commit(); continue

                    # Generate AI response using the description (clean text for the AI)
                    ai_input = media_result.get("description", media_result["content"])
                    ai_response = generate_ai_response(user, conv["id"], ai_input, db_conn)

                    db_conn.execute("INSERT INTO messages (conversation_id,sender,content,msg_type) VALUES (?,?,?,?)", (conv["id"],"bot",ai_response,"text"))
                    db_conn.execute("UPDATE users SET msgs_used=msgs_used+1 WHERE id=?", (user_id,))
                    db_conn.commit()

                    send_whatsapp_message(user["whatsapp_phone_id"], user["whatsapp_token"], sender_phone, ai_response)
        db_conn.close()
    except Exception as e:
        print(f"Webhook error: {e}")
    return jsonify({"status":"ok"}), 200


def generate_ai_response(user, conversation_id, message, db_conn):
    history = list(reversed(db_conn.execute("SELECT sender,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 10", (conversation_id,)).fetchall()))
    kb_items = db_conn.execute("SELECT title,content FROM knowledge_base WHERE user_id=? LIMIT 20", (user["id"],)).fetchall()
    qr_items = db_conn.execute("SELECT shortcut,content FROM quick_replies WHERE user_id=? LIMIT 20", (user["id"],)).fetchall()
    
    kb_context = "\n".join([f"- {i['title']}: {i['content']}" for i in kb_items])
    qr_context = "\n".join([f"- /{q['shortcut']}: {q['content']}" for q in qr_items])
    
    tone_map = {"profissional":"Profissional mas acessível.","descontraido":"Descontraído, com emojis moderados.","formal":"Formal e respeitoso.","amigavel":"Amigável e caloroso."}
    
    system_prompt = f"""{user['ai_system_prompt']}

Tom: {tone_map.get(user['ai_tone'],'Profissional.')}

INFORMAÇÕES DO NEGÓCIO:
{kb_context or 'Nenhuma info cadastrada.'}

RESPOSTAS RÁPIDAS DISPONÍVEIS:
{qr_context or 'Nenhuma.'}

REGRAS:
- Responda de forma breve (máx 3 parágrafos curtos)
- Não invente informações sobre produtos ou preços
- Se não souber, diga que vai verificar
- Horário: {user['business_hours']}
- Se o cliente enviar áudio, você receberá a transcrição
- Se o cliente enviar imagem, você receberá a descrição da imagem
- Se o cliente enviar PDF, você receberá o texto extraído
"""

    api_messages = [{"role":"assistant" if h["sender"]=="bot" else "user","content":h["content"]} for h in history]
    api_messages.append({"role":"user","content":message})

    api_key = get_setting("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import requests as req
            resp = req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":api_key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":"claude-sonnet-4-20250514","max_tokens":500,"system":system_prompt,"messages":api_messages}, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                tokens_in = result.get("usage",{}).get("input_tokens",0)
                tokens_out = result.get("usage",{}).get("output_tokens",0)
                cost = (tokens_in * 3 / 1000000) + (tokens_out * 15 / 1000000)
                db_conn.execute("INSERT INTO api_usage_log (user_id,api_name,tokens_in,tokens_out,cost_estimate) VALUES (?,?,?,?,?)",
                    (user["id"],"anthropic",tokens_in,tokens_out,cost))
                return result["content"][0]["text"]
        except Exception as e: print(f"AI error: {e}")

    return user["ai_greeting"] or "Olá! Obrigado por entrar em contato. Como posso ajudar?"


def send_whatsapp_message(phone_id, token, to, message):
    print(f"\n[WA SEND] Tentando enviar para {to}...")
    print(f"[WA SEND] Phone ID: {phone_id}")
    print(f"[WA SEND] Token: {token[:20]}... ({len(token)} chars)")
    if not phone_id or not token:
        print(f"[WA SEND] ERRO: Phone ID ou Token vazio!")
        return
    try:
        import requests as req
        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
        print(f"[WA SEND] URL: {url}")
        print(f"[WA SEND] Para: {to}")
        print(f"[WA SEND] Mensagem: {message[:80]}...")
        resp = req.post(url, headers=headers, json=payload, timeout=15)
        print(f"[WA SEND] Status: {resp.status_code}")
        print(f"[WA SEND] Resposta: {resp.text[:500]}")
        if resp.status_code != 200:
            print(f"[WA SEND] ERRO! Verifique o token e Phone ID")
    except Exception as e:
        print(f"[WA SEND] EXCEÇÃO: {e}")


# ═══════════════════════════════════════════════════════════════
#  PAINEL ADMINISTRATIVO (DONO DO SISTEMA)
# ═══════════════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    error = ""
    client_ip = request.remote_addr or "unknown"
    if request.method == "POST":
        if not check_rate_limit(client_ip):
            error = "Muitas tentativas. Aguarde 5 minutos."
        elif request.form.get("email") == ADMIN_EMAIL and request.form.get("password") == ADMIN_PASSWORD:
            reset_login_attempts(client_ip)
            session["is_admin"] = True
            return redirect("/admin")
        else:
            record_login_attempt(client_ip)
            error = "Credenciais inválidas."
    alert = f'<div class="alert alert-error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Admin — atendente.online</title><link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{GLOBAL_CSS}</style></head><body>
<div class="auth-container"><div class="auth-card" style="border-top:3px solid var(--red)">
    <div style="text-align:center;margin-bottom:24px"><img src="data:image/png;base64,{LOGO_NAV_B64}" alt="atendente.online" style="height:50px"><span class="admin-badge" style="margin-left:8px;vertical-align:middle">ADMIN</span></div>
    <h2>Painel Administrativo</h2>{alert}
    <form method="POST">
    <div class="form-group"><label class="form-label">Email admin</label><input type="email" name="email" class="form-input" required></div>
    <div class="form-group"><label class="form-label">Senha</label><input type="password" name="password" class="form-input" required></div>
    <button type="submit" class="btn btn-primary btn-block btn-lg" style="background:var(--red)">Entrar no Admin</button></form>
</div></div></body></html>"""

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")


# ─── ADMIN DASHBOARD ──────────────────────────────────────────
@app.route("/admin")
@admin_required
def admin_dashboard():
    s = get_admin_stats()
    profit = s["mrr"] - s["total_api_cost"]

    content = f"""<div class="container">
        <div class="page-header fade-in"><h1>Dashboard Administrativo 🏢</h1><p>Visão geral do seu SaaS</p></div>
        
        <div class="grid-5 fade-in fade-in-1">
            <div class="metric-card"><div style="font-size:24px">👥</div><div class="metric-value">{s['total_users']}</div><div class="metric-label">Clientes totais</div>
                <div class="metric-trend trend-up">+{s['new_users_today']} hoje</div></div>
            <div class="metric-card"><div style="font-size:24px">✅</div><div class="metric-value" style="color:var(--green2)">{s['active_users']}</div><div class="metric-label">Assinaturas ativas</div></div>
            <div class="metric-card"><div style="font-size:24px">⏳</div><div class="metric-value" style="color:var(--orange)">{s['trial_users']}</div><div class="metric-label">Em trial</div></div>
            <div class="metric-card"><div style="font-size:24px">💰</div><div class="metric-value" style="color:var(--green2)">R$ {s['mrr']:.0f}</div><div class="metric-label">MRR (receita mensal)</div></div>
            <div class="metric-card"><div style="font-size:24px">📊</div><div class="metric-value" style="color:var(--accent2)">R$ {s['total_revenue']:.0f}</div><div class="metric-label">Receita total</div></div>
        </div>

        <div class="grid-4 fade-in fade-in-2">
            <div class="stat-card"><div class="stat-icon stat-icon-green">💬</div><div class="stat-value">{s['total_conversations']}</div><div class="stat-label">Conversas totais</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-blue">📨</div><div class="stat-value">{s['total_messages']}</div><div class="stat-label">Mensagens totais</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-orange">📨</div><div class="stat-value">{s['msgs_today']}</div><div class="stat-label">Mensagens hoje</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-red">💸</div><div class="stat-value">US$ {s['total_api_cost']:.2f}</div><div class="stat-label">Custo total de API</div></div>
        </div>

        <div class="grid-2 fade-in fade-in-3">
            <div class="card">
                <div class="card-header"><span class="card-title">Distribuição por plano</span></div>
                <table><thead><tr><th>Plano</th><th>Ativos</th><th>Receita/mês</th></tr></thead><tbody>
                {''.join(f'<tr><td><span class="badge badge-purple">{PLANS[k]["name"]}</span></td><td>{s["by_plan"].get(k,0)}</td><td>R$ {s["by_plan"].get(k,0) * PLANS[k]["price"]:.0f}</td></tr>' for k in PLANS)}
                <tr style="font-weight:700"><td>Total</td><td>{s['active_users']}</td><td>R$ {s['mrr']:.0f}</td></tr>
                </tbody></table>
            </div>
            <div class="card">
                <div class="card-header"><span class="card-title">Saúde do negócio</span></div>
                <div style="padding:16px 0">
                    <div style="display:flex;justify-content:space-between;margin-bottom:16px"><span style="color:var(--text2)">Taxa de conversão trial→pago</span>
                        <strong>{(s['active_users']/max(s['total_users'],1)*100):.0f}%</strong></div>
                    <div style="display:flex;justify-content:space-between;margin-bottom:16px"><span style="color:var(--text2)">Ticket médio</span>
                        <strong>R$ {(s['mrr']/max(s['active_users'],1)):.0f}</strong></div>
                    <div style="display:flex;justify-content:space-between;margin-bottom:16px"><span style="color:var(--text2)">Custo API / cliente</span>
                        <strong>US$ {(s['total_api_cost']/max(s['active_users'],1)):.2f}</strong></div>
                    <div style="display:flex;justify-content:space-between;margin-bottom:16px"><span style="color:var(--text2)">Lucro estimado (MRR - API)</span>
                        <strong style="color:{'var(--green2)' if profit > 0 else 'var(--red)'}">R$ {profit:.0f}</strong></div>
                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text2)">Clientes inativos</span>
                        <strong style="color:var(--red)">{s['inactive_users']}</strong></div>
                </div>
            </div>
        </div>
    </div>"""
    return admin_html("Admin Dashboard", content)


# ─── ADMIN: CLIENTES ──────────────────────────────────────────
@app.route("/admin/users")
@admin_required
def admin_users():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    rows = ""
    for u in users:
        status_cls = {"active":"badge-green","trial":"badge-orange","inactive":"badge-red","cancelled":"badge-red"}.get(u["plan_status"],"badge-orange")
        status_txt = {"active":"Ativo","trial":"Trial","inactive":"Inativo","cancelled":"Cancelado"}.get(u["plan_status"],u["plan_status"])
        stats = get_user_stats(u["id"])
        plan_name = PLANS.get(u['plan'], {}).get('name', u['plan'])
        rows += f"""<tr>
            <td><strong>{u['name']}</strong><br><span style="color:var(--text3);font-size:12px">{u['email']}</span></td>
            <td>{u['company'] or '—'}</td>
            <td><span class="badge badge-purple">{plan_name}</span></td>
            <td><span class="badge {status_cls}">{status_txt}</span></td>
            <td>{u['msgs_used']}/{u['msgs_limit']}</td>
            <td>{stats['conversations']}</td>
            <td style="font-size:12px;color:var(--text3)">{(u['created_at'] or '')[:10]}</td>
            <td style="font-size:12px;color:var(--text3)">{(u['last_login'] or 'Nunca')[:10]}</td>
            <td>
                <form method="POST" action="/admin/users/{u['id']}/toggle" style="display:inline">
                    <button type="submit" class="btn {'btn-danger' if u['is_active'] else 'btn-success'} btn-sm">{'Desativar' if u['is_active'] else 'Ativar'}</button>
                </form>
            </td></tr>"""

    content = f"""<div class="container"><div class="page-header"><h1>Clientes ({len(users)})</h1><p>Todos os clientes cadastrados no sistema</p></div>
        <div class="card"><div class="table-wrap"><table><thead><tr><th>Cliente</th><th>Empresa</th><th>Plano</th><th>Status</th><th>Msgs</th><th>Conversas</th><th>Cadastro</th><th>Último login</th><th>Ação</th></tr></thead>
        <tbody>{rows}</tbody></table></div></div></div>"""
    return admin_html("Clientes", content)


@app.route("/admin/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def admin_toggle_user(uid):
    db = get_db()
    user = db.execute("SELECT is_active FROM users WHERE id=?", (uid,)).fetchone()
    if user:
        new_status = 0 if user["is_active"] else 1
        db.execute("UPDATE users SET is_active=? WHERE id=?", (new_status, uid))
        db.commit()
    return redirect("/admin/users")


# ─── ADMIN: PAGAMENTOS ────────────────────────────────────────
@app.route("/admin/payments")
@admin_required
def admin_payments():
    db = get_db()
    payments = db.execute("""SELECT p.*, u.name, u.email FROM payments p 
        JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC LIMIT 100""").fetchall()
    
    total_approved = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM payments WHERE status='approved'").fetchone()["s"]
    total_pending = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM payments WHERE status='pending'").fetchone()["s"]
    count_approved = db.execute("SELECT COUNT(*) as c FROM payments WHERE status='approved'").fetchone()["c"]

    rows = ""
    for p in payments:
        p_date = (p['created_at'] or '')[:16]
        p_plan = PLANS.get(p['plan'], {}).get('name', p['plan'])
        p_cls = 'badge-green' if p['status']=='approved' else 'badge-orange' if p['status']=='pending' else 'badge-red'
        p_label = {"approved":"Aprovado","pending":"Pendente","rejected":"Rejeitado"}.get(p['status'], p['status'])
        rows += f"""<tr><td>{p_date}</td><td><strong>{p['name']}</strong><br><span style="color:var(--text3);font-size:12px">{p['email']}</span></td>
        <td><span class="badge badge-purple">{p_plan}</span></td><td>R$ {p['amount']:.2f}</td>
        <td><span class="badge {p_cls}">{p_label}</span></td>
        <td style="font-size:12px;color:var(--text3)">{p['mp_payment_id'] or '—'}</td></tr>"""

    content = f"""<div class="container"><div class="page-header"><h1>Pagamentos 💰</h1><p>Histórico de todas as transações</p></div>
        <div class="grid-4" style="margin-bottom:32px">
            <div class="stat-card"><div class="stat-icon stat-icon-green">✅</div><div class="stat-value">R$ {total_approved:.0f}</div><div class="stat-label">Total recebido</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-orange">⏳</div><div class="stat-value">R$ {total_pending:.0f}</div><div class="stat-label">Pendente</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-blue">🧾</div><div class="stat-value">{count_approved}</div><div class="stat-label">Pagamentos aprovados</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-purple">💳</div><div class="stat-value">{len(payments)}</div><div class="stat-label">Total transações</div></div>
        </div>
        <div class="card"><div class="card-header"><span class="card-title">Todas as transações</span></div>
        <div class="table-wrap"><table><thead><tr><th>Data</th><th>Cliente</th><th>Plano</th><th>Valor</th><th>Status</th><th>ID MP</th></tr></thead>
        <tbody>{rows}</tbody></table></div></div></div>"""
    return admin_html("Pagamentos", content)


# ─── ADMIN: USO DE API ────────────────────────────────────────
@app.route("/admin/usage")
@admin_required
def admin_usage():
    db = get_db()
    # Per-user usage
    usage = db.execute("""SELECT u.name, u.email, u.plan, u.msgs_used, u.msgs_limit,
        COALESCE(SUM(a.tokens_in),0) as total_tokens_in, COALESCE(SUM(a.tokens_out),0) as total_tokens_out,
        COALESCE(SUM(a.cost_estimate),0) as total_cost, COUNT(a.id) as api_calls
        FROM users u LEFT JOIN api_usage_log a ON u.id = a.user_id
        GROUP BY u.id ORDER BY total_cost DESC""").fetchall()

    rows = ""
    for u in usage:
        plan_name = PLANS.get(u['plan'], {}).get('name', u['plan'])
        plan_price = PLANS.get(u['plan'], {}).get('price', 0)
        is_healthy = plan_price > u['total_cost'] * 5.5
        health_color = 'var(--green2)' if is_healthy else 'var(--red)'
        health_label = 'Saudável' if is_healthy else 'Atenção'
        rows += f"""<tr><td><strong>{u['name']}</strong><br><span style="color:var(--text3);font-size:12px">{u['email']}</span></td>
        <td><span class="badge badge-purple">{plan_name}</span></td>
        <td>{u['msgs_used']}/{u['msgs_limit']}</td><td>{u['api_calls']}</td>
        <td>{u['total_tokens_in']:,}</td><td>{u['total_tokens_out']:,}</td>
        <td><strong>US$ {u['total_cost']:.4f}</strong></td>
        <td style="color:{health_color}">{health_label}</td></tr>"""

    total_cost = sum(u['total_cost'] for u in usage)
    total_calls = sum(u['api_calls'] for u in usage)

    content = f"""<div class="container"><div class="page-header"><h1>Uso de API 📊</h1><p>Monitoramento de custos por cliente</p></div>
        <div class="grid-4" style="margin-bottom:32px">
            <div class="stat-card"><div class="stat-icon stat-icon-red">💸</div><div class="stat-value">US$ {total_cost:.2f}</div><div class="stat-label">Custo total de API</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-blue">🔄</div><div class="stat-value">{total_calls}</div><div class="stat-label">Chamadas de API</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-purple">📉</div><div class="stat-value">US$ {(total_cost/max(len(usage),1)):.3f}</div><div class="stat-label">Custo médio/cliente</div></div>
            <div class="stat-card"><div class="stat-icon stat-icon-green">💰</div><div class="stat-value">US$ {(total_cost/max(total_calls,1)):.4f}</div><div class="stat-label">Custo médio/chamada</div></div>
        </div>
        <div class="card"><div class="card-header"><span class="card-title">Uso por cliente</span></div>
        <div class="table-wrap"><table><thead><tr><th>Cliente</th><th>Plano</th><th>Msgs</th><th>Chamadas API</th><th>Tokens in</th><th>Tokens out</th><th>Custo</th><th>Saúde</th></tr></thead>
        <tbody>{rows}</tbody></table></div></div></div>"""
    return admin_html("Uso de API", content)


# ─── ADMIN: LOGS ──────────────────────────────────────────────
@app.route("/admin/logs")
@admin_required
def admin_logs():
    db = get_db()
    recent_users = db.execute("SELECT name,email,created_at,plan FROM users ORDER BY created_at DESC LIMIT 20").fetchall()
    recent_payments = db.execute("SELECT p.*,u.name FROM payments p JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC LIMIT 20").fetchall()
    
    user_rows = ""
    for u in recent_users:
        pn = PLANS.get(u["plan"], {}).get("name", u["plan"])
        user_rows += f'<tr><td style="color:var(--text3);font-size:12px">{(u["created_at"] or "")[:16]}</td><td>👤 Novo cadastro</td><td><strong>{u["name"]}</strong> ({u["email"]}) — Plano {pn}</td></tr>'
    pay_rows = "".join(f'<tr><td style="color:var(--text3);font-size:12px">{(p["created_at"] or "")[:16]}</td><td>💳 Pagamento</td><td><strong>{p["name"]}</strong> — R$ {p["amount"]:.2f} ({p["status"]})</td></tr>' for p in recent_payments)

    content = f"""<div class="container"><div class="page-header"><h1>Logs do Sistema 📋</h1><p>Atividade recente</p></div>
        <div class="grid-2">
            <div class="card"><div class="card-header"><span class="card-title">Últimos cadastros</span></div>
            <div class="table-wrap"><table><thead><tr><th>Data</th><th>Evento</th><th>Detalhes</th></tr></thead><tbody>{user_rows}</tbody></table></div></div>
            <div class="card"><div class="card-header"><span class="card-title">Últimos pagamentos</span></div>
            <div class="table-wrap"><table><thead><tr><th>Data</th><th>Evento</th><th>Detalhes</th></tr></thead><tbody>{pay_rows}</tbody></table></div></div>
        </div></div>"""
    return admin_html("Logs", content)


# ─── ADMIN: CONFIGURAÇÕES DE API ───────────────────────────────
@app.route("/admin/api-settings", methods=["GET", "POST"])
@admin_required
def admin_api_settings():
    msg = ""
    if request.method == "POST":
        keys = ["ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "MERCADOPAGO_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN"]
        for key in keys:
            value = request.form.get(key, "").strip()
            if value:
                set_setting(key, value)
        base_url = request.form.get("BASE_URL", "").strip()
        if base_url:
            set_setting("BASE_URL", base_url)
        msg = '<div class="alert alert-success">Configurações de API salvas!</div>'

    anthropic_key = get_setting("ANTHROPIC_API_KEY")
    groq_key = get_setting("GROQ_API_KEY")
    openai_key = get_setting("OPENAI_API_KEY")
    mp_token = get_setting("MERCADOPAGO_ACCESS_TOKEN")
    wa_verify = get_setting("WHATSAPP_VERIFY_TOKEN", "meu_token_verificacao")
    base_url = get_setting("BASE_URL", "http://localhost:8080")

    def mask(key):
        if not key: return ""
        return key[:8] + "..." + key[-4:] if len(key) > 16 else key[:4] + "..."

    content = f"""<div class="container">
        <div class="page-header fade-in"><h1>Configurações de API 🔑</h1><p>Configure todas as chaves de API do sistema</p></div>
        {msg}
        <form method="POST">
        <div class="grid-2">
            <div class="card fade-in fade-in-1">
                <div class="card-header"><span class="card-title">IA e Transcrição</span></div>
                <div class="form-group">
                    <label class="form-label">Anthropic API Key (Claude — IA)</label>
                    <input type="text" name="ANTHROPIC_API_KEY" class="form-input" placeholder="sk-ant-..." value="" autocomplete="off"
                        style="background:#2a2a3a;border:2px solid {'var(--green)' if anthropic_key else 'var(--red)'}">
                    <small style="color:var(--text3)">{'✅ Configurada: ' + mask(anthropic_key) if anthropic_key else '❌ Não configurada — IA usa respostas padrão'}</small>
                </div>
                <div class="form-group">
                    <label class="form-label">Groq API Key (Transcrição de áudio)</label>
                    <input type="text" name="GROQ_API_KEY" class="form-input" placeholder="gsk_..." value="" autocomplete="off"
                        style="background:#2a2a3a;border:2px solid {'var(--green)' if groq_key else 'var(--red)'}">
                    <small style="color:var(--text3)">{'✅ Configurada: ' + mask(groq_key) if groq_key else '❌ Não configurada — áudios não serão transcritos'}</small>
                </div>
                <div class="form-group">
                    <label class="form-label">OpenAI API Key (fallback áudio)</label>
                    <input type="text" name="OPENAI_API_KEY" class="form-input" placeholder="sk-..." value="" autocomplete="off"
                        style="background:#2a2a3a;border:1px solid rgba(255,255,255,0.08)">
                    <small style="color:var(--text3)">{'✅ Configurada: ' + mask(openai_key) if openai_key else '⬜ Opcional — usado se Groq falhar'}</small>
                </div>
            </div>
            <div class="card fade-in fade-in-2">
                <div class="card-header"><span class="card-title">Pagamentos e WhatsApp</span></div>
                <div class="form-group">
                    <label class="form-label">Mercado Pago Access Token</label>
                    <input type="text" name="MERCADOPAGO_ACCESS_TOKEN" class="form-input" placeholder="APP_USR-..." value="" autocomplete="off"
                        style="background:#2a2a3a;border:2px solid {'var(--green)' if mp_token and mp_token != 'TEST-xxxx' else 'var(--orange)'}">
                    <small style="color:var(--text3)">{'✅ Configurado: ' + mask(mp_token) if mp_token and mp_token != 'TEST-xxxx' else '⚠️ Não configurado — checkout simulado'}</small>
                </div>
                <div class="form-group">
                    <label class="form-label">WhatsApp Verify Token</label>
                    <input type="text" name="WHATSAPP_VERIFY_TOKEN" class="form-input" value="{wa_verify}" autocomplete="off"
                        style="background:#2a2a3a;border:1px solid rgba(255,255,255,0.08)">
                    <small style="color:var(--text3)">Token usado na verificação do webhook do Meta</small>
                </div>
                <div class="form-group">
                    <label class="form-label">URL Base do Sistema</label>
                    <input type="text" name="BASE_URL" class="form-input" value="{base_url}" autocomplete="off"
                        style="background:#2a2a3a;border:1px solid rgba(255,255,255,0.08)">
                    <small style="color:var(--text3)">URL pública (ex: https://seudominio.com ou URL do ngrok)</small>
                </div>
            </div>
        </div>
        <button type="submit" class="btn btn-primary btn-lg">Salvar todas as configurações</button>
        </form>

        <div class="card fade-in fade-in-3" style="margin-top:32px">
            <div class="card-header"><span class="card-title">Onde conseguir as chaves</span></div>
            <div style="color:var(--text2);font-size:14px;line-height:2">
                <p><strong style="color:var(--text)">Anthropic (Claude):</strong> <a href="https://console.anthropic.com/settings/keys" target="_blank">console.anthropic.com/settings/keys</a></p>
                <p><strong style="color:var(--text)">Groq (Áudio):</strong> <a href="https://console.groq.com/keys" target="_blank">console.groq.com/keys</a> — praticamente grátis!</p>
                <p><strong style="color:var(--text)">OpenAI (Fallback):</strong> <a href="https://platform.openai.com/api-keys" target="_blank">platform.openai.com/api-keys</a></p>
                <p><strong style="color:var(--text)">Mercado Pago:</strong> <a href="https://www.mercadopago.com.br/developers/panel/app" target="_blank">mercadopago.com.br/developers/panel/app</a></p>
            </div>
        </div>
    </div>"""
    return admin_html("Configurações de API", content)


# ─── ADMIN: EXPORTAR DADOS ────────────────────────────────────
@app.route("/admin/export/<string:data_type>")
@admin_required
def admin_export(data_type):
    db = get_db()
    if data_type == "users":
        rows = db.execute("SELECT id,name,email,company,phone,plan,plan_status,msgs_used,msgs_limit,created_at,last_login FROM users").fetchall()
        csv = "id,nome,email,empresa,telefone,plano,status,msgs_usadas,msgs_limite,cadastro,ultimo_login\n"
        csv += "\n".join(",".join(str(r[k]) for k in r.keys()) for r in rows)
    elif data_type == "payments":
        rows = db.execute("SELECT p.id,u.name,u.email,p.amount,p.status,p.plan,p.mp_payment_id,p.created_at FROM payments p JOIN users u ON p.user_id=u.id").fetchall()
        csv = "id,cliente,email,valor,status,plano,mp_id,data\n"
        csv += "\n".join(",".join(str(r[k]) for k in r.keys()) for r in rows)
    else:
        return "Tipo inválido", 400
    
    output = io.BytesIO(csv.encode("utf-8"))
    output.seek(0)
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name=f"atendeia_{data_type}_{datetime.now().strftime('%Y%m%d')}.csv")


# ═══════════════════════════════════════════════════════════════
#  INIT & RUN
# ═══════════════════════════════════════════════════════════════

# Inicializa o banco sempre (necessário para gunicorn no Railway)
init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print("\n" + "="*60)
    print("  ⚡ ATENDE.AI v2.0 — Sistema rodando!")
    print(f"  📍 Painel cliente: http://localhost:{port}")
    print(f"  🔐 Painel admin:   http://localhost:{port}/admin/login")
    print(f"  👤 Admin login:    {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print("  ─────────────────────────────────────")
    print(f"  🤖 Claude (IA):    {'✅ Configurada' if get_setting('ANTHROPIC_API_KEY') else '❌ Configure no admin → APIs'}")
    print(f"  🎤 Groq (Áudio):   {'✅ Configurada' if get_setting('GROQ_API_KEY') else '❌ Configure no admin → APIs'}")
    print(f"  🎤 OpenAI (Áudio): {'✅ Configurada' if get_setting('OPENAI_API_KEY') else '⬜ Opcional (fallback)'}")
    print("="*60 + "\n")
    app.run(debug=True, host="0.0.0.0", port=port)
