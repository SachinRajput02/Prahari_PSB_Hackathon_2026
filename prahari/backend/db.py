"""PRAHARI — SQLite data layer (zero-setup; swap DSN for PostgreSQL in prod)."""
import sqlite3
import json
import time
from pathlib import Path
from threading import Lock

DB = Path(__file__).parent / "prahari.db"
_lock = Lock()


def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with _lock, conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS identities(
            user_id TEXT PRIMARY KEY, name TEXT, kyc_status TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS devices(
            device_id TEXT PRIMARY KEY, first_seen REAL, trusted INTEGER);
        CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY, user_id TEXT, device_id TEXT, ip TEXT,
            created_at REAL, last_event_at REAL, ctq REAL);
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, user_id TEXT,
            ts REAL, ctq REAL, ml_trust REAL, decision TEXT, action TEXT,
            friction TEXT, reasons TEXT, signals TEXT, policy TEXT);
        CREATE TABLE IF NOT EXISTS links(
            user_id TEXT, attr_type TEXT, attr_value TEXT);
        """)


def insert_event(row: dict):
    with _lock, conn() as c:
        c.execute("""INSERT INTO events
            (session_id,user_id,ts,ctq,ml_trust,decision,action,friction,reasons,signals,policy)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
            row["session_id"], row["user_id"], time.time(), row["ctq"],
            row["ml_trust"], row["decision"], row["action"], row["friction"],
            json.dumps(row["reasons"]), json.dumps(row["signals"]),
            json.dumps(row["policy"])))


def upsert_session(sid, user_id, device_id, ip):
    now = time.time()
    with _lock, conn() as c:
        c.execute("""INSERT INTO sessions(id,user_id,device_id,ip,created_at,last_event_at,ctq)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET last_event_at=excluded.last_event_at""",
            (sid, user_id, device_id, ip, now, now, 99))


def touch_session(sid, ctq):
    with _lock, conn() as c:
        c.execute("UPDATE sessions SET last_event_at=?, ctq=? WHERE id=?",
                  (time.time(), ctq, sid))


def recent_events(limit=40):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def metrics():
    with conn() as c:
        rows = c.execute("SELECT decision, friction, ctq FROM events").fetchall()
    n = len(rows)
    if not n:
        return {"events": 0, "silent_pct": 0, "stepups": 0, "blocked": 0,
                "avg_ctq": 0, "friction_saved_pct": 0}
    silent = sum(1 for r in rows if r["decision"] == "silent")
    soft = sum(1 for r in rows if r["decision"] == "soft")
    hard = sum(1 for r in rows if r["decision"] == "hard")
    avg = sum(r["ctq"] for r in rows) / n
    return {
        "events": n,
        "silent_pct": round(100 * silent / n),
        "stepups": soft + hard,
        "blocked": hard,
        "avg_ctq": round(avg),
        # share of sessions that completed with zero friction
        "friction_saved_pct": round(100 * silent / n),
    }


def get_identity(user_id):
    with conn() as c:
        r = c.execute("SELECT * FROM identities WHERE user_id=?", (user_id,)).fetchone()
    return dict(r) if r else None


def all_links():
    with conn() as c:
        rows = c.execute("SELECT user_id, attr_type, attr_value FROM links").fetchall()
    return [dict(r) for r in rows]


def identities_in(user_ids):
    if not user_ids:
        return {}
    q = ",".join("?" * len(user_ids))
    with conn() as c:
        rows = c.execute(
            f"SELECT * FROM identities WHERE user_id IN ({q})", tuple(user_ids)).fetchall()
    return {r["user_id"]: dict(r) for r in rows}
