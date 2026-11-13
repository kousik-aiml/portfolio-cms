"""SQLite storage layer.

Everything the owner can edit lives in the database:

* settings        - site title, theme, admin password hash, ...
* profile_fields  - one row per profile field (working value + published value)
* site_sections   - the sections shown on the website (order, title, visibility)
* custom_fields   - owner-defined extra fields attached to any section / the profile
* items           - every record (education, projects, custom-section entries ...)
                    stored as JSON so new fields never need a schema change
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS profile_fields (
    key               TEXT PRIMARY KEY,
    value             TEXT,
    visible           INTEGER NOT NULL DEFAULT 1,
    published_value   TEXT,
    published_visible INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS site_sections (
    key      TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    intro    TEXT NOT NULL DEFAULT '',
    kind     TEXT NOT NULL DEFAULT 'builtin',
    visible  INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL DEFAULT 0,
    layout   TEXT NOT NULL DEFAULT 'cards'
);
CREATE TABLE IF NOT EXISTS custom_fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uid         TEXT UNIQUE,
    key         TEXT NOT NULL,
    label       TEXT NOT NULL,
    type        TEXT NOT NULL,
    options     TEXT NOT NULL DEFAULT '[]',
    target      TEXT NOT NULL,
    help        TEXT NOT NULL DEFAULT '',
    show_public INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(target, key)
);
CREATE TABLE IF NOT EXISTS items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uid            TEXT UNIQUE NOT NULL,
    section        TEXT NOT NULL,
    data           TEXT NOT NULL DEFAULT '{}',
    published_data TEXT,
    status         TEXT NOT NULL DEFAULT 'draft',
    visible        INTEGER NOT NULL DEFAULT 1,
    position       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT,
    updated_at     TEXT,
    published_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_section ON items(section, position);
"""

REQUIRED_TABLES = {"settings", "profile_fields", "site_sections", "custom_fields", "items"}


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_uid():
    return uuid.uuid4().hex


def jdump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def jload(text, default=None):
    if text is None:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- connection

def connect(path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- settings

def get_setting(key, default=""):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value):
    get_db().execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def all_settings():
    return {r["key"]: r["value"] for r in get_db().execute("SELECT key,value FROM settings")}


# --------------------------------------------------------------------------- site sections

def site_sections(visible_only=False):
    sql = "SELECT * FROM site_sections"
    if visible_only:
        sql += " WHERE visible=1"
    sql += " ORDER BY position, key"
    return [dict(r) for r in get_db().execute(sql)]


def site_section(key):
    row = get_db().execute("SELECT * FROM site_sections WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------- items

def item_from_row(row):
    d = dict(row)
    d["data"] = jload(row["data"], {}) or {}
    d["published_data"] = jload(row["published_data"]) if row["published_data"] is not None else None
    d["dirty"] = row["status"] == "published" and row["data"] != row["published_data"]
    d["visible"] = bool(row["visible"])
    return d


def list_items(section):
    rows = get_db().execute(
        "SELECT * FROM items WHERE section=? ORDER BY position, id", (section,)
    ).fetchall()
    return [item_from_row(r) for r in rows]


def get_item(item_id):
    row = get_db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return item_from_row(row) if row else None


def get_item_by_uid(uid):
    row = get_db().execute("SELECT * FROM items WHERE uid=?", (uid,)).fetchone()
    return item_from_row(row) if row else None


def next_position(section):
    row = get_db().execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM items WHERE section=?", (section,)
    ).fetchone()
    return row["p"]


def create_item(section, data, publish=False, visible=True, uid=None, position=None):
    now = utcnow()
    text = jdump(data)
    cur = get_db().execute(
        "INSERT INTO items(uid,section,data,published_data,status,visible,position,created_at,updated_at,published_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            uid or new_uid(), section, text, text if publish else None,
            "published" if publish else "draft", 1 if visible else 0,
            next_position(section) if position is None else position,
            now, now, now if publish else None,
        ),
    )
    return cur.lastrowid


def save_item_data(item_id, data, publish=False):
    now = utcnow()
    text = jdump(data)
    if publish:
        get_db().execute(
            "UPDATE items SET data=?, published_data=?, status='published', updated_at=?, published_at=? WHERE id=?",
            (text, text, now, now, item_id),
        )
    else:
        get_db().execute("UPDATE items SET data=?, updated_at=? WHERE id=?", (text, now, item_id))


def publish_item(item_id):
    now = utcnow()
    get_db().execute(
        "UPDATE items SET published_data=data, status='published', published_at=?, updated_at=? WHERE id=?",
        (now, now, item_id),
    )


def unpublish_item(item_id):
    get_db().execute(
        "UPDATE items SET published_data=NULL, status='draft', updated_at=? WHERE id=?",
        (utcnow(), item_id),
    )


def set_positions(table, ids, id_column="id", extra_where="", extra_args=()):
    """Persist a new ordering: ids[0] gets position 0 and so on."""
    conn = get_db()
    for pos, ident in enumerate(ids):
        conn.execute(
            f"UPDATE {table} SET position=? WHERE {id_column}=? {extra_where}",
            (pos, ident, *extra_args),
        )
