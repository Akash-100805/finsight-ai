"""SECTOR_PROVIDER=tkg: Indian holdings only, the contract (tkg.drivers, tkg.v_events.title), company evidence, no TKG imports."""
from __future__ import annotations

import pathlib
import re
from datetime import datetime, timezone

import pytest

from finsight.data.common import Unavailable
from finsight.data.sector_signal import (FallbackSectorProvider, SectorProviderError, TkgProvider, is_indian_security,
                                         relation_arrow)
from flow_helpers import make_deps
from test_data_adapters import make_settings
from test_flow import US_PORT, PORT, state_after_scan
from finsight.flow import stage1
from finsight.flow import scoring as sc

NOW = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)
EVENT = "11111111-1111-1111-1111-111111111111"
ARTICLE = "22222222-2222-2222-2222-222222222222"
PATH = {"type": "driver", "driver_id": "drv:crude_oil_price", "relation": "MOVES_UP", "magnitude": "high", "contrib": -0.4,
        "event_id": EVENT, "article_id": ARTICLE, "summary": "Crude jumps", "reviewed": True}
COMPANY_PATH = {"type": "driver_override", "driver_id": "drv:coal_price", "relation": "MOVES_DOWN", "magnitude": "medium",
                "sensitivity": 0.6, "contrib": -0.2, "event_id": EVENT, "article_id": ARTICLE, "summary": "Coal falls", "reviewed": True}


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return list(self.rows)


class ContractEngine:
    """Answers the contract queries by table name and records every statement."""

    def __init__(self, tables):
        self.tables, self.sql = tables, []

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt, params=None):
        q = str(stmt)
        self.sql.append(q)
        for key, rows in self.tables.items():
            if key in q:
                if isinstance(rows, Exception):
                    raise rows
                return Result(rows)
        raise AssertionError(f"unexpected query: {q}")


def contract_tables(**over):
    tables = {
        "tkg.sector_impacts": [{"sector_id": "information_technology", "as_of": NOW, "score": -0.4, "confidence": 0.7, "status": "signal",
                                "n_events": 2, "top_paths": [PATH], "uses_unreviewed_prior": False}],
        "tkg.drivers": [{"driver_id": "drv:crude_oil_price", "label": "Crude Oil Price"}, {"driver_id": "drv:coal_price", "label": "Coal Price"}],
        "tkg.v_events": [{"event_id": EVENT, "title": "Brent jumps after OPEC+ cut", "summary": "Crude jumps"}],
        "tkg.v_security_impacts_latest": [{"security_id": "NSE:AAA", "as_of": NOW, "via_sector_score": -0.1, "direct_score": -0.2,
                                           "direct_confidence": 0.5, "n_direct_events": 1, "top_paths": [COMPANY_PATH]},
                                          {"security_id": "NSE:BBB", "as_of": NOW, "via_sector_score": 0.0, "direct_score": 0.0,
                                           "direct_confidence": 0.0, "n_direct_events": 0, "top_paths": []}],
    }
    tables.update(over)
    return tables


def provider(engine):
    return TkgProvider(engine=engine, settings=make_settings(SECTOR_PROVIDER="tkg"), now=lambda: NOW)


# ------------------------------------------------------------------ the contract, no workarounds

def test_driver_labels_and_headlines_come_from_the_contract():
    engine = ContractEngine(contract_tables())
    out = provider(engine).sector_signals(["information_technology"])
    text = out["information_technology"]["explanations"][0]
    assert text == "Brent jumps after OPEC+ cut -> Crude Oil Price ↑ (high) -> -0.40"
    joined = " ".join(engine.sql)
    assert "tkg.drivers" in joined and "tkg.v_events" in joined
    assert "news.v_articles" not in joined and "news." not in joined          # no reaching into the news schema
    assert out["information_technology"]["evidence_article_ids"] == [ARTICLE]


def test_the_event_summary_is_used_only_when_the_title_is_null():
    engine = ContractEngine(contract_tables(**{"tkg.v_events": [{"event_id": EVENT, "title": None, "summary": "Crude jumps"}]}))
    text = provider(engine).sector_signals(["information_technology"])["information_technology"]["explanations"][0]
    assert text.startswith("Crude jumps -> Crude Oil Price")


def test_unreadable_drivers_is_an_error_not_a_title_cased_guess():
    engine = ContractEngine(contract_tables(**{"tkg.drivers": RuntimeError("permission denied for table drivers")}))
    with pytest.raises(SectorProviderError, match=r"tkg\.drivers is not readable"):
        provider(engine).sector_signals(["information_technology"])
    engine = ContractEngine(contract_tables(**{"tkg.drivers": []}))
    with pytest.raises(SectorProviderError, match="no label"):
        provider(engine).sector_signals(["information_technology"])


def test_relation_names_come_from_the_shared_vocabulary():
    assert (relation_arrow("MOVES_UP"), relation_arrow("MOVES_DOWN"), relation_arrow("MIXED"), relation_arrow(None)) == ("↑", "↓", "", "")
    import finsight.data.sector_signal as module
    assert "finsight_shared.tkg_vocab" in pathlib.Path(module.__file__).read_text(encoding="utf-8")


def test_the_agents_import_no_tkg_package_code():
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    offenders = [str(p) for p in src.rglob("*.py")
                 if re.search(r"^\s*(from|import)\s+tkg(\.|\s|$)", p.read_text(encoding="utf-8"), re.M)]
    assert offenders == []


# ------------------------------------------------------------------ company-level evidence (evidence only)

