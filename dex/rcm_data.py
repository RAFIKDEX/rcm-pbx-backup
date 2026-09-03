"""Read-only accessors for existing RCM data used by DEX.

The legacy ``db.get_db`` helper changes the SQLite mode to 0666.  DEX never
calls it; these accessors open a read-only connection without changing file
permissions and return only the fields needed by provisioning.
"""

import sqlite3

import db


def _connect():
    conn = sqlite3.connect(db.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_extension(extension):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM extensions WHERE ext = ?", (str(extension),)).fetchone()
        return dict(row) if row else None


def get_active_extensions():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM extensions WHERE enabled = 1 ORDER BY ext").fetchall()
        return [dict(row) for row in rows]


def get_ldap_settings():
    with _connect() as conn:
        row = conn.execute("SELECT * FROM ldap_settings WHERE id = 1").fetchone()
        return dict(row) if row else None
