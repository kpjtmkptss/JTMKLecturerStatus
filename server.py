#!/usr/bin/env python3
"""
JTMK PTSS Lecturer Status Dashboard — Backend Server
Python 3 + SQLite (no installation required)
Run: python3 server.py
"""

import http.server
import json
import sqlite3
import os
import hashlib
import secrets
import urllib.parse
from datetime import datetime

DB_FILE = "jtmk.db"
PORT = 8000
SESSIONS = {}  # token -> {username, role, lecturerId}

# ─────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS lecturers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            staff_id        TEXT NOT NULL UNIQUE,
            username        TEXT NOT NULL UNIQUE,
            password        TEXT NOT NULL,
            programme       TEXT NOT NULL CHECK(programme IN ('SAD','NS')),
            status          TEXT NOT NULL DEFAULT 'available',
            remarks         TEXT DEFAULT '',
            status_updated_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            text    TEXT NOT NULL,
            date    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lecturer_id INTEGER NOT NULL,
            task_order  INTEGER NOT NULL,
            task_text   TEXT NOT NULL,
            FOREIGN KEY(lecturer_id) REFERENCES lecturers(id) ON DELETE CASCADE
        );
    """)

    # Seed lecturers if empty
    c.execute("SELECT COUNT(*) FROM lecturers")
    if c.fetchone()[0] == 0:
        seed = [
            ("Ts. Dr. Ahmad Fadzli Nizam",    "PTSS-JTMK-001", "Ahmad",    "Ahmad",    "SAD", "class",      ""),
            ("Pn. Norlia Binti Hassin",        "PTSS-JTMK-002", "Norlia",   "Norlia",   "SAD", "available",  ""),
            ("En. Shahrul Nizam Abd Halim",    "PTSS-JTMK-003", "Shahrul",  "Shahrul",  "SAD", "outstation", "Conference KL"),
            ("Pn. Siti Aishah Binti Sulaiman", "PTSS-JTMK-004", "Siti",     "Siti",     "SAD", "class",      ""),
            ("En. Mohd Hafizuddin Zakaria",    "PTSS-JTMK-005", "Mohd",     "Mohd",     "SAD", "leave",      "MC"),
            ("Dr. Faridah Binti Jalil",        "PTSS-JTMK-006", "Faridah",  "Faridah",  "NS",  "class",      ""),
            ("En. Zulkifli Bin Othman",        "PTSS-JTMK-007", "Zulkifli", "Zulkifli", "NS",  "available",  ""),
            ("Pn. Hasniza Binti Abd Rahim",    "PTSS-JTMK-008", "Hasniza",  "Hasniza",  "NS",  "outstation", ""),
            ("En. Muhamad Azwan Mansor",       "PTSS-JTMK-009", "Muhamad",  "Muhamad",  "NS",  "class",      ""),
            ("Pn. Rosnah Binti Mohamad",       "PTSS-JTMK-010", "Rosnah",   "Rosnah",   "NS",  "available",  ""),
        ]
        for row in seed:
            c.execute("""INSERT INTO lecturers (name,staff_id,username,password,programme,status,remarks)
                         VALUES (?,?,?,?,?,?,?)""", row)

    conn.commit()
    conn.close()
    print(f"[DB] Database ready: {DB_FILE}")

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def ts_now():
    return datetime.now().strftime("%d %b %Y %H:%M")

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def json_response(handler, data, status=200):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", len(body))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
    handler.end_headers()
    handler.wfile.write(body)

def read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    return json.loads(handler.rfile.read(length)) if length else {}

def get_token(handler):
    auth = handler.headers.get("Authorization", "")
    return auth.replace("Bearer ", "").strip()

def require_auth(handler):
    return SESSIONS.get(get_token(handler))

def require_admin(handler):
    s = require_auth(handler)
    return s if s and s["role"] == "admin" else None

# ─────────────────────────────────────────
# REQUEST HANDLER
# ─────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.date_time_string()}] {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")

        # Serve static files
        if path == "" or path == "/":
            self.serve_file("index.html", "text/html")
        elif path == "/jtmk.png":
            self.serve_file("jtmk.png", "image/png")

        # API
        elif path == "/api/lecturers":
            self.api_get_lecturers()
        elif path == "/api/announcements":
            self.api_get_announcements()
        elif path == "/api/tasks":
            self.api_get_tasks()
        else:
            json_response(self, {"error": "Not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")

        if path == "/api/login":
            self.api_login()
        elif path == "/api/logout":
            self.api_logout()
        elif path == "/api/lecturers":
            self.api_add_lecturer()
        elif path == "/api/announcements":
            self.api_add_announcement()
        elif path == "/api/tasks":
            self.api_save_tasks()
        else:
            json_response(self, {"error": "Not found"}, 404)

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        parts = path.split("/")

        if len(parts) == 4 and parts[2] == "lecturers":
            lid = int(parts[3])
            if len(parts) == 4:
                self.api_update_lecturer(lid)
        elif len(parts) == 4 and parts[2] == "lecturers" and parts[3].isdigit():
            self.api_update_lecturer(int(parts[3]))
        else:
            # Try pattern /api/lecturers/<id>
            if path.startswith("/api/lecturers/"):
                try:
                    lid = int(path.split("/")[-1])
                    self.api_update_lecturer(lid)
                except:
                    json_response(self, {"error": "Bad request"}, 400)
            else:
                json_response(self, {"error": "Not found"}, 404)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")

        if path.startswith("/api/lecturers/"):
            try:
                lid = int(path.split("/")[-1])
                self.api_delete_lecturer(lid)
            except:
                json_response(self, {"error": "Bad request"}, 400)
        elif path.startswith("/api/announcements/"):
            try:
                aid = int(path.split("/")[-1])
                self.api_delete_announcement(aid)
            except:
                json_response(self, {"error": "Bad request"}, 400)
        else:
            json_response(self, {"error": "Not found"}, 404)

    # ── Static file server ──
    def serve_file(self, filename, mime):
        if not os.path.exists(filename):
            json_response(self, {"error": "File not found"}, 404)
            return
        with open(filename, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    # ─────────────────────────────────────
    # AUTH
    # ─────────────────────────────────────
    def api_login(self):
        body = read_body(self)
        username = body.get("username", "").strip()
        password = body.get("password", "").strip()

        # Admin
        if username == "admin" and password == "admin123":
            token = secrets.token_hex(32)
            SESSIONS[token] = {"role": "admin", "username": "admin", "name": "Admin", "lecturerId": None}
            return json_response(self, {"token": token, "role": "admin", "name": "Admin"})

        # Lecturer
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM lecturers WHERE username=? AND password=?",
            (username, password)
        ).fetchone()
        conn.close()
        if row:
            token = secrets.token_hex(32)
            SESSIONS[token] = {"role": "lecturer", "username": username, "name": row["name"], "lecturerId": row["id"]}
            return json_response(self, {"token": token, "role": "lecturer", "name": row["name"], "lecturerId": row["id"]})

        json_response(self, {"error": "Invalid username or password"}, 401)

    def api_logout(self):
        token = get_token(self)
        SESSIONS.pop(token, None)
        json_response(self, {"ok": True})

    # ─────────────────────────────────────
    # LECTURERS
    # ─────────────────────────────────────
    def api_get_lecturers(self):
        if not require_auth(self):
            return json_response(self, {"error": "Unauthorized"}, 401)
        conn = get_db()
        rows = conn.execute("SELECT * FROM lecturers ORDER BY id").fetchall()
        conn.close()
        json_response(self, [dict(r) for r in rows])

    def api_add_lecturer(self):
        if not require_admin(self):
            return json_response(self, {"error": "Forbidden"}, 403)
        b = read_body(self)
        try:
            conn = get_db()
            conn.execute("""INSERT INTO lecturers (name,staff_id,username,password,programme,status,remarks)
                            VALUES (?,?,?,?,?,?,?)""",
                (b["name"], b["staffId"], b["username"], b["password"],
                 b["programme"], b.get("status","available"), b.get("remarks","")))
            conn.commit()
            lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            row = conn.execute("SELECT * FROM lecturers WHERE id=?", (lid,)).fetchone()
            conn.close()
            json_response(self, dict(row), 201)
        except Exception as e:
            json_response(self, {"error": str(e)}, 400)

    def api_update_lecturer(self, lid):
        session = require_auth(self)
        if not session:
            return json_response(self, {"error": "Unauthorized"}, 401)
        b = read_body(self)
        conn = get_db()
        row = conn.execute("SELECT * FROM lecturers WHERE id=?", (lid,)).fetchone()
        if not row:
            conn.close()
            return json_response(self, {"error": "Not found"}, 404)

        # Lecturer can only update their own status & remarks
        if session["role"] == "lecturer":
            if session["lecturerId"] != lid:
                conn.close()
                return json_response(self, {"error": "Forbidden"}, 403)
            status = b.get("status", row["status"])
            remarks = b.get("remarks", row["remarks"])
            status_updated_at = ts_now() if "status" in b else row["status_updated_at"]
            conn.execute("""UPDATE lecturers SET status=?, remarks=?, status_updated_at=? WHERE id=?""",
                         (status, remarks, status_updated_at, lid))
        else:
            # Admin full update
            status_updated_at = ts_now() if "status" in b and b["status"] != row["status"] else row["status_updated_at"]
            conn.execute("""UPDATE lecturers SET name=?,staff_id=?,username=?,password=?,
                            programme=?,status=?,remarks=?,status_updated_at=? WHERE id=?""",
                (b.get("name", row["name"]),
                 b.get("staffId", row["staff_id"]),
                 b.get("username", row["username"]),
                 b.get("password", row["password"]),
                 b.get("programme", row["programme"]),
                 b.get("status", row["status"]),
                 b.get("remarks", row["remarks"]),
                 status_updated_at, lid))
        conn.commit()
        updated = conn.execute("SELECT * FROM lecturers WHERE id=?", (lid,)).fetchone()
        conn.close()
        json_response(self, dict(updated))

    def api_delete_lecturer(self, lid):
        if not require_admin(self):
            return json_response(self, {"error": "Forbidden"}, 403)
        conn = get_db()
        conn.execute("DELETE FROM lecturers WHERE id=?", (lid,))
        conn.execute("DELETE FROM tasks WHERE lecturer_id=?", (lid,))
        conn.commit()
        conn.close()
        json_response(self, {"ok": True})

    # ─────────────────────────────────────
    # ANNOUNCEMENTS
    # ─────────────────────────────────────
    def api_get_announcements(self):
        if not require_auth(self):
            return json_response(self, {"error": "Unauthorized"}, 401)
        conn = get_db()
        rows = conn.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
        conn.close()
        json_response(self, [dict(r) for r in rows])

    def api_add_announcement(self):
        if not require_admin(self):
            return json_response(self, {"error": "Forbidden"}, 403)
        b = read_body(self)
        conn = get_db()
        conn.execute("INSERT INTO announcements (text,date) VALUES (?,?)", (b["text"], ts_now()))
        conn.commit()
        aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM announcements WHERE id=?", (aid,)).fetchone()
        conn.close()
        json_response(self, dict(row), 201)

    def api_delete_announcement(self, aid):
        if not require_admin(self):
            return json_response(self, {"error": "Forbidden"}, 403)
        conn = get_db()
        conn.execute("DELETE FROM announcements WHERE id=?", (aid,))
        conn.commit()
        conn.close()
        json_response(self, {"ok": True})

    # ─────────────────────────────────────
    # TASKS
    # ─────────────────────────────────────
    def api_get_tasks(self):
        if not require_auth(self):
            return json_response(self, {"error": "Unauthorized"}, 401)
        conn = get_db()
        rows = conn.execute("SELECT * FROM tasks ORDER BY lecturer_id, task_order").fetchall()
        conn.close()
        # Group by lecturer_id -> {lecturerId: [task_text,...]}
        result = {}
        for r in rows:
            lid = str(r["lecturer_id"])
            result.setdefault(lid, []).append(r["task_text"])
        json_response(self, result)

    def api_save_tasks(self):
        if not require_admin(self):
            return json_response(self, {"error": "Forbidden"}, 403)
        b = read_body(self)  # {lecturerId: [task,...]}
        lid = int(b["lecturerId"])
        task_list = b.get("tasks", [])[:5]
        conn = get_db()
        conn.execute("DELETE FROM tasks WHERE lecturer_id=?", (lid,))
        for i, t in enumerate(task_list):
            if t.strip():
                conn.execute("INSERT INTO tasks (lecturer_id,task_order,task_text) VALUES (?,?,?)", (lid, i+1, t.strip()))
        conn.commit()
        conn.close()
        json_response(self, {"ok": True})


if __name__ == "__main__":
    init_db()
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[SERVER] JTMK PTSS Dashboard running at http://localhost:{PORT}")
    print(f"[SERVER] Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Stopped.")
