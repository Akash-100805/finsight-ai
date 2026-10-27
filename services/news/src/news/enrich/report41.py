"""docs/review/phase4_1_enrichment.md: BEFORE (the saved Phase 4 enrichment) -> AFTER (this code), over the same saved dry-run articles.

    python -m src.news.enrich.report41
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from wordfreq import zipf_frequency

ROOT = Path(__file__).resolve().parents[5]
ENR = ROOT / "services" / "news" / "data_cache" / "enriched"
OUT = ROOT / "docs" / "review" / "phase4_1_enrichment.md"

# (label, predicate(record, link))
CANDIDATES = [
    ("SMP (Senior Management Personnel)", lambda r, s: "SMP" in s["matched_text"]),
    ("Bank of India inside Reserve Bank of India items (RBI sources)", lambda r, s: r["source_id"].startswith("rbi_") and s["security_id"] == "NSE:BANKINDIA"),
    ("key / Key", lambda r, s: any(t.lower() == "key" for t in s["matched_text"])),
    ("bullish", lambda r, s: any(t.lower() == "bullish" for t in s["matched_text"])),
    ("BSE (exchange read as BSE Ltd)", lambda r, s: s["security_id"] == "NSE:BSE" and any(t == "BSE" for t in s["matched_text"])),
    ("people", lambda r, s: any(t.lower() == "people" for t in s["matched_text"])),
    ("happen", lambda r, s: any(t.lower() == "happen" for t in s["matched_text"])),
    ("Sea", lambda r, s: any(t.lower() == "sea" for t in s["matched_text"])),
    ("mega", lambda r, s: any(t.lower() == "mega" for t in s["matched_text"])),
    ("persistent", lambda r, s: any(t.lower() == "persistent" for t in s["matched_text"])),
    ("strategy", lambda r, s: any(t.lower() == "strategy" for t in s["matched_text"])),
    ("Delta", lambda r, s: any(t.lower() == "delta" for t in s["matched_text"])),
    ("Bancorp Inc (generic official name)", lambda r, s: any("bancorp inc" in t.lower() for t in s["matched_text"]) and s["security_id"] == "NASDAQ:TBBK"),
]


def load(name: str) -> list[dict]:
    path = ENR / name
    return [r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "enriched"]


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in row) + " |" for row in rows]
    return "\n".join(out)


def hits(rows: list[dict], pred) -> list[tuple[dict, dict]]:
    return [(r, s) for r in rows for s in r["securities"] if pred(r, s)]


def per_source(rows: list[dict]) -> dict[str, tuple[int, int]]:
    c, t = Counter(), Counter()
    for r in rows:
        t[r["source_id"]] += 1
        c[r["source_id"]] += bool(r["securities"])
    return {s: (c[s], t[s]) for s in t}


def suspicious(text_: str) -> bool:
    toks = text_.split()
    return len(toks) == 1 and (zipf_frequency(text_.lower(), "en") >= 3.0 or (text_.isupper() and len(text_) <= 4))


def build(before: list[dict], after: list[dict], meta_after: dict) -> str:
    out = ["# Phase 4.1 enrichment: before and after", "",
           f"The same saved dry-run articles ({len(after) + sum(meta_after.get('rejected_out_of_scope', {}).values())} in), enriched by the Phase 4 code (BEFORE) and by the "
           "Phase 4.1 code (AFTER). No new API calls; nothing written to `news.articles`.", ""]

    out += ["## 1. Phase 4 false-positive candidates", "", "Articles whose links include the candidate, BEFORE -> AFTER.", ""]
    rows, remaining = [], []
    for label, pred in CANDIDATES:
        b, a = hits(before, pred), hits(after, pred)
        rows.append([label, len({id(r) for r, _ in b}), len({id(r) for r, _ in a})])
        if a:
            remaining.append((label, a[:3]))
    out += [table(["Candidate", "BEFORE", "AFTER"], rows), ""]
    if remaining:
        out += ["### Remaining matches (up to 3 each)", ""]
        for label, examples in remaining:
            out.append(f"**{label}**")
            for r, s in examples:
                out.append(f"- `{r['source_id']}` {r['title'][:110]} -> {s['security_id']} via `{'/'.join(s['matched_text'])}` ({s['method']})")
            out.append("")
    else:
        out += ["No candidate matches remain.", ""]

    out += ["## 2. Articles with a security, per source", ""]
    pb, pa = per_source(before), per_source(after)
    rows = [[s, f"{pct(*pb[s])} ({pb[s][0]}/{pb[s][1]})", f"{pct(*pa[s])} ({pa[s][0]}/{pa[s][1]})" if s in pa else "0 (all rejected)"] for s in sorted(pb)]
    tb, ta = sum(v[0] for v in pb.values()), sum(v[0] for v in pa.values())
    rows.append(["**all**", f"{pct(tb, len(before))} ({tb}/{len(before)})", f"{pct(ta, len(after))} ({ta}/{len(after)})"])
    out += [table(["Source", "BEFORE", "AFTER"], rows), "", "### Resolution method mix (links)", ""]
    mb, ma = Counter(s["method"] for r in before for s in r["securities"]), Counter(s["method"] for r in after for s in r["securities"])
    out += [table(["Method", "BEFORE", "AFTER"], [[m, mb[m], ma[m]] for m in sorted(set(mb) | set(ma))]), ""]

    out += ["## 3. Sentiment method mix (links)", ""]
    sb, sa = Counter(s["sentiment_method"] for r in before for s in r["securities"]), Counter(s["sentiment_method"] for r in after for s in r["securities"])
    nb, na = sum(sb.values()), sum(sa.values())
    out += [table(["sentiment_method", "BEFORE", "AFTER"], [[m, f"{sb[m]} ({pct(sb[m], nb)})", f"{sa[m]} ({pct(sa[m], na)})"] for m in sorted(set(sb) | set(sa))]), "",
            f"`shared_clause` share AFTER: {pct(sa['shared_clause'], na)} of links.", ""]
    lb = Counter(s["finbert_label"] for r in before for s in r["securities"])
    la = Counter(s["finbert_label"] for r in after for s in r["securities"])
    out += [table(["Per-security label", "BEFORE", "AFTER"], [[m, f"{lb[m]} ({pct(lb[m], nb)})", f"{la[m]} ({pct(la[m], na)})"] for m in ("positive", "neutral", "negative")]), ""]

    out += ["## 4. Event type 'other'", ""]
    def other(rows_, src=None):
        pool = [r for r in rows_ if src is None or r["source_id"] == src]
        return sum(r["event_type"] == "other" for r in pool), len(pool)
    ob, oa, nb_, na_ = other(before), other(after), other(before, "nse_announcements"), other(after, "nse_announcements")
    out += [table(["Share of 'other'", "BEFORE", "AFTER", "target"], [
        ["overall", f"{pct(*ob)} ({ob[0]}/{ob[1]})", f"{pct(*oa)} ({oa[0]}/{oa[1]})", "< 15%"],
        ["NSE announcements", f"{pct(*nb_)} ({nb_[0]}/{nb_[1]})", f"{pct(*na_)} ({na_[0]}/{na_[1]})", "< 15%"]]), ""]
    ev = Counter(r["event_type"] for r in after)
    out += ["### Event type mix AFTER", "", table(["event_type", "n"], [[k, v] for k, v in ev.most_common()]), ""]
    by_src = Counter(r["source_id"] for r in after if r["event_type"] == "other")
    out += ["### 'other' AFTER by source", "", table(["source", "other", "of"], [[s, n, sum(r['source_id'] == s for r in after)] for s, n in by_src.most_common()]), ""]
    titles = Counter((r["source_id"], r["title"].split(": ", 1)[-1][:110]) for r in after if r["event_type"] == "other")
    out += ["### Top 30 remaining 'other' titles (NSE titles shown without the company prefix)", "",
            table(["n", "source", "title"], [[n, s, t] for (s, t), n in titles.most_common(30)]), ""]

    out += ["## 5. out_of_scope", "",
            f"Exchange filings whose company is not in the security master are rejected as `out_of_scope` / `issuer_not_in_master`: "
            f"**{sum(meta_after.get('rejected_out_of_scope', {}).values())}** (BEFORE: 0 rejected, {sum(1 for r in before if r['filing'] and not r['securities'])} filings sat unlinked).", ""]

    out += ["## 6. Top 60 matched aliases AFTER", "", "`suspicious` = a single ordinary word or a short upper-case token: check these first.", ""]
    c = Counter((t, s["security_id"]) for r in after for s in r["securities"] if s["method"] != "exchange_filing" for t in s["matched_text"])
    rows = [[n, t, sid, "SUSPICIOUS" if suspicious(t) else ""] for (t, sid), n in c.most_common(60)]
    out += [table(["n", "matched text", "security", "flag"], rows), ""]
    return "\n".join(out)


def main() -> int:
    before, after = load("phase4_all.jsonl"), load("all.jsonl")
    meta = json.loads((ENR / "all.meta.json").read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(before, after, meta), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
