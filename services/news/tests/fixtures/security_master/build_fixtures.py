"""Regenerates the small REAL fixtures in this folder from the cached downloads in data_cache/ (run from services/news).

Rows are selected by fixed rules, not edited: every fixture row is a verbatim row of the real file.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from finsight_shared.sectors import NSE_SECTORS  # noqa: E402
from src.news.security_master import bse_industry as bi  # noqa: E402
from src.news.security_master import sources  # noqa: E402
from src.news.security_master.parse import parse_bse, parse_nifty, parse_nse, parse_sec  # noqa: E402

OUT = Path(__file__).resolve().parent
LABELS = {label for _, label in NSE_SECTORS}
DUAL_TM = ["RELIANCE", "TCS", "INFY", "ITC", "ETERNAL", "TITAN"]
US_TICKERS = ["GOOGL", "GOOG", "AAPL", "MSFT", "NVDA", "BRK-B", "BRK-A", "JPM", "XOM"]


def raw_rows(path: Path):
    text = path.read_bytes().decode("utf-8-sig")
    lines = text.splitlines()
    return lines[0], {i: l for i, l in enumerate(lines[1:])}


def main():
    nse_path, bse_path, tm_path = sources.fetch_nse(True), sources.fetch_bse(True), sources.fetch_nifty_total_market(True)
    nse, bse, tm = parse_nse(nse_path), parse_bse(bse_path), parse_nifty(tm_path)
    cache = bi.load_cache()
    tm_symbols = {n.symbol for n in tm}
    bse_by_isin = {}
    for b in bse:
        bse_by_isin.setdefault(b.isin, []).append(b)
    nse_isins = {n.isin for n in nse}

    dual = [n for n in nse if n.symbol in DUAL_TM]
    non_tm = sorted((n for n in nse if n.symbol not in tm_symbols and n.isin in bse_by_isin
                     and bse_by_isin[n.isin][0].scrip_cd in cache), key=lambda n: n.symbol)
    direct = [n for n in non_tm if cache[bse_by_isin[n.isin][0].scrip_cd]["IndustryNew"] in LABELS][:5]
    mapped = [n for n in non_tm if cache[bse_by_isin[n.isin][0].scrip_cd]["IndustryNew"] not in LABELS][:2]
    nse_only = sorted((n for n in nse if n.isin not in {b.isin for b in bse} and n.symbol not in tm_symbols), key=lambda n: n.symbol)[:3]
    bse_only_all = sorted((b for b in bse if b.isin not in nse_isins and b.scrip_cd in cache), key=lambda b: b.scrip_cd)
    bse_only = bse_only_all[:5] + [b for b in bse_only_all if not cache[b.scrip_cd]["IndustryNew"]][:1]

    nse_sel = dual + direct + mapped + nse_only
    nse_syms = {n.symbol for n in nse_sel}
    bse_sel = [b for n in nse_sel for b in bse_by_isin.get(n.isin, [])] + bse_only
    seen, bse_final = set(), []
    for b in bse_sel:
        if b.scrip_cd not in seen:
            seen.add(b.scrip_cd)
            bse_final.append(b)

    # write verbatim rows
    def pick(path, keep, key_of_line):
        header, rows = raw_rows(path)
        lines = [l for l in rows.values() if keep(key_of_line(l))]
        return header, lines

    h, l = pick(nse_path, lambda k: k in nse_syms, lambda line: line.split(",")[0].strip().upper())
    (OUT / "nse.csv").write_text("\n".join([h, *l]) + "\n", encoding="utf-8", newline="\n")
    h, l = pick(tm_path, lambda k: k in nse_syms, lambda line: line.split(",")[-3].strip().upper())
    (OUT / "nifty_total_market.csv").write_text("\n".join([h, *l]) + "\n", encoding="utf-8", newline="\n")
    codes = {b.scrip_cd for b in bse_final}
    h, l = pick(bse_path, lambda k: k in codes, lambda line: line.split(",")[0].strip())
    (OUT / "bse.csv").write_text("\n".join([h, *l]) + "\n", encoding="utf-8", newline="\n")
    (OUT / "bse_industry.json").write_text(json.dumps({c: cache[c] for c in sorted(codes) if c in cache}, indent=1), encoding="utf-8", newline="\n")

    # SEC: all rows of the chosen CIKs, plus one OTC row and one row with no exchange
    sec_path = sources.fetch_sec_tickers(True)
    sec = parse_sec(sec_path)
    chosen = {r.cik for r in sec if r.ticker in US_TICKERS and r.exchange in ("Nasdaq", "NYSE", "CBOE")}
    extra = [next(r for r in sec if r.exchange == "OTC"), next(r for r in sec if r.exchange == ""),
             next(r for r in sec if r.exchange == "CBOE")]
    rows = [r for r in sec if r.cik in chosen] + extra
    full = json.loads(sec_path.read_text(encoding="utf-8"))
    keep = {(r.cik, r.ticker) for r in rows}
    data = [row for row in full["data"] if (row[0], row[2]) in keep]
    (OUT / "sec_tickers.json").write_text(json.dumps({"fields": full["fields"], "data": data}, indent=1), encoding="utf-8", newline="\n")
    sic = sources.load_sic_cache()
    (OUT / "sec_sic.json").write_text(json.dumps({str(c): sic.get(str(c)) for c in sorted({r[0] for r in data})}, indent=1), encoding="utf-8", newline="\n")
    print("nse", len(nse_sel), "bse", len(bse_final), "sec rows", len(data), "direct", len(direct), "mapped", len(mapped), "nse_only", len(nse_only), "bse_only", len(bse_only))


if __name__ == "__main__":
    main()