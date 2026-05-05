from __future__ import annotations
import json
from pathlib import Path
from threading import Lock
from app.models import GeneratedBuild, PerkCard, SourceRecord
from app.services.db import get_conn

DATA_DIR = Path(__file__).resolve().parents[1] / 'data'
_SOURCE_SEED_LOCK = Lock()
_SOURCE_SEEDED = False


def load_perks() -> list[PerkCard]:
    raw = json.loads((DATA_DIR / 'perks.json').read_text(encoding='utf-8'))
    return [PerkCard.model_validate(x) for x in raw]


def load_sources_json() -> list[SourceRecord]:
    raw = json.loads((DATA_DIR / 'sources.json').read_text(encoding='utf-8'))
    return [SourceRecord.model_validate(x) for x in raw]


def seed_sources(force: bool = False) -> None:
    global _SOURCE_SEEDED
    if _SOURCE_SEEDED and not force:
        return
    with _SOURCE_SEED_LOCK:
        if _SOURCE_SEEDED and not force:
            return
        with get_conn() as conn:
            for s in load_sources_json():
                conn.execute(
                    '''INSERT OR REPLACE INTO source_records
                    (id, source_name, source_url, source_type, date_accessed, relevant_patch, summary, reliability_score, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (s.id, s.source_name, s.source_url, s.source_type.value, s.date_accessed.isoformat(), s.relevant_patch, s.summary, s.reliability_score, s.notes),
                )
            conn.commit()
        _SOURCE_SEEDED = True


def list_sources() -> list[SourceRecord]:
    seed_sources()
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM source_records ORDER BY reliability_score DESC').fetchall()
    return [SourceRecord.model_validate(dict(r)) for r in rows]


def save_build(build: GeneratedBuild) -> None:
    with get_conn() as conn:
        conn.execute('INSERT OR REPLACE INTO generated_builds (id, build_json, created_at) VALUES (?, ?, ?)',
                     (build.id, build.model_dump_json(), build.created_at.isoformat()))
        conn.commit()


def get_build(build_id: str) -> GeneratedBuild | None:
    with get_conn() as conn:
        row = conn.execute('SELECT build_json FROM generated_builds WHERE id=?', (build_id,)).fetchone()
    return GeneratedBuild.model_validate_json(row['build_json']) if row else None