def test_company_impacts_are_read_from_the_contract_view():
    engine = ContractEngine(contract_tables())
    out = provider(engine).company_impacts(["NSE:AAA", "NSE:BBB"], 30)
    assert set(out) == {"NSE:AAA"}                                      # BBB has no direct events: omitted
    ev = out["NSE:AAA"]
    assert (ev["direct_score"], ev["direct_confidence"], ev["n_direct_events"], ev["via_sector_score"]) == (-0.2, 0.5, 1, -0.1)
    assert ev["paths"] == ["Brent jumps after OPEC+ cut -> Coal Price ↓ (medium) -> company sensitivity +0.60 = -0.20"]
    assert any("tkg.v_security_impacts_latest" in q for q in engine.sql)


# ------------------------------------------------------------------ Indian holdings only, per-holding provider

class StubTkg:
    source = "tkg"

    def __init__(self, fail=False):
        self.calls, self.company_calls, self.fail = [], [], fail

    def sector_signals(self, sector_ids, window_days=None):
        self.calls.append(list(sector_ids))
        if self.fail:
            raise SectorProviderError("tkg.sector_impacts returned no rows")
        return {s: {"score": -0.5, "confidence": 0.8, "n": 3, "source": "tkg", "evidence_article_ids": ["a1"],
                    "explanations": ["Brent jumps -> Crude Oil Price ↑ (high) -> -0.40"], "as_of": NOW.isoformat()} for s in sector_ids}

    def company_impacts(self, security_ids, window_days=None):
        self.company_calls.append(list(security_ids))
        return {"NSE:AAA": {"direct_score": -0.2, "direct_confidence": 0.5, "via_sector_score": -0.1, "n_direct_events": 1,
                            "paths": ["Coal falls -> Coal Price ↓"], "evidence_article_ids": ["a1"], "as_of": NOW.isoformat()}}


class StubLite:
    source = "tkg_lite"

    def __init__(self):
        self.calls = []

    def sector_signals(self, sector_ids, window_days=None):
        self.calls.append(list(sector_ids))
        return {s: {"score": 0.5, "confidence": 1.0, "n": 30, "source": "tkg_lite", "evidence_article_ids": ["x"]} for s in sector_ids}


def scan(port, primary, lite):
    deps = make_deps()
    deps.sector_provider = FallbackSectorProvider(primary, lite)
    s, deps = state_after_scan(deps, port)
    return s, deps, stage1.stage1_sector(s, deps)


def test_us_holdings_use_tkg_lite_and_indian_holdings_use_the_tkg():
    primary, lite = StubTkg(), StubLite()
    s, _, out = scan(US_PORT, primary, lite)
    assert is_indian_security("NSE:AAA") and not is_indian_security("NASDAQ:USX")
    assert primary.calls == [["information_technology"]] and lite.calls == [["information_technology"]]
    assert out["sector_signal_sources"] == {"AAA": "tkg", "NASDAQ:USX": "tkg_lite"}
    assert out["sector_signal_source"] == "tkg+tkg_lite"                                  # the chip: "TKG + TKG-lite"
    assert out["stage1_sector"]["AAA"]["evidence"]["source"] == "tkg"
    assert out["stage1_sector"]["NASDAQ:USX"]["evidence"]["source"] == "tkg_lite"
    assert out["stage1_sector"]["AAA"]["signal"] < 0 < out["stage1_sector"]["NASDAQ:USX"]["signal"]
    assert out["sector_fallback_reason"] is None


def test_all_indian_run_is_tkg_and_all_us_run_never_calls_the_tkg():
    primary, lite = StubTkg(), StubLite()
    _, _, out = scan(PORT, primary, lite)
    assert out["sector_signal_source"] == "tkg" and lite.calls == []
    primary, lite = StubTkg(), StubLite()
    us_only = {"user_id": "us", "holdings": [{"ticker": "NASDAQ:USX", "quantity": 4, "average_cost": 8.0}]}
    _, _, out = scan(us_only, primary, lite)
    assert out["sector_signal_source"] == "tkg_lite" and primary.calls == [] and out["sector_signal_sources"] == {"NASDAQ:USX": "tkg_lite"}


def test_a_tkg_failure_falls_back_to_lite_for_everything_and_says_why():
    primary, lite = StubTkg(fail=True), StubLite()
    _, _, out = scan(US_PORT, primary, lite)
    assert out["sector_signal_source"] == "tkg_lite" and set(out["sector_signal_sources"].values()) == {"tkg_lite"}
    assert "SectorProviderError" in out["sector_fallback_reason"]
    assert out["tkg_company_evidence"] == {} and primary.company_calls == []


def test_company_evidence_is_attached_for_indian_holdings_only_and_never_enters_fusion():
    primary, lite = StubTkg(), StubLite()
    s, deps, out = scan(US_PORT, primary, lite)
    assert primary.company_calls == [["NSE:AAA"]]                                         # the US security is never sent to the TKG
    assert set(out["tkg_company_evidence"]) == {"AAA"}
    assert out["tkg_company_evidence"]["AAA"]["direct_score"] == -0.2

    with_evidence = {**s.model_dump(), **out}
    without = {**with_evidence, "tkg_company_evidence": {}}
    from finsight.schemas.state import AnalysisState
    a, b = AnalysisState(**with_evidence), AnalysisState(**without)
    assert stage1.fusion(a, deps)["fused_values"] == stage1.fusion(b, deps)["fused_values"]


def test_the_stage1_sector_node_writes_only_its_own_fields():
    s, deps = state_after_scan()
    assert set(stage1.stage1_sector(s, deps)) == {"stage1_sector", "sector_signal_source", "sector_signal_sources",
                                                   "sector_fallback_reason", "tkg_company_evidence"}
    assert sc.sector_confidence(0.9, "tkg") == 0.9
