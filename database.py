import os
import sqlite3
import json
import uuid
import threading
import shutil
from datetime import datetime

DB_FILE = os.getenv("DB_PATH", "meal_planner.db")
BACKUP_FILE = DB_FILE + ".bak"
_local = threading.local()

def get_connection():
    """Get a thread-local persistent SQLite connection."""
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        # Switch to DELETE mode for better reliability in container volumes
        _local.conn.execute("PRAGMA journal_mode=DELETE")
    return _local.conn

def close_db():
    """Close the thread-local persistent SQLite connection."""
    if hasattr(_local, "conn"):
        try:
            _local.conn.close()
        except:
            pass
        del _local.conn

def backup_db():
    """Create a simple backup of the database file."""
    try:
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, BACKUP_FILE)
    except Exception as e:
        print(f"Backup failed: {e}")

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sessions
                 (id TEXT PRIMARY KEY, created_at TEXT, completed_at TEXT, is_complete INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, event_type TEXT, data TEXT, created_at TEXT,
                  FOREIGN KEY(session_id) REFERENCES sessions(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  session_id TEXT, 
                  ingredient_raw TEXT, 
                  ingredient_normalized TEXT, 
                  ingredient_final TEXT, 
                  source_recipe TEXT,
                  outcome TEXT, 
                  correction_made INTEGER DEFAULT 0,
                  created_at TEXT,
                  FOREIGN KEY(session_id) REFERENCES sessions(id))''')
    conn.commit()

def log_audit(session_id, raw, normalized, final, source, outcome, correction=0):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO audit_log 
                 (session_id, ingredient_raw, ingredient_normalized, ingredient_final, source_recipe, outcome, correction_made, created_at) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
              (session_id, raw, normalized, final, source, outcome, correction, datetime.now().isoformat()))
    conn.commit()

def create_session():
    session_id = str(uuid.uuid4())
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)", (session_id, datetime.now().isoformat()))
    conn.commit()
    return session_id

def log_event(session_id, event_type, data):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO logs (session_id, event_type, data, created_at) VALUES (?, ?, ?, ?)",
              (session_id, event_type, json.dumps(data), datetime.now().isoformat()))
    conn.commit()

def get_audit_logs(limit=200):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""SELECT id, session_id, ingredient_raw, ingredient_normalized, ingredient_final, source_recipe, outcome, correction_made, created_at 
                 FROM audit_log ORDER BY created_at DESC LIMIT ?""", (limit,))
    columns = [column[0] for column in c.description]
    results = []
    for row in c.fetchall():
        results.append(dict(zip(columns, row)))
    return results

def complete_session(session_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE sessions SET is_complete = 1, completed_at = ? WHERE id = ?", (datetime.now().isoformat(), session_id))
    conn.commit()
    backup_db()
