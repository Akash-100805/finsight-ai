"""securities-refresh: download (or reuse cache), build, upsert securities per source, regenerate aliases."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.news.db.engine import get_engine
from src.news.security_master import bse_industry as bse_ind
from src.news.security_master import sources
from src.news.security_master.aliases import AliasResult, generate_aliases
from src.news.security_master.build import SRC_BSE, SRC_NSE, SRC_US, BuildResult, build_securities
from src.news.security_master.datafiles import (
    load_ambiguous_terms, load_bse_industry_map, load_curated, load_sic_ranges, load_symbol_stoplist,
)
from src.news.security_master.load import LoadStats, SourceStats, sync_aliases, upsert_source
from src.news.security_master.parse import parse_bse, parse_nifty, parse_nse, parse_sec

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "security_master"


@dataclass
class RefreshResult:
    build: BuildResult
    aliases: AliasResult
    stats: LoadStats = field(default_factory=LoadStats)


def _input_paths(offline: bool, fixtures: bool) -> dict[str, Path]:
    if fixtures:
        return {"nse": FIXTURE_DIR / "nse.csv", "bse": next(FIXTURE_DIR.glob("bse.*")), "nifty": FIXTURE_DIR / "nifty_total_market.csv",
                "sec": FIXTURE_DIR / "sec_tickers.json"}
    return {"nse": sources.fetch_nse(offline), "bse": sources.fetch_bse(offline),
            "nifty": sources.fetch_nifty_total_market(offline), "sec": sources.fetch_sec_tickers(offline)}


def run_refresh(target: str = "main", offline: bool = False, fixtures: bool = False, refresh_bse_industry: bool = False) -> RefreshResult:
    paths = _input_paths(offline, fixtures)
    nse, bse, nifty, sec = parse_nse(paths["nse"]), parse_bse(paths["bse"]), parse_nifty(paths["nifty"]), parse_sec(paths["sec"])
    if fixtures:
        sic_cache = json.loads((FIXTURE_DIR / "sec_sic.json").read_text(encoding="utf-8"))
    else:
        us_ciks = sorted({s.cik for s in sec if s.exchange in ("Nasdaq", "NYSE", "CBOE")})
        sic_cache = sources.fetch_sic_codes(us_ciks, offline)

    if fixtures:
        industry_cache = json.loads((FIXTURE_DIR / "bse_industry.json").read_text(encoding="utf-8"))
        needed = bse_ind.needed_scrips(nse, bse, nifty)
        fetch_note = None
    else:
        needed = bse_ind.needed_scrips(nse, bse, nifty)
        fetch_note = None
        todo = needed if refresh_bse_industry else [c for c in needed if not bse_ind.cache_path(c).exists()]
        if todo and not offline:
            outcome = bse_ind.fetch_missing(needed, refresh=refresh_bse_industry)
            fetch_note = (f"BSE industry: {outcome.fetched}/{outcome.attempted} fetched directly"
                          + ("; STOPPED after 10 consecutive blocks (BSE refuses scripts - use tools/bse_industry_browser.md)" if outcome.stopped_blocked else ""))
        industry_cache = bse_ind.load_cache()
    built = build_securities(nse, bse, nifty, sec, sic_cache, load_bse_industry_map(), load_sic_ranges(), industry_cache, needed)
    built.report.fetch_note = fetch_note
    all_rows = built.nse + built.bse + built.us
    aliases = generate_aliases(all_rows, load_symbol_stoplist(), load_ambiguous_terms(), load_curated())

    engine = get_engine(target)
    result = RefreshResult(built, aliases)
    for source, rows in ((SRC_NSE, built.nse), (SRC_BSE, built.bse), (SRC_US, built.us)):  # NSE first: BSE rows point at it
        result.stats.sources[source] = upsert_source(engine, source, rows)
    result.stats.aliases = sync_aliases(engine, aliases.aliases)
    return result


def print_summary(result: RefreshResult) -> None:
    b = result.build
    print(f"Built: NSE {len(b.nse)}, BSE {len(b.bse)}, US {len(b.us)}; aliases {len(result.aliases.aliases)}")
    for source, s in result.stats.sources.items():
        print(f"  {source}: inserted {s.inserted}, updated {s.updated}, deactivated {s.deactivated}")
    a = result.stats.aliases
    print(f"  aliases: inserted {a.inserted}, updated {a.updated}, deleted {a.deleted}")
    print("Total changes:", result.stats.changed, "(0 means the master was already up to date)")
    r = b.report
    if r.unknown_bse_industries:
        print("REPORT: BSE industries missing from bse_industry_to_sector.csv (sector left NULL):")
        for name, n in r.unknown_bse_industries.most_common():
            print(f"    {name!r}: {n} securities")
    if r.blank_bse_industry:
        print(f"REPORT: {r.blank_bse_industry} fetched BSE scrips have an empty IndustryNew (sector left NULL)")
    if getattr(r, "fetch_note", None):
        print("REPORT:", r.fetch_note)
    if r.industry_unfetched:
        print(f"REPORT: {len(r.industry_unfetched)} scrips still have no BSE industry in the cache (sector left NULL)")
    if r.unknown_nifty_industries:
        print("REPORT: Nifty industries that are not frozen sectors:", dict(r.unknown_nifty_industries))
    if r.us_unmapped_sic:
        print(f"REPORT: {sum(r.us_unmapped_sic.values())} US securities have a SIC code with no sic_to_sector.csv range:",
              dict(r.us_unmapped_sic.most_common(15)))
    print(f"US: {r.us_missing_sic} securities without SIC; excluded by exchange: {dict(r.us_excluded_exchange)}")
    al = result.aliases
    if al.curated_missing:
        print(f"REPORT: {len(al.curated_missing)} curated rows reference a security_id that does not exist:")
        for sid, alias in al.curated_missing:
            print(f"    {sid}  ({alias})")
    if al.curated_remapped:
        print(f"REPORT: {len(al.curated_remapped)} curated rows pointed at a secondary listing and were moved to its primary")
    if al.curated_invalid:
        print(f"REPORT: {len(al.curated_invalid)} invalid curated rows ignored:", al.curated_invalid[:10])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="securities-refresh")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    parser.add_argument("--offline", action="store_true", help="use only cached files")
    parser.add_argument("--refresh-bse-industry", action="store_true", help="re-pull BSE industry for every needed scrip, ignoring the cache")
    parser.add_argument("--fixtures", action="store_true", help="use the saved test fixtures instead of downloads (test target only)")
    args = parser.parse_args(argv)
    if args.fixtures and args.target != "test":
        print("--fixtures may only be used with --target test")
        return 2
    try:
        result = run_refresh(args.target, args.offline, args.fixtures, args.refresh_bse_industry)
    except (sources.DownloadError, RuntimeError) as exc:
        print(f"securities-refresh failed: {exc}")
        return 1
    print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())