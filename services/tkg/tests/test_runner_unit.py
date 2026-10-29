"""Unit tests for runner helpers and the CLI loop (no network, no database)."""
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tkg.processing import runner
from tkg.processing.runner import pacific_day_start_utc, LockError

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
import tkg_dev  # noqa: E402


def test_pacific_day_boundary_in_summer_time():
    # 2026-10-28 09:00 UTC = 02:00 PDT (UTC-7) on 28 Oct -> the Pacific day began 28 Oct 07:00 UTC
    assert pacific_day_start_utc(datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 28, 7, 0, tzinfo=timezone.utc)
    # 06:59 UTC is still 27 Oct 23:59 Pacific
    assert pacific_day_start_utc(datetime(2026, 10, 28, 6, 59, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 27, 7, 0, tzinfo=timezone.utc)


def test_pacific_day_boundary_in_standard_time():
    # after the November switch Pacific is UTC-8
    assert pacific_day_start_utc(datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 12, 1, 8, 0, tzinfo=timezone.utc)


def test_budget_never_exceeds_remaining_daily_quota(monkeypatch):
    monkeypatch.setattr(runner.settings, "TKG_LLM_RPD", 100)
    monkeypatch.setattr(runner.settings, "TKG_LLM_SAFETY_FRACTION", 0.8)
    monkeypatch.setattr(runner, "llm_requests_today", lambda session, now=None: 95)
    assert runner.compute_request_budget(None) == 1                   # default floor(0.8*100/48) = 1
    assert runner.compute_request_budget(None, max_requests=50) == 5  # explicit cap still limited by the day
    monkeypatch.setattr(runner, "llm_requests_today", lambda session, now=None: 0)
    assert runner.compute_request_budget(None) == 1
    assert runner.compute_request_budget(None, max_requests=50) == 50
    monkeypatch.setattr(runner, "llm_requests_today", lambda session, now=None: 100)
    assert runner.compute_request_budget(None, max_requests=50) == 0


def test_rpd_and_rpm_have_no_defaults():
    from tkg.settings import TKGSettings
    for name in ("TKG_LLM_RPD", "TKG_LLM_RPM", "TKG_LLM_MODEL"):
        assert TKGSettings.model_fields[name].is_required()
    assert TKGSettings.model_fields["TKG_LLM_MAX_OUTPUT_TOKENS"].default == 4096
    assert TKGSettings.model_fields["TKG_SCORE_K"].default == 3.0
    assert TKGSettings.model_fields["TKG_CONFIDENCE_C"].default == 4.0


class FakeConn:
    def __init__(self, name, log, fail=False):
        self.name, self.log, self.fail = name, log, fail

    def execute(self, stmt, params=None):
        self.log.append((self.name, str(stmt)))
        if self.fail:
            raise RuntimeError("lock query failed")
        return SimpleNamespace(scalar=lambda: True)


def test_lock_helpers_run_on_the_connection_they_are_given():
    log = []
    conn = FakeConn("lock-conn", log)
    assert runner.acquire_advisory_lock(conn, 7) is True
    assert runner.release_advisory_lock(conn, 7) is True
    assert [n for n, _ in log] == ["lock-conn", "lock-conn"]
    assert "pg_try_advisory_lock" in log[0][1] and "pg_advisory_unlock" in log[1][1]


def test_lock_error_is_fatal_not_fail_open():
    with pytest.raises(RuntimeError):
        runner.acquire_advisory_lock(FakeConn("c", [], fail=True), 7)


def test_cmd_process_exits_nonzero_on_lock_error(monkeypatch):
    def boom(**kw):
        raise LockError("Advisory lock check failed (OperationalError); refusing to run")

    monkeypatch.setattr(tkg_dev, "run_processing", boom)
    args = SimpleNamespace(target="test", dry_run=False, max_requests=None, no_llm=False)
    with pytest.raises(SystemExit) as exc:
        tkg_dev.cmd_process(args)
    assert exc.value.code == 1


def test_run_loop_survives_failures_and_stops_cleanly(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_run(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("iteration failed")
        return {"status": "completed", "run_id": "r", "articles_seen": 0, "processed": 0, "events_created": 0,
                "failed": 0, "llm_requests": 0, "rate_limited": False, "snapshots_written": 46, "duration_s": 0.1}

    clock = {"t": 0.0}

    def fake_sleep(seconds):
        clock["t"] += seconds
        if calls["n"] >= 2:
            raise KeyboardInterrupt        # Ctrl+C while waiting for the next iteration

    class Dummy:
        def close(self): pass
        def dispose(self): pass

    monkeypatch.setattr(tkg_dev, "run_processing", fake_run)
    monkeypatch.setattr(tkg_dev.time, "sleep", fake_sleep)
    monkeypatch.setattr(tkg_dev.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(tkg_dev, "get_engine", lambda url: Dummy())
    monkeypatch.setattr(tkg_dev, "get_session_factory", lambda engine: (lambda: Dummy()))
    args = SimpleNamespace(target="test", interval_minutes=0.01, initial_delay_minutes=0.0, max_requests=None)
    tkg_dev.cmd_run_loop(args)             # returns normally on KeyboardInterrupt
    assert calls["n"] >= 2                 # the first iteration failed, the loop kept going
