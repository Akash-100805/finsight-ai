r"""Writes data_cache/bse_industry/<scrip_code>.json from a compact browser export.

Export format (JSON; the dictionaries only need to be in one of the files): {"i": [Industry values], "s": [Sector values], "n": [IndustryNew values],
                       "r": "code,iIdx,sIdx,nIdx;code,iIdx,sIdx,nIdx;..."}
The ISIN is filled in from the cached BSE scrip list. Codes that are already cached are skipped.

Run from services/news:  .venv\Scripts\python.exe tools\bse_industry_import.py export1.json [export2.json ...]
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.news.security_master import sources  # noqa: E402
from src.news.security_master.parse import parse_bse  # noqa: E402

CACHE_DIR = ROOT / "data_cache" / "bse_industry"


def main(paths: list[str]) -> int:
    isin_by_code = {b.scrip_cd: b.isin for b in parse_bse(sources.fetch_bse(offline=True))}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    written = skipped = bad = 0
    exports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    dictionary = next(e for e in exports if "i" in e)  # the value dictionaries need to be in at least one file
    for export in exports:
        for item in filter(None, export["r"].split(";")):
            code, i, s, n = item.split(",")
            if not re.fullmatch(r"\d{4,8}", code) or code not in isin_by_code:
                bad += 1
                continue
            target = CACHE_DIR / f"{code}.json"
            if target.exists():
                skipped += 1
                continue
            target.write_text(json.dumps({
                "SecurityCode": code, "ISIN": isin_by_code[code], "Industry": dictionary["i"][int(i)],
                "Sector": dictionary["s"][int(s)], "IndustryNew": dictionary["n"][int(n)],
                "_fetched_at": datetime.now(timezone.utc).isoformat(), "_source": "BSE ComHeader (selected fields)",
            }), encoding="utf-8")
            written += 1
    print(f"written {written}, already cached {skipped}, rejected {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))