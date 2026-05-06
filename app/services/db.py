from __future__ import annotations
import sqlite3
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / 'db' / 'build_agent.db'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS source_records (
  id TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_type TEXT NOT NULL,
  date_accessed TEXT NOT NULL,
  relevant_patch TEXT,
  summary TEXT NOT NULL,
  reliability_score REAL NOT NULL,
  notes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generated_builds (
  id TEXT PRIMARY KEY,
  build_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
'''


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
