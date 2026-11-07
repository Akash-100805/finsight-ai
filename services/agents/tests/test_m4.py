"""M4: holdings validation, portfolio / search / run endpoints (async, concurrency, progress), run accounting, LangSmith redaction.
Stores, security master, LLM, prices: all in-memory fakes (the TEST-database stores are in test_m4_db.py)."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from finsight import api, services as svc, tracing
from finsight.core.holdings import MAX_HOLDINGS, OWNER_RE, validate_holdings, validate_name
from finsight.core.portfolio_scan import scan_portfolio
from finsight.flow.progress import STAGES
from finsight.graph import run_analysis
from finsight.schemas.state import AnalysisState, Holding
from tests.app_helpers import GOOD_ROWS, any_listed, lookup, make_services
from tests.flow_helpers import good_handler, llm_for, make_deps, sig
from tests.test_flow import PORT


def norm(s):
    return s


# ── holdings validation ──────────────────────────────────────────────────────────────────────────────────────────
def test_valid_holdings_pass_unchanged():
    clean, errors = validate_holdings(GOOD_ROWS, lookup)
    assert errors == [] and clean == GOOD_ROWS


def test_all_row_errors_are_reported_at_once():
    rows = [{"security_id": "NSE:AAA", "quantity": 0, "avg_cost": -1, "currency": "EUR"},                 # three problems in one row
            {"security_id": "NSE:NOPE", "quantity": 5, "avg_cost": 1, "currency": "INR"},                  # unknown
            {"security_id": "NSE:DEAD", "quantity": 5, "avg_cost": 1, "currency": "INR"},                  # inactive
            {"security_id": "NASDAQ:USX", "quantity": 5, "avg_cost": 1, "currency": "INR"},                # wrong currency
            {"security_id": "NSE:BBB", "quantity": "x", "avg_cost": 1, "currency": "INR"},                 # not a number
            {"security_id": "NSE:CCC", "quantity": 1, "avg_cost": 1, "currency": "INR", "colour": "red"},  # unknown field
            {"security_id": "NSE:CCC", "quantity": 1, "avg_cost": 1, "currency": "INR"},                   # valid, but...
            {"security_id": "NSE:CCC", "quantity": 2, "avg_cost": 1, "currency": "INR"},                   # ...a duplicate
            "not an object", {"quantity": 1, "avg_cost": 1, "currency": "INR"}]                            # missing id
    clean, errors = validate_holdings(rows, lookup)
    assert clean == []
    got = {(e["row"], e["field"]) for e in errors}
    assert {(0, "quantity"), (0, "avg_cost"), (0, "currency"), (1, "security_id"), (2, "security_id"), (3, "currency"), (4, "quantity"), (5, "colour"),
            (7, "security_id"), (8, None), (9, "security_id")} <= got
    assert any("trades in USD" in e["message"] for e in errors) and any("not an active" in e["message"] for e in errors)


def test_zero_cost_is_allowed_negative_quantity_is_not_and_the_limit_is_fifty():
    ok, errors = validate_holdings([{"security_id": "NSE:AAA", "quantity": 1, "avg_cost": 0, "currency": "INR"}], lookup)
    assert errors == [] and ok[0]["avg_cost"] == 0
    assert validate_holdings([{"security_id": "NSE:AAA", "quantity": -1, "avg_cost": 1, "currency": "INR"}], lookup)[1]
    many = [{"security_id": f"NSE:T{i}", "quantity": 1, "avg_cost": 1, "currency": "INR"} for i in range(MAX_HOLDINGS + 1)]
    errors = validate_holdings(many, any_listed)[1]
    assert errors == [{"row": None, "field": "holdings", "message": f"too many holdings ({MAX_HOLDINGS + 1}); at most {MAX_HOLDINGS}"}]
    assert validate_holdings(many[:MAX_HOLDINGS], any_listed)[1] == []
    for bad in (float("nan"), float("inf"), True):
        assert validate_holdings([{"security_id": "NSE:AAA", "quantity": bad, "avg_cost": 1, "currency": "INR"}], lookup)[1]


def test_names_and_owner_ids():
    assert validate_name("My portfolio") == [] and validate_name("") and validate_name(None) and validate_name("x" * 101)
    assert OWNER_RE.match("demo") and OWNER_RE.match("a.b-c_1") and not OWNER_RE.match("") and not OWNER_RE.match("a b") and not OWNER_RE.match("x" * 65)


def test_a_zero_average_cost_is_a_zero_return_not_a_division_by_zero():
    r = scan_portfolio([Holding(ticker="A", quantity=2, average_cost=0.0, current_price=10.0), Holding(ticker="B", quantity=1, average_cost=10.0, current_price=10.0)])
    assert r.holding_metrics["A"].unrealized_return_pct == 0.0 and r.holding_metrics["A"].weight == pytest.approx(2 / 3)


# ── portfolio endpoints ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RUNS_DIR", tmp_path)
    svc.set_services(make_services(lambda portfolio, progress: None))
    return TestClient(api.app)


def create(client, name="Core", owner="demo", rows=None):
    return client.post("/api/portfolios", json={"owner_id": owner, "name": name, "holdings": GOOD_ROWS if rows is None else rows})


def test_create_list_get_update_delete_and_default(client):
    a = create(client, "Core")
    assert a.status_code == 201 and a.json()["is_default"] is True and len(a.json()["holdings"]) == 2
    b = create(client, "Second")
    assert b.json()["is_default"] is False
    listed = client.get("/api/portfolios?owner_id=demo").json()["portfolios"]
    assert [p["name"] for p in listed] == ["Core", "Second"] and listed[0]["n_holdings"] == 2 and "holdings" not in listed[0]
    assert client.get("/api/portfolios?owner_id=other").json()["portfolios"] == []
    pid = a.json()["portfolio_id"]
    assert client.get(f"/api/portfolios/{pid}").json()["name"] == "Core"
    put = client.put(f"/api/portfolios/{pid}", json={"name": "Renamed", "holdings": [GOOD_ROWS[0]]})
    assert put.status_code == 200 and put.json()["name"] == "Renamed" and len(put.json()["holdings"]) == 1
    assert client.put(f"/api/portfolios/{pid}", json={"name": "Second"}).status_code == 422                # name taken
    assert client.post(f"/api/portfolios/{b.json()['portfolio_id']}/default").status_code == 200
    assert client.delete(f"/api/portfolios/{b.json()['portfolio_id']}").status_code == 200              # the default goes: the other becomes default
    assert client.get(f"/api/portfolios/{pid}").json()["is_default"] is True
    assert client.delete(f"/api/portfolios/{pid}").status_code == 200 and client.get(f"/api/portfolios/{pid}").status_code == 404
    assert client.get("/api/portfolios/not-a-uuid").status_code == 404 and client.delete("/api/portfolios/not-a-uuid").status_code == 404


def test_import_reports_every_error_at_once_and_stores_nothing(client):
    bad = {"owner_id": "demo", "name": "Bad", "holdings": [{"security_id": "NSE:NOPE", "quantity": 0, "avg_cost": 1, "currency": "INR"}, {"security_id": "NSE:AAA", "quantity": 1, "avg_cost": 1, "currency": "USD"}]}
    r = client.post("/api/portfolios/import", json=bad)
    assert r.status_code == 422 and r.json()["detail"] == "validation failed" and len(r.json()["errors"]) == 3
    assert client.get("/api/portfolios?owner_id=demo").json()["portfolios"] == []
    assert client.post("/api/portfolios/import", json={"owner_id": "demo", "name": "", "holdings": "x"}).status_code == 422
    assert client.post("/api/portfolios/import", content="not json").status_code == 422
    good = client.post("/api/portfolios/import", json={"name": "Imported", "holdings": GOOD_ROWS})                  # owner defaults to demo
    assert good.status_code == 201 and good.json()["owner_id"] == "demo"
    assert create(client, "Imported").status_code == 422                                                         # duplicate name
    assert create(client, "Bad owner", owner="no spaces").status_code == 422


def test_more_than_fifty_holdings_are_rejected(client):
    many = [{"security_id": f"NSE:T{i}", "quantity": 1, "avg_cost": 1, "currency": "INR"} for i in range(51)]
    svc._SERVICES.lookup = any_listed
    r = create(client, "Big", rows=many)
    assert r.status_code == 422 and "at most 50" in json.dumps(r.json())


def test_the_existing_samples_can_be_imported(client):
    svc._SERVICES.lookup = any_listed
    names = [s["name"] for s in client.get("/samples").json()]
    assert names
    for n in names:
        r = client.post("/api/portfolios/import-sample", json={"owner_id": "demo", "sample": n})
        assert r.status_code == 201, (n, r.text)
        assert all(h["currency"] in ("INR", "USD") and h["quantity"] > 0 and h["security_id"].count(":") == 1 for h in r.json()["holdings"])
    mixed = next(p for p in client.get("/api/portfolios?owner_id=demo").json()["portfolios"] if p["name"] == "sample: mixed_us")
    cur = {h["security_id"]: h["currency"] for h in client.get(f"/api/portfolios/{mixed['portfolio_id']}").json()["holdings"]}
    assert cur["NASDAQ:NVDA"] == "USD" and cur["NSE:RELIANCE"] == "INR"
    assert client.post("/api/portfolios/import-sample", json={"sample": "nope"}).status_code == 404


def test_portfolio_endpoints_say_503_when_the_app_database_is_not_migrated(client):
    svc.set_services(make_services(lambda p, pr: None, portfolios=False))
    svc._SERVICES.app_db = {"target": "main", "migrated": False, "note": "the app tables are not migrated on MAIN"}
    r = client.get("/api/portfolios?owner_id=demo")
    assert r.status_code == 503 and "not migrated" in r.json()["detail"]
    assert client.post("/analyze/demo").status_code == 503


def test_security_search(client):
    r = client.get("/api/securities/search?q=alpha").json()
    assert [x["security_id"] for x in r["results"]] == ["NSE:AAA"]
    assert client.get("/api/securities/search?q=nsE:").json()["results"]
    assert client.get("/api/securities/search?q=").status_code == 422 and client.get("/api/securities/search?q=a&limit=0").status_code == 422
    assert "NSE:DEAD" not in json.dumps(client.get("/api/securities/search?q=ltd").json())


# ── asynchronous runs ────────────────────────────────────────────────────────────────────────────────────────────
def wait_done(client, run_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["status"] in ("done", "failed"):
            return r
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def real_run_fn(**deps_kw):
    def run_fn(portfolio, progress):
        return run_analysis(portfolio, deps=make_deps(**deps_kw), progress=progress)
    return run_fn


def services_with(run_fn, tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(api, "RUNS_DIR", tmp_path)
    s = make_services(run_fn, api.finish_run, look=any_listed if kw.pop("any", False) else lookup, **kw)
    svc.set_services(s)
    return s


def test_post_returns_202_at_once_and_the_run_finishes_with_stages_and_a_result(client, tmp_path, monkeypatch):
    services_with(real_run_fn(returns={"NSE:AAA": -0.4}, bench_return=0.1, sentiments={"NSE:BBB": sig(0.0, 5), "NSE:CCC": sig(0.0, 5)}), tmp_path, monkeypatch)
    pid = create(client, "Run me", rows=[{"security_id": f"NSE:{t}", "quantity": 10, "avg_cost": 50.0, "currency": "INR"} for t in ("AAA", "BBB", "CCC")]).json()["portfolio_id"]
    r = client.post("/api/runs", json={"portfolio_id": pid})
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["status_url"] == f"/api/runs/{r.json()['run_id']}"
    done = wait_done(client, r.json()["run_id"])
    assert done["status"] == "done" and done["error"] is None and done["result"]["run_id"] == r.json()["run_id"] and done["result"]["disclaimer"]
    stages = {s["name"]: s for s in done["stages"]}
    assert [s["name"] for s in done["stages"]] == STAGES
    assert all(stages[n]["status"] == "done" and stages[n]["detail"] and stages[n]["finished_at"] for n in STAGES if n != "conflict_resolver")
    assert stages["conflict_resolver"]["status"] == "skipped"                                         # nobody's votes conflicted
    assert stages["load_holdings"]["detail"] == "3 of 3 holdings resolved, 0 excluded" and "flagged" in stages["fusion"]["detail"]
    assert stages["stage2"]["llm_calls"] >= 1 and stages["synthesis"]["llm_calls"] == 1
    assert done["metadata"]["accounting"]["llm_calls"] >= 2 and done["stage"] == "compliance"
    assert client.get("/api/runs").json()["runs"][0]["run_id"] == r.json()["run_id"] and "result" not in client.get("/api/runs").json()["runs"][0]
    assert client.get(f"/api/runs?owner_id=nobody").json()["runs"] == []
    assert (tmp_path / f"{r.json()['run_id']}.json").exists()


def test_a_running_run_exposes_its_current_stage(client, tmp_path, monkeypatch):
    gate, inside = threading.Event(), threading.Event()

    def run_fn(portfolio, progress):
        progress({"node": "load_holdings", "phase": "start", "stage_index": 0, "ts": time.time()})
        progress({"node": "load_holdings", "phase": "end", "stage_index": 0, "status": "ok", "detail": "2 of 2 holdings resolved, 0 excluded", "seconds": 0.1, "ts": time.time()})
        progress({"node": "prices_and_fx", "phase": "start", "stage_index": 1, "ts": time.time()})
        inside.set()
        gate.wait(5)
        return real_run_fn(returns={"NSE:AAA": 0.1})(portfolio, lambda ev: None)
    services_with(run_fn, tmp_path, monkeypatch)
    pid = create(client).json()["portfolio_id"]
    rid = client.post("/api/runs", json={"portfolio_id": pid}).json()["run_id"]
    assert inside.wait(5)
    mid = client.get(f"/api/runs/{rid}").json()
    assert mid["status"] == "running" and mid["stage"] == "prices_and_fx" and mid["stage_index"] == 1 and "result" not in mid
    assert mid["stages"][0]["status"] == "done" and mid["stages"][1]["status"] == "running" and mid["stages"][2]["status"] == "pending"
    gate.set()
    assert wait_done(client, rid)["status"] == "done"


def test_concurrency_one_per_owner_two_in_total_otherwise_429(client, tmp_path, monkeypatch):
    gate, started = threading.Event(), threading.Semaphore(0)

    def run_fn(portfolio, progress):
        started.release()
        gate.wait(10)
        return real_run_fn(returns={"NSE:AAA": 0.1})(portfolio, lambda ev: None)
    services_with(run_fn, tmp_path, monkeypatch)
    pids = {o: create(client, "P", owner=o).json()["portfolio_id"] for o in ("a", "b", "c")}
    first = client.post("/api/runs", json={"portfolio_id": pids["a"]})
    assert first.status_code == 202
    same_owner = client.post("/analyze/a")
    assert same_owner.status_code == 429 and same_owner.json()["scope"] == "owner" and same_owner.headers["retry-after"]
    assert client.post("/api/runs", json={"portfolio_id": pids["b"]}).status_code == 202
    third = client.post("/api/runs", json={"portfolio_id": pids["c"]})
    assert third.status_code == 429 and third.json()["scope"] == "global"
    assert started.acquire(timeout=5) and started.acquire(timeout=5)
    gate.set()
    wait_done(client, first.json()["run_id"])
    for _ in range(100):                                                      # the slot is freed right after the run is stored
        if not svc._SERVICES.manager.active():
            break
        time.sleep(0.02)
    assert client.post("/api/runs", json={"portfolio_id": pids["c"]}).status_code == 202


def test_a_failing_run_is_reported_and_frees_its_slot(client, tmp_path, monkeypatch):
    def run_fn(portfolio, progress):
        raise RuntimeError("news database down")
    services_with(run_fn, tmp_path, monkeypatch)
    pid = create(client).json()["portfolio_id"]
    rid = client.post("/api/runs", json={"portfolio_id": pid}).json()["run_id"]
    failed = wait_done(client, rid)
    assert failed["status"] == "failed" and "RuntimeError: news database down" in failed["error"] and "result" not in failed
    for _ in range(100):
        if not svc._SERVICES.manager.active():
            break
        time.sleep(0.02)
    assert client.post("/api/runs", json={"portfolio_id": pid}).status_code == 202


def test_analyze_owner_uses_the_default_portfolio_and_sync_returns_the_result(client, tmp_path, monkeypatch):
    seen = []

    def run_fn(portfolio, progress):
        seen.append(portfolio)
        return real_run_fn(returns={"NSE:AAA": 0.1})(portfolio, progress)
    services_with(run_fn, tmp_path, monkeypatch)
    assert client.post("/analyze/demo").status_code == 404                                              # no portfolio yet
    empty = create(client, "Empty", rows=[]).json()
    assert client.post("/analyze/demo").status_code == 422 and "no holdings" in client.post("/analyze/demo").json()["detail"]
    client.put(f"/api/portfolios/{empty['portfolio_id']}", json={"holdings": GOOD_ROWS})
    r = client.post("/analyze/demo")
    assert r.status_code == 202
    wait_done(client, r.json()["run_id"])
    assert seen[0] == {"user_id": "demo", "holdings": [{"ticker": "NSE:AAA", "quantity": 10.0, "average_cost": 90.0}, {"ticker": "NASDAQ:USX", "quantity": 4.0, "average_cost": 8.0}]}
    sync = client.post("/analyze/demo?sync=true")
    assert sync.status_code == 200 and sync.json()["disclaimer"] and sync.json()["run_id"]
    assert client.post("/analyze/bad owner").status_code in (404, 422)
    assert client.post("/api/runs", json={"portfolio_id": "11111111-1111-1111-1111-111111111111"}).status_code == 404
    assert client.get("/api/runs/unknown").status_code == 404 and client.get("/api/runs/!!").status_code == 404


def test_the_old_synchronous_analyze_endpoint_is_unchanged(client, monkeypatch):
    state = real_run_fn(returns={"NSE:AAA": 0.1})(PORT, lambda ev: None)
    monkeypatch.setattr(api, "run_analysis", lambda portfolio, deps=None, target="main", progress=None: state)
    r = client.post("/analyze", json={"sample": "concentrated_it"})
    assert r.status_code == 200 and r.json()["disclaimer"]


# ── progress hooks only observe ──────────────────────────────────────────────────────────────────────────────────
def strip(state: AnalysisState) -> dict:
    d = state.model_dump(mode="json")
    for k in ("run_seconds", "run_accounting"):
        d.pop(k)
    return d


def test_progress_hooks_do_not_change_the_result():
    kw = dict(returns={"NSE:AAA": -0.4}, bench_return=0.1)
    events = []
    with_hook = run_analysis(PORT, deps=make_deps(**kw), progress=events.append)
    without = run_analysis(PORT, deps=make_deps(**kw))
    assert strip(with_hook) == strip(without)
    nodes = [e["node"] for e in events if e["phase"] == "start"]
    assert set(nodes) == set(STAGES) - {"conflict_resolver"} and len(nodes) == len(set(nodes))
    ends = {e["node"]: e for e in events if e["phase"] == "end"}
    assert set(ends) == set(nodes) and all(e["status"] == "ok" and e["seconds"] >= 0 and e["detail"] for e in ends.values())
    for n in nodes:                                                                    # every node starts before it ends
        assert next(i for i, e in enumerate(events) if e["node"] == n and e["phase"] == "start") < next(i for i, e in enumerate(events) if e["node"] == n and e["phase"] == "end")
    assert ends["load_holdings"]["detail"] == "3 of 3 holdings resolved, 0 excluded" and ends["portfolio_scan"]["detail"].startswith("3 holdings")
    assert ends["fusion"]["detail"].startswith(f"{len(with_hook.shortlist)} flagged") and ends["stage2"]["detail"].startswith(f"{len(with_hook.stage2_verdicts)} stock(s) deep-dived")
    assert ends["synthesis"]["llm_calls"] == 1


def test_a_broken_observer_never_breaks_a_run():
    def boom(ev):
        raise RuntimeError("observer bug")
    a = run_analysis(PORT, deps=make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1), progress=boom)
    b = run_analysis(PORT, deps=make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1))
    assert strip(a) == strip(b)


def test_a_failed_node_is_reported_by_the_hook(monkeypatch):
    from finsight import graph
    monkeypatch.setitem(graph.NODES, "stage1_sentiment", lambda s, d: (_ for _ in ()).throw(RuntimeError("down")))
    events = []
    run_analysis(PORT, deps=make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1), progress=events.append)
    end = next(e for e in events if e["node"] == "stage1_sentiment" and e["phase"] == "end")
    assert end["status"] == "error" and "down" in end["detail"]


# ── accounting ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_run_records_llm_calls_by_node_tokens_cache_hits_and_duration():
    deps = make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1)
    state = run_analysis(PORT, deps=deps)
    a = state.run_accounting
    by = a["llm_calls_by_node"]
    assert set(by) == {"stage2", "synthesis"} and by["synthesis"]["calls"] == 1 and by["stage2"]["calls"] == len(state.stage2_verdicts)
    assert a["llm_calls"] == sum(n["calls"] for n in by.values()) == state.llm_calls_used == deps.llm.calls_made
    assert a["tokens"] == {"input": 100 * a["llm_calls"], "output": 50 * a["llm_calls"]}                   # the fake backend reports 100 / 50 per call
    assert a["max_calls"] == 8 and a["duration_s"] == state.run_seconds and set(a["node_seconds"]) == set(STAGES) - {"conflict_resolver"}
    assert a["cache"] == {"sector_narratives": {"hits": 0, "misses": 0}, "fundamentals": {"hits": 0, "misses": 0}}


def test_cache_hits_are_counted_for_sector_narratives_and_fundamentals():
    from tests.test_m1 import CANDS, good_narrative, tkg_sig
    from tests.test_m2 import tcs_bundle
    from finsight.data.common import Unavailable

    class Provider:
        source = "tkg"

        def sector_signals(self, ids, window_days=None):
            return {sid: (tkg_sig(-0.5) if sid == "information_technology" else Unavailable("insufficient_news", "x")) for sid in ids}

    def handler(model, system, user):
        if "temporal knowledge graph" in system:
            return good_narrative()
        if "financial health" in system:
            return json.dumps({"security_id": json.loads(user.split("\n", 1)[1])["security_id"], "stance": "neutral", "confidence": 0.5, "metrics_cited": ["roe_pct"], "rationale": "Return on equity is 43.4."})
        return good_handler(model, system, user)
    first = make_deps(llm=llm_for(handler, AGENTS_LLM_MAX_CALLS_PER_RUN=60)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1)
    first.sector_provider, first.sector_candidates = Provider(), lambda s: CANDS
    first.fundamentals = lambda sid: {**tcs_bundle(), "cache": "miss"}
    r1 = run_analysis(PORT, deps=first).run_accounting
    assert r1["cache"]["sector_narratives"] == {"hits": 0, "misses": 1} and r1["cache"]["fundamentals"]["misses"] >= 1 and "stage1_sector_agent" in r1["llm_calls_by_node"]
    second = make_deps(llm=llm_for(handler, AGENTS_LLM_MAX_CALLS_PER_RUN=60)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1)
    second.sector_provider, second.sector_candidates, second.app_store = Provider(), (lambda s: CANDS), first.app_store           # the shared cache
    second.fundamentals = lambda sid: {**tcs_bundle(), "cache": "hit"}
    r2 = run_analysis(PORT, deps=second).run_accounting
    assert r2["cache"]["sector_narratives"] == {"hits": 1, "misses": 0} and r2["cache"]["fundamentals"]["hits"] >= 1 and "stage1_sector_agent" not in r2["llm_calls_by_node"]


def test_the_default_call_budget_covers_a_busy_run():
    from finsight.settings import Settings
    s = Settings(_env_file=None)
    worst_realistic = 8 * 2 + 8 * (2 + 2) + 3 * 2 + 3            # sectors, stocks (fundamental + recheck, each with a retry), resolutions, synthesis + regeneration
    assert s.AGENTS_LLM_MAX_CALLS_PER_RUN == 60 and worst_realistic <= s.AGENTS_LLM_MAX_CALLS_PER_RUN
    assert (s.RUNS_MAX_PER_OWNER, s.RUNS_MAX_GLOBAL) == (1, 2)


# ── LangSmith tracing and redaction ──────────────────────────────────────────────────────────────────────────────
def test_redaction_removes_quantities_costs_values_and_owner_ids_everywhere():
    state = AnalysisState(user_id="jane.doe@example.com", holdings=[Holding(ticker="AAA", quantity=12345, average_cost=91.25, current_price=100.0)])
    out = tracing.redact({"inputs": state, "args": [{"owner_id": "demo", "note": "mail jane@example.com now"}], "keep": {"weight_pct": 33.3, "signal": -0.4, "value": 0.5}})
    text = json.dumps(out)
    for leaked in ("12345", "91.25", "100.0", "jane.doe", "example.com", '"demo"'):
        assert leaked not in text
    assert out["inputs"]["user_id"] == out["inputs"]["holdings"][0]["quantity"] == out["inputs"]["holdings"][0]["average_cost"] == tracing.REDACTED
    assert out["inputs"]["holdings"][0]["ticker"] == "AAA" and out["keep"] == {"weight_pct": 33.3, "signal": -0.4, "value": 0.5}
    assert out["args"][0]["note"] == "mail [redacted-email] now"


def test_redaction_covers_derived_cost_fields_and_a_whole_state_dump():
    deps = make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1)
    state = run_analysis({"user_id": "owner-secret-77", "holdings": [{"ticker": "AAA", "quantity": 7777, "average_cost": 91.5}, {"ticker": "BBB", "quantity": 5, "average_cost": 180.0}]}, deps=deps)
    text = json.dumps(tracing.redact(state))
    assert "owner-secret-77" not in text and "7777" not in text and "91.5" not in text and "unrealized_return_pct\": -" not in text
    assert "unrealized_return_pct\": \"[redacted]\"" in text and "weight\"" in text                       # the share of the portfolio is not a cost; the return is


def test_tracing_is_off_by_default_even_if_the_environment_asks(monkeypatch):
    import langsmith as ls
    from finsight.settings import Settings
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    off = Settings(_env_file=None)
    assert tracing.enabled(off) is False                                         # the flag alone (here from the environment) is not enough: a key is needed too
    assert Settings(_env_file=None, LANGSMITH_TRACING=False).LANGSMITH_TRACING is False
    ctx, config = tracing.run_context(off)
    with ctx:
        assert ls.utils.tracing_is_enabled() is False                           # a stray shell variable cannot send an unredacted trace
    assert config == {}
    monkeypatch.delenv("LANGSMITH_TRACING")
    assert tracing.enabled(Settings(_env_file=None, LANGSMITH_TRACING=True)) is False                           # on only with a key too
    assert tracing.enabled(Settings(_env_file=None, LANGSMITH_API_KEY="k")) is False


def test_tracing_defaults_to_off(monkeypatch):
    from finsight.settings import Settings
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert Settings(_env_file=None).LANGSMITH_TRACING is False and tracing.enabled(Settings(_env_file=None)) is False


def test_enabled_tracing_builds_the_client_with_the_redaction_hooks(monkeypatch):
    import langsmith as ls
    from finsight.settings import Settings
    captured = {}

    class StubClient:
        def __init__(self, **kw):
            captured.update(kw)
    monkeypatch.setattr(ls, "Client", StubClient)
    on = Settings(_env_file=None, LANGSMITH_TRACING=True, LANGSMITH_API_KEY="lsv2_fake", LANGSMITH_PROJECT="proj")
    assert tracing.enabled(on)
    tracing.make_client(on)
    assert captured["hide_inputs"] is tracing.redact and captured["hide_outputs"] is tracing.redact and captured["hide_metadata"] is tracing.redact
    assert captured["api_key"] == "lsv2_fake"
    ctx, config = tracing.run_context(on)
    assert len(config["callbacks"]) == 1 and type(config["callbacks"][0]).__name__ == "LangChainTracer"
    hide = captured["hide_inputs"]({"holdings": [{"quantity": 5, "average_cost": 9.0}], "user_id": "u-1"})
    assert hide == {"holdings": [{"quantity": "[redacted]", "average_cost": "[redacted]"}], "user_id": "[redacted]"}


# ── the durable run store never slows a run ──────────────────────────────────────────────────────────────────────
def test_durable_run_writes_are_asynchronous_coalesced_and_failure_tolerant():
    from finsight.data.app_repo import MemoryRunStore
    from finsight.runs import CompositeRunStore

    class SlowDurable:
        def __init__(self):
            self.creates, self.updates, self.fail = [], [], False

        def create(self, run):
            time.sleep(0.2)
            if self.fail:
                raise RuntimeError("db down")
            self.creates.append(dict(run))

        def update(self, run_id, **fields):
            time.sleep(0.2)
            if self.fail:
                raise RuntimeError("db down")
            self.updates.append((run_id, fields))

        def get(self, run_id):
            return None

        def list(self, owner_id=None, limit=50):
            return []
    durable = SlowDurable()
    store = CompositeRunStore(MemoryRunStore(), durable)
    started = time.time()
    store.create({"run_id": "r1-abcdefgh", "owner_id": "o", "status": "queued", "created_at": "2026-01-01"})
    for i in range(10):
        store.update("r1-abcdefgh", stage_index=i)
    store.update("r1-abcdefgh", _durable=False, stage="memory-only")
    store.update("r1-abcdefgh", status="done")
    assert time.time() - started < 0.15                                                         # nothing waited for the database
    assert store.get("r1-abcdefgh")["status"] == "done" and store.get("r1-abcdefgh")["stage"] == "memory-only"          # the registry is always current
    assert store.flush(10)
    assert len(durable.creates) == 1 and len(durable.updates) <= 1                                       # eleven writes became the create plus at most one update
    last = {**durable.creates[0], **{k: v for _, f in durable.updates for k, v in f.items()}}
    assert last["status"] == "done" and last["stage_index"] == 9 and "stage" not in last
    durable.fail = True
    store.update("r1-abcdefgh", status="failed")
    assert store.flush(10) and store.durable_errors >= 1 and store.get("r1-abcdefgh")["status"] == "failed"     # a database failure never fails a run
