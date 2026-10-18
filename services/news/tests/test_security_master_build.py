"""Build logic against small REAL fixtures (tests/fixtures/security_master/)."""
import json
from pathlib import Path

import pytest

from src.news.security_master import bse_industry as bi
from src.news.security_master.build import build_securities
from src.news.security_master.datafiles import load_bse_industry_map, load_sic_ranges
from src.news.security_master.parse import ShapeError, parse_bse, parse_nifty, parse_nse, parse_sec

FIX = Path(__file__).parent / "fixtures" / "security_master"


@pytest.fixture(scope="module")
def inputs():
    nse, bse = parse_nse(FIX / "nse.csv"), parse_bse(FIX / "bse.csv")
    nifty, sec = parse_nifty(FIX / "nifty_total_market.csv"), parse_sec(FIX / "sec_tickers.json")
    return dict(nse=nse, bse=bse, nifty=nifty, sec=sec,
                sic=json.loads((FIX / "sec_sic.json").read_text()), industry=json.loads((FIX / "bse_industry.json").read_text()))


def build(inputs, industry=None):
    needed = bi.needed_scrips(inputs["nse"], inputs["bse"], inputs["nifty"])
    return build_securities(inputs["nse"], inputs["bse"], inputs["nifty"], inputs["sec"], inputs["sic"],
                            load_bse_industry_map(), load_sic_ranges(),
                            inputs["industry"] if industry is None else industry, needed), needed


def by_id(rows):
    return {r["security_id"]: r for r in rows}


# ── parsing ──────────────────────────────────────────────────────────────────
def test_parse_bse_real_csv_shape(inputs):
    assert inputs["bse"] and all(b.instrument == "Equity" and b.status == "Active" and b.isin for b in inputs["bse"])
    assert all(b.industry == "" for b in inputs["bse"])  # the manual download carries no industry


def test_parse_bse_filters_non_equity_and_inactive(tmp_path):
    f = tmp_path / "bse.csv"
    f.write_text("Security Code,Issuer Name,Security Id,Security Name,Status,Group,Face Value,ISIN No,Instrument\n"
                 "1,A,A,A Ltd,Active,A ,1,INE000000001,Equity,,\n2,B,B,B Pref,Active,A ,1,INE000000002,PreferenceShares,,\n"
                 "3,C,C,C Ltd,Active,A ,1,INE000000003,-,,\n4,D,D,D Ltd,Suspended,A ,1,INE000000004,Equity,,\n", encoding="utf-8")
    assert [b.scrip_cd for b in parse_bse(f)] == ["1"]


def test_parse_bse_wrong_shape_stops(tmp_path):
    f = tmp_path / "bse.csv"
    f.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ShapeError):
        parse_bse(f)


def test_parse_bse_api_json_shape(tmp_path):
    f = tmp_path / "bse.json"
    f.write_text(json.dumps([{"SCRIP_CD": "500325", "Scrip_Name": "Reliance Industries Ltd", "Status": "Active", "GROUP": "A",
                              "ISIN_NUMBER": "INE002A01018", "INDUSTRY": None, "scrip_id": "RELIANCE", "Segment": "Equity"}]))
    rows = parse_bse(f)
    assert rows[0].scrip_cd == "500325" and rows[0].scrip_id == "RELIANCE" and rows[0].industry == ""


# ── NSE / BSE ────────────────────────────────────────────────────────────────
def test_dual_listing_primary_and_sector_copy(inputs):
    built, _ = build(inputs)
    nse, bse = by_id(built.nse), by_id(built.bse)
    rel = bse["BSE:500325"]
    assert rel["primary_listing_id"] == "NSE:RELIANCE" and rel["alt_symbol"] == "RELIANCE"
    assert rel["sector"] == nse["NSE:RELIANCE"]["sector"] == "oil_gas_and_consumable_fuels"
    assert rel["sector_method"] == "nifty_index"
    assert nse["NSE:RELIANCE"]["primary_listing_id"] is None


def test_nifty_wins_over_bse_industry(inputs):
    industry = dict(inputs["industry"])
    industry["500325"] = {"Industry": "x", "Sector": "y", "IndustryNew": "Textiles"}
    built, _ = build(inputs, industry)
    row = by_id(built.nse)["NSE:RELIANCE"]
    assert row["sector"] == "oil_gas_and_consumable_fuels" and row["sector_method"] == "nifty_index"
    assert row["industry_raw"] == "Oil Gas & Consumable Fuels"


def test_non_nifty_nse_stock_uses_bse_industry(inputs):
    built, _ = build(inputs)
    bse_by_isin = {b.isin: b for b in inputs["bse"]}
    checked = 0
    for n in inputs["nse"]:
        b = bse_by_isin.get(n.isin)
        row = by_id(built.nse)[f"NSE:{n.symbol}"]
        entry = inputs["industry"].get(b.scrip_cd) if b else None
        if row["sector_method"] == "bse_industry_map":
            checked += 1
            assert row["industry_raw"] == f"{entry['Industry']} | {entry['Sector']} | {entry['IndustryNew']}"
            assert row["sector"] is not None
    assert checked == 7  # 5 exact-label + 2 mapped-through-CSV fixtures


