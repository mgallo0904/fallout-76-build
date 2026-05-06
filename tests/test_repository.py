from datetime import date, timedelta

from app.models import SourceRecord, SourceType
from app.services.db import get_conn
from app.services.repository import (
    get_build,
    latest_source_date_accessed,
    list_sources,
    upsert_source,
)


def test_latest_source_date_accessed_reflects_db_upsert():
    baseline = latest_source_date_accessed()
    future = baseline + timedelta(days=365)
    record = SourceRecord(
        id="test_future_source",
        source_name="Test Future Source",
        source_url="https://example.invalid/future",
        source_type=SourceType.community,
        date_accessed=future,
        relevant_patch="patch-future",
        summary="future-dated test source",
        reliability_score=0.5,
        notes="injected by test",
    )
    try:
        upsert_source(record)
        assert latest_source_date_accessed() >= future
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM source_records WHERE id=?", (record.id,))
            conn.commit()


def test_get_build_returns_none_for_corrupt_row():
    bad_id = "build-corrupt-row"
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO generated_builds (id, build_json, created_at) VALUES (?, ?, ?)",
            (bad_id, "{not valid json", date.today().isoformat()),
        )
        conn.commit()
    try:
        assert get_build(bad_id) is None
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM generated_builds WHERE id=?", (bad_id,))
            conn.commit()


def test_list_sources_returns_records():
    sources = list_sources()
    assert sources
    assert all(isinstance(s, SourceRecord) for s in sources)
