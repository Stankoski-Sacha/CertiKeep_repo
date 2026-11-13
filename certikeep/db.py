"""SQLite storage. One file (instance/certikeep.db), created on first run."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
-- which certificate types each worker must hold
CREATE TABLE IF NOT EXISTS requirements (
    worker_id   INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    cert_type   TEXT NOT NULL,
    PRIMARY KEY (worker_id, cert_type)
);
CREATE TABLE IF NOT EXISTS documents (
    id                INTEGER PRIMARY KEY,
    original_name     TEXT NOT NULL,
    stored_name       TEXT NOT NULL,
    mime_type         TEXT NOT NULL,
    uploaded_at       TEXT NOT NULL,
    uploaded_by       TEXT NOT NULL,
    -- what the AI said (kept unchanged for the audit trail)
    ai_json           TEXT,
    ai_model          TEXT,
    ai_readable       INTEGER NOT NULL DEFAULT 0,
    ai_error          TEXT,
    ai_latency_s      REAL,
    -- current values (AI suggestion, later corrected/confirmed by a person)
    worker_id         INTEGER REFERENCES workers(id) ON DELETE SET NULL,
    worker_name       TEXT,
    certificate_type  TEXT,
    issue_date        TEXT,
    expiry_date       TEXT,
    confidences       TEXT NOT NULL DEFAULT '{}',
    -- human confirmation = audit trail
    confirmed_by      TEXT,
    confirmed_at      TEXT,
    rejected          INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER,
    at           TEXT NOT NULL,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT ''
);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(document_id: int | None, actor: str, action: str, detail: str | dict = "") -> None:
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False)
    get_db().execute("INSERT INTO audit_log (document_id, at, actor, action, detail) VALUES (?,?,?,?,?)",
                     (document_id, now(), actor, action, detail))
