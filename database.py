import sqlite3
import json
import uuid
import os
from datetime import datetime

DB_FILE = "meal_planner.db"

def init_db():
    # Ensure the database file is created with restricted permissions
    if not os.path.exists(DB_FILE):
        try:
            fd = os.open(DB_FILE, os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
    else:
        # If it already exists, ensure permissions are restricted
        os.chmod(DB_FILE, 0o600)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sessions
                 (id TEXT PRIMARY KEY, created_at TEXT, completed_at TEXT, is_complete INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, event_type TEXT, data TEXT, created_at TEXT,
                  FOREIGN KEY(session_id) REFERENCES sessions(id))''')
    conn.commit()
    conn.close()

def create_session():
    session_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)", (session_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return session_id

def log_event(session_id, event_type, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO logs (session_id, event_type, data, created_at) VALUES (?, ?, ?, ?)",
              (session_id, event_type, json.dumps(data), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def complete_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE sessions SET is_complete = 1, completed_at = ? WHERE id = ?", (datetime.now().isoformat(), session_id))
    conn.commit()
    conn.close()
