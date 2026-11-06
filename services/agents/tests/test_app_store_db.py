"""PgAppStore against the TEST database as finsight_app (marker db). Writes only rows with a unique test key and deletes them afterwards.
Skipped when APP_TEST_DATABASE_URL is not set or the app tables are not migrated (python -m finsight.migrate --target test)."""
import uuid

import pytest
from sqlalchemy import text

from finsight.data.app_store import PgAppStore, app_engine
from finsight.settings import SettingsError, get_settings

pytestmark = pytest.mark.db


@pytest.fixture()
def engine():
    try:
        eng = app_engine(get_settings(), "test")
        with eng.connect() as c:
            c.execute(text("SELECT 1 FROM app.sector_narratives LIMIT 1"))
            c.execute(text("SELECT 1 FROM app.fundamentals_cache LIMIT 1"))
    except (SettingsError, Exception) as exc:           # no URL, or not migrated
        pytest.skip(f"app TEST database not ready: {type(exc).__name__}")
    return eng


def test_sector_narrative_round_trip_and_first_write_wins(engine):
    store, key = PgAppStore(engine), f"test_sector_{uuid.uuid4().hex[:8]}"
    try:
        assert store.get_sector_narrative(key, "run1", "v1") is None
        store.put_sector_narrative(key, "run1", "v1", {"outlook": "negative", "key_chains": []}, "m")
        store.put_sector_narrative(key, "run1", "v1", {"outlook": "positive", "key_chains": []}, "m")          # same key: ignored
        assert store.get_sector_narrative(key, "run1", "v1") == {"outlook": "negative", "key_chains": []}
        assert store.get_sector_narrative(key, "run2", "v1") is None and store.get_sector_narrative(key, "run1", "v2") is None
        assert store.errors == 0
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM app.sector_narratives WHERE sector_id = :k"), {"k": key})


def test_fundamentals_round_trip_respects_the_ttl(engine):
    store, key = PgAppStore(engine), f"TEST:{uuid.uuid4().hex[:8]}"
    try:
        assert store.get_fundamentals(key, 24) is None
        store.put_fundamentals(key, {"metrics": {}, "latest_results_date": "2026-09-30"})
        assert store.get_fundamentals(key, 24)["latest_results_date"] == "2026-09-30"
        assert store.get_fundamentals(key, 0) is None                                           # older than a zero-hour TTL
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM app.fundamentals_cache WHERE security_id = :k"), {"k": key})


def test_a_failing_database_degrades_to_a_miss_and_counts_the_error():
    from sqlalchemy import create_engine
    store = PgAppStore(create_engine("postgresql+psycopg2://nobody:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}))
    assert store.get_sector_narrative("s", "r", "v") is None and store.get_fundamentals("x", 24) is None
    store.put_sector_narrative("s", "r", "v", {}, None)
    assert store.errors == 3
