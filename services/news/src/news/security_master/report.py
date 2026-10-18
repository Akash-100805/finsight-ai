"""Writes docs/review/phase2_coverage.md from the current contents of news.securities / news.security_aliases."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.news.db.engine import get_engine
from src.news.security_master import sources
from src.news.security_master import bse_industry as bse_ind
from src.news.security_master.parse import parse_bse, parse_nifty

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUT = REPO_ROOT / "docs" / "review" / "phase2_coverage.md"


def _table(headers: list[str], rows: list[tuple]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join("" if v is None else str(v).replace("|", "\\|") for v in row) + " |" for row in rows]
    return "\n".join(lines)


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:.1f}% ({num}/{den})" if den else "n/a"


def build_report(engine: Engine, offline: bool = True) -> str:
    q = lambda sql, **p: conn.execute(text(sql), p).all()  # noqa: E731
    out = [f"# Phase 2 coverage report", "", f"Generated {date.today().isoformat()} from the `main` database. Targets are from guide section 6.1.", ""]
    with engine.connect() as conn:
        out += ["## Securities by exchange", "", _table(
            ["Exchange", "Active", "Inactive", "Primary (active)", "Secondary (active)"],
            [tuple(r) for r in q("""
                SELECT exchange, count(*) FILTER (WHERE is_active), count(*) FILTER (WHERE NOT is_active),
                       count(*) FILTER (WHERE is_active AND primary_listing_id IS NULL),
                       count(*) FILTER (WHERE is_active AND primary_listing_id IS NOT NULL)
                FROM news.securities GROUP BY exchange ORDER BY exchange""")]), ""]

        # sector coverage against the guide's targets
        nifty_symbols = {n.symbol for n in parse_nifty(sources.fetch_nifty_total_market(offline=offline))}
        nse = {r[0]: r[1] for r in q("SELECT symbol, sector FROM news.securities WHERE exchange='NSE' AND is_active")}
        tm_in_db = [s for s in nifty_symbols if s in nse]
        tm_with = sum(1 for s in tm_in_db if nse[s])
        nse_with = sum(1 for v in nse.values() if v)
        bse_only = q("SELECT count(*) FILTER (WHERE sector IS NOT NULL), count(*) FROM news.securities WHERE exchange='BSE' AND is_active AND primary_listing_id IS NULL")[0]
        us = q("SELECT count(*) FILTER (WHERE sector IS NOT NULL), count(*) FROM news.securities WHERE country='US' AND is_active")[0]
        out += ["## Sector coverage", "", _table(["Population", "With sector", "Guide target"], [
            ("Nifty Total Market stocks (symbols in the constituents file)", _pct(tm_with, len(nifty_symbols)), "100%"),
            ("Active NSE equities", _pct(nse_with, len(nse)), ">= 95%"),
            ("Active BSE-only equities", _pct(bse_only[0], bse_only[1]), ">= 90%"),
            ("Active US securities", _pct(us[0], us[1]), "no target in the guide"),
        ]), ""]
        out += ["Nifty Total Market symbols not found in the NSE master: "
                + (", ".join(sorted(nifty_symbols - set(nse))) or "none"), ""]
        out += ["### Sector method breakdown (active securities)", "", _table(["Exchange", "sector_method", "Securities"],
               [tuple(r) for r in q("""SELECT CASE WHEN country='US' THEN 'US' ELSE exchange END AS grp, coalesce(sector_method,'(no sector)'), count(*)
                                       FROM news.securities WHERE is_active GROUP BY 1,2 ORDER BY 1,2""")]), ""]

        # why is the sector NULL? (NSE and BSE-only securities)
        cache = bse_ind.load_cache()
        bse_rows = parse_bse(sources.fetch_bse(offline=offline))
        codes_by_isin: dict[str, list[str]] = {}
        for b in bse_rows:
            codes_by_isin.setdefault(b.isin, []).append(b.scrip_cd)
        reasons = {"NSE: no BSE listing, so no industry source": 0, "NSE: BSE industry blank (IndustryNew empty)": 0,
                   "NSE: BSE industry not fetched": 0, "NSE: IndustryNew has no mapping": 0}
        for isin, in q("SELECT isin FROM news.securities WHERE exchange='NSE' AND is_active AND sector IS NULL"):
            codes = codes_by_isin.get(isin or "", [])
            if not codes:
                reasons["NSE: no BSE listing, so no industry source"] += 1
            elif not any(c in cache for c in codes):
                reasons["NSE: BSE industry not fetched"] += 1
            elif all(not (cache.get(c) or {}).get("IndustryNew") for c in codes):
                reasons["NSE: BSE industry blank (IndustryNew empty)"] += 1
            else:
                reasons["NSE: IndustryNew has no mapping"] += 1
        bse_only_null = q("SELECT alt_symbol, symbol FROM news.securities WHERE exchange='BSE' AND is_active AND primary_listing_id IS NULL AND sector IS NULL")
        reasons["BSE-only: IndustryNew blank or unmapped"] = len(bse_only_null)
        out += ["### Why a sector is NULL", "", _table(["Reason", "Securities"], list(reasons.items())), ""]

        null_nse = q("SELECT symbol, name, isin FROM news.securities WHERE exchange='NSE' AND is_active AND sector IS NULL ORDER BY symbol")
        out += [f"## NSE securities with no sector ({len(null_nse)})", "",
                "The allowed sources carry no market-cap data, so \"largest\" cannot be ranked; these are the first 30 by symbol.", "",
                _table(["Symbol", "Name", "ISIN"], [tuple(r) for r in null_nse[:30]]), ""]

        out += ["## Aliases", "", _table(["alias_type", "Total", "Ambiguous"], [tuple(r) for r in q(
            "SELECT alias_type, count(*), count(*) FILTER (WHERE is_ambiguous) FROM news.security_aliases GROUP BY alias_type ORDER BY alias_type")]), ""]
        total = q("SELECT count(*), count(*) FILTER (WHERE is_ambiguous), count(DISTINCT alias_norm) FROM news.security_aliases")[0]
        out += [f"Total aliases: {total[0]}; ambiguous: {total[1]}; distinct normalized aliases: {total[2]}.", ""]

        shared = q("""
            SELECT a.alias_norm, count(DISTINCT coalesce(s.primary_listing_id, s.security_id)) AS owners,
                   bool_or(a.is_ambiguous), string_agg(DISTINCT coalesce(s.primary_listing_id, s.security_id), ', ' ORDER BY coalesce(s.primary_listing_id, s.security_id))
            FROM news.security_aliases a JOIN news.securities s USING (security_id)
            GROUP BY a.alias_norm HAVING count(DISTINCT coalesce(s.primary_listing_id, s.security_id)) > 1
            ORDER BY owners DESC, a.alias_norm LIMIT 30""")
        out += ["## 30 most-shared aliases (one alias, several primary securities)", "",
                _table(["alias_norm", "Primary securities", "is_ambiguous", "Securities (first 8)"],
                       [(r[0], r[1], r[2], ", ".join(r[3].split(", ")[:8])) for r in shared]), ""]

        sample = q("SELECT security_id, name FROM news.securities WHERE is_active AND primary_listing_id IS NULL ORDER BY md5(security_id) LIMIT 20")
        out += ["## 20 sample primary securities with all aliases", "(deterministic sample: ordered by md5 of the security_id)", ""]
        for sid, name in sample:
            aliases = q("SELECT alias, alias_type, is_ambiguous, case_sensitive FROM news.security_aliases WHERE security_id=:s ORDER BY alias_type, alias", s=sid)
            out.append(f"**{sid}** — {name}")
            out += [f"- `{a}` ({t}{', ambiguous' if amb else ''}{', case-sensitive' if cs else ''})" for a, t, amb, cs in aliases] or ["- (no aliases)"]
            out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("main", "test"), default="main")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(get_engine(args.target)), encoding="utf-8", newline="\n")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())