def test_exact_label_maps_directly_and_other_values_use_csv(inputs):
    built, _ = build(inputs)
    methods = {r["sector"] for r in built.nse if r["sector_method"] == "bse_industry_map"}
    assert methods  # mapped via exact label or csv
    industry = {"500012": {"Industry": "i", "Sector": "s", "IndustryNew": "Oil, Gas & Consumable Fuels"}}
    row = build_securities(inputs["nse"], inputs["bse"], [], [], {}, load_bse_industry_map(), [], industry, ["500012"])
    assert by_id(row.bse)["BSE:500012"]["sector"] == "oil_gas_and_consumable_fuels"
    industry = {"500012": {"Industry": "i", "Sector": "s", "IndustryNew": "Chemicals"}}
    row = build_securities(inputs["nse"], inputs["bse"], [], [], {}, load_bse_industry_map(), [], industry, ["500012"])
    assert by_id(row.bse)["BSE:500012"]["sector"] == "chemicals"


def test_nse_without_bse_listing_stays_null(inputs):
    built, _ = build(inputs)
    bse_isins = {b.isin for b in inputs["bse"]}
    only = [r for r in built.nse if r["isin"] not in bse_isins]
    assert len(only) == 3 and all(r["sector"] is None and r["sector_method"] is None for r in only)


def test_bse_only_gets_sector_from_industry_and_blank_is_reported(inputs):
    built, needed = build(inputs)
    nse_isins = {n.isin for n in inputs["nse"]}
    only = [r for r in built.bse if r["isin"] not in nse_isins]
    assert len(only) == 6 and all(r["primary_listing_id"] is None for r in only)
    with_sector = [r for r in only if r["sector"]]
    assert len(with_sector) == 5 and all(r["sector_method"] == "bse_industry_map" for r in with_sector)
    blank = [r for r in only if not r["sector"]]
    assert len(blank) == 1 and blank[0]["sector_method"] is None
    assert built.report.blank_bse_industry == 1


def test_unknown_industry_new_is_reported_not_guessed(inputs):
    code = next(r["symbol"] for r in build(inputs)[0].bse if r["sector_method"] == "bse_industry_map" and r["primary_listing_id"] is None)
    industry = dict(inputs["industry"])
    industry[code] = {"Industry": "Widgets", "Sector": "Gadgets", "IndustryNew": "Widget Making"}
    built, _ = build(inputs, industry)
    row = by_id(built.bse)[f"BSE:{code}"]
    assert row["sector"] is None and row["industry_raw"] == "Widgets | Gadgets | Widget Making"
    assert built.report.unknown_bse_industries["Widget Making"] == 1


def test_missing_cache_entry_is_reported(inputs):
    industry = dict(inputs["industry"])
    gone = next(iter(industry))
    del industry[gone]
    built, _ = build(inputs, industry)
    assert gone in built.report.industry_unfetched


def test_needed_scrips_rules(inputs):
    needed = set(bi.needed_scrips(inputs["nse"], inputs["bse"], inputs["nifty"]))
    nifty_symbols = {n.symbol for n in inputs["nifty"]}
    nse_isin = {n.isin: n for n in inputs["nse"]}
    for b in inputs["bse"]:
        nse = nse_isin.get(b.isin)
        if nse is not None and nse.symbol in nifty_symbols:
            assert b.scrip_cd not in needed  # never for Nifty Total Market stocks
        else:
            assert b.scrip_cd in needed


def test_nifty_isin_fallback_when_symbol_differs(inputs):
    nifty = [type(n)(n.company, n.industry, "RENAMED", n.isin) for n in inputs["nifty"]]
    built = build_securities(inputs["nse"], [], nifty, [], {}, {}, [])
    assert by_id(built.nse)["NSE:RELIANCE"]["sector_method"] == "nifty_index"


# ── US ───────────────────────────────────────────────────────────────────────
def test_us_primary_secondary_otc_and_sic(inputs):
    built, _ = build(inputs)
    us = by_id(built.us)
    assert us["NASDAQ:GOOGL"]["primary_listing_id"] is None and us["NASDAQ:GOOG"]["primary_listing_id"] == "NASDAQ:GOOGL"
    assert us["NASDAQ:GOOGL"]["cik"] == us["NASDAQ:GOOG"]["cik"]
    brk = [r for r in built.us if r["cik"] == us["NYSE:BRK-B"]["cik"]]
    assert sum(1 for r in brk if r["primary_listing_id"] is None) == 1
    order = [r["security_id"] for r in sorted(brk, key=lambda r: [s.ticker for s in inputs["sec"] if s.cik == int(r["cik"])].index(r["symbol"]))]
    assert next(r for r in brk if r["primary_listing_id"] is None)["security_id"] == order[0]
    assert all(r["exchange"] in ("NASDAQ", "NYSE", "CBOE") and r["country"] == "US" for r in built.us)
    assert built.report.us_excluded_exchange["OTC"] == 1 and built.report.us_excluded_exchange["(none)"] == 1
    aapl = us["NASDAQ:AAPL"]
    assert aapl["sector_method"] == "sic_map" and aapl["sic_code"] == "3571" and aapl["sector"] == "information_technology"


def test_us_zero_or_missing_sic_leaves_sector_null(inputs):
    sic = {k: ({"sic": "0", "sic_description": ""} if k == str(next(iter(inputs["sic"]))) else v) for k, v in inputs["sic"].items()}
    built = build_securities(inputs["nse"], inputs["bse"], inputs["nifty"], inputs["sec"], sic, {}, load_sic_ranges())
    zero_cik = str(next(iter(inputs["sic"])))
    assert all(r["sector"] is None and r["sic_code"] is None for r in built.us if r["cik"] == zero_cik)
    assert built.report.us_missing_sic >= 1