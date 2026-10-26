"""Builds docs/review/phase4_enrichment.md from an enriched JSONL file (data_cache/enriched/<name>.jsonl)."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from src.news.enrich.cli import ENRICHED_DIR

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUT = REPO_ROOT / "docs" / "review" / "phase4_enrichment.md"


def table(headers, rows) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join("" if v is None else str(v).replace("|", "\\|").replace("\n", " ") for v in row) + " |" for row in rows]
    return "\n".join(lines)


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def dist(counter: Counter, total: int) -> list[tuple]:
    return [(k, v, pct(v, total)) for k, v in counter.most_common()]


def build(rows: list[dict], meta: dict, flags: dict[tuple[str, str], str], names: dict[str, str]) -> str:
    n = len(rows)
    out = ["# Phase 4 enrichment review", "",
           f"Generated {date.today().isoformat()} from `{n}` saved articles (the Phase 3 and Phase 4 dry runs, deduplicated by canonical URL). "
           "No new API calls and nothing written to `news.articles`.", ""]

    # per source -----------------------------------------------------------------------------------------------
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_source[r["source_id"]].append(r)
    methods = ["exchange_filing", "provider_confirmed", "dictionary_ner", "dictionary_context", "provider_only"]
    src_rows = []
    for sid, rs in sorted(by_source.items()):
        with_sec = sum(1 for r in rs if r["securities"])
        mix = Counter(l["method"] for r in rs for l in r["securities"])
        total_links = sum(mix.values())
        src_rows.append((sid, len(rs), pct(with_sec, len(rs)), total_links, ", ".join(f"{m}={mix[m]}" for m in methods if mix[m]) or "-"))
    all_with = sum(1 for r in rows if r["securities"])
    out += ["## Articles with at least one security, and the method mix, per source", "",
            table(["Source", "Articles", "With >= 1 security", "Links", "Method mix"], src_rows),
            "", f"**All sources: {all_with} of {n} articles ({pct(all_with, n)}) have at least one linked security.**", ""]

    # top matched aliases -----------------------------------------------------------------------------------------
    alias_counts: Counter = Counter()
    sources_of: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for r in rows:
        for l in r["securities"]:
            for t in set(l["matched_text"]):
                alias_counts[(t, l["security_id"], l["method"])] += 1
                sources_of[(t, l["security_id"])][r["source_id"]] += 1
    by_text = Counter()
    for (t, sid, m), c in alias_counts.items():
        by_text[(t, sid)] += c
    top = by_text.most_common(60)
    method_of = {}
    for (t, sid, m), c in alias_counts.items():
        method_of.setdefault((t, sid), Counter())[m] += c
    top_rows = []
    for (t, sid), c in top:
        mm = method_of[(t, sid)].most_common(1)[0][0]
        verdict = flags.get((t, sid), "")
        src = ", ".join(f"{k} {v}" for k, v in sources_of[(t, sid)].most_common(2))
        top_rows.append((c, f"`{t}`", f"`{sid}`", names.get(sid, ""), mm, src, verdict))
    out += ["## Top 60 matched aliases (false-positive check)", "",
            "Count = articles in which the text matched. The last column is my judgement: `WRONG` marks a match that links to the "
            "wrong company, `CHECK` marks one that is right only sometimes. Empty means it looks right.", "",
            table(["Articles", "Matched text", "Security", "Name", "Method", "Mostly from", "Looks wrong?"], top_rows), ""]

    # other likely false positives: ordinary single words that were accepted ----------------------------------------
    from wordfreq import zipf_frequency
    words: Counter = Counter()
    for (t, sid), c in by_text.items():
        if " " not in t.strip() and t.isalpha() and zipf_frequency(t.lower(), "en") >= 3.5 and not t.isupper():
            words[(t, sid)] = c
    out += ["## Other accepted matches that are ordinary English words (outside the top 60)", "",
            "Single common words (wordfreq score >= 3.5) that were accepted as a company. Each one needed a context cue in its sentence "
            "(for example the word `shares` or `results`), which these headlines happen to contain.", "",
            table(["Articles", "Matched text", "Security", "Name", "Looks wrong?"], [(c, f"`{t}`", f"`{sid}`", names.get(sid, ""), flags.get((t, sid), "")) for (t, sid), c in words.most_common(30)]), ""]

    # unresolved -------------------------------------------------------------------------------------------------
    un: dict[str, Counter] = defaultdict(Counter)
    filing_examples, filing_total = [], 0
    for r in rows:
        company = (r.get("filing") or {}).get("company_name")
        for u in r["unresolved"]:
            if company and u["raw_text"] == company:
                filing_total += 1
                if len(filing_examples) < 12:
                    filing_examples.append(company)
                continue
            un[u["reason"]][u["raw_text"]] += 1
    out += ["## Top 40 unresolved raw texts by reason", ""]
    for reason in ("ambiguous_no_context", "no_master_match", "unsupported_exchange", "low_confidence"):
        if un.get(reason):
            out += [f"### {reason} ({sum(un[reason].values())} mentions, {len(un[reason])} distinct)", "",
                    table(["Raw text", "Mentions"], un[reason].most_common(40)), ""]
    out += [f"## Exchange filings that did not resolve ({filing_total})", "",
            "Company names from NSE filings that matched no NSE security by exact normalized name (no guess is made). Examples:", ""]
    out += [f"- {c}" for c in filing_examples] or ["- none"]
    out.append("")

    # sentiment ------------------------------------------------------------------------------------------------
    per_sec = Counter(l["finbert_label"] for r in rows for l in r["securities"])
    methods_mix = Counter(l["sentiment_method"] for r in rows for l in r["securities"])
    art_lab = Counter(r["article_sentiment_label"] for r in rows)
    total_links = sum(per_sec.values())
    out += ["## FinBERT", "", "### Per-security label", "", table(["Label", "Links", "Share"], dist(per_sec, total_links)), "",
            "### Per-security sentiment method", "", table(["Method", "Links", "Share"], dist(methods_mix, total_links)), "",
            "### Article-level label (all articles)", "", table(["Label", "Articles", "Share"], dist(art_lab, n)), ""]

    # classification -------------------------------------------------------------------------------------------------
    events = Counter(r["event_type"] for r in rows)
    cats = Counter(r["category"] for r in rows)
    geos = Counter(r["geo_scope"] for r in rows)
    domains = Counter(r["domain"] for r in rows)
    origins = Counter(r["event_origin"].split(":")[0] for r in rows)
    out += ["## Classification", "", f"**event_type = other: {events['other']} of {n} ({pct(events['other'], n)})**", "",
            "### event_type", "", table(["event_type", "Articles", "Share"], dist(events, n)), "",
            "### Where the event_type came from", "", table(["Origin", "Articles", "Share"], dist(origins, n)), "",
            "### category", "", table(["category", "Articles", "Share"], dist(cats, n)), "",
            "### geo_scope", "", table(["geo_scope", "Articles", "Share"], dist(geos, n)), "",
            "### domain", "", table(["domain", "Articles", "Share"], dist(domains, n)), ""]
    other_by_source = Counter(r["source_id"] for r in rows if r["event_type"] == "other")
    out += ["### event_type = other, by source", "",
            table(["Source", "other", "of", "Share"], [(s, c, len(by_source[s]), pct(c, len(by_source[s]))) for s, c in other_by_source.most_common()]), ""]
    with_sector = sum(1 for r in rows if r["sectors"])
    out += ["## Sectors from securities", "",
            f"**{with_sector} of {n} articles ({pct(with_sector, n)}) have at least one `from_security` sector** (link confidence >= 0.70 and a known sector).", ""]

    # random sample ------------------------------------------------------------------------------------------------
    rng = random.Random(7)
    sample = rng.sample(rows, min(30, n))
    out += ["## 30 random enriched articles", "", "(random sample, seed 7)", ""]
    for i, r in enumerate(sample, 1):
        out += [f"### {i}. {r['title']}", "",
                f"- source `{r['source_id']}`, published {r['published_at']}",
                f"- category `{r['category']}` ({r['category_origin']}), event `{r['event_type']}` ({r['event_origin']}), geo `{r['geo_scope']}`, "
                f"countries {r['countries']}, domain `{r['domain']}`",
                f"- article sentiment {r['article_sentiment_score']} ({r['article_sentiment_label']})",
                "- sectors: " + (", ".join(f"{s['sector']} ({s['confidence']})" for s in r["sectors"]) or "none")]
        for l in r["securities"]:
            out.append(f"- **{l['security_id']}** {names.get(l['security_id'], '')} - {l['role']}, {l['method']} {l['confidence']}, matched {l['matched_text']}, "
                       f"FinBERT {l['finbert_score']} {l['finbert_label']} ({l['sentiment_method']}, {l['finbert_n_sentences']} sentence(s))")
        for u in r["unresolved"][:4]:
            out.append(f"- unresolved: `{u['raw_text']}` ({u['reason']})")
        out.append("")

    out += ["## Timing on this machine (CPU)", "", "```", json.dumps(meta, indent=1), "```", ""]
    return "\n".join(out)


def main() -> int:
    from src.news.db.engine import get_engine
    from sqlalchemy import text

    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="all")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--flags", default="", help="JSON file {\"text|security_id\": \"WRONG: ...\"} for the top-60 table")
    args = parser.parse_args()
    path = ENRICHED_DIR / f"{args.name}.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    with get_engine("main").connect() as conn:
        names = {r[0]: r[1] for r in conn.execute(text("SELECT security_id, name FROM news.securities"))}
    flags: dict[tuple[str, str], str] = {}
    if args.flags:
        for k, v in json.loads(Path(args.flags).read_text(encoding="utf-8")).items():
            t, sid = k.split("|")
            flags[(t, sid)] = v
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(build(rows, meta, flags, names), encoding="utf-8", newline="\n")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
