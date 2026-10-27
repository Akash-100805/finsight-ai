"""agents-smoke: for each sample portfolio print every holding's security_id, sector, current price, sentiment signal (or the reason it is missing)
and its sector's TKG-lite signal (or the reason), then make one LLM ping per model role (model name and latency only; never the key).

    python dev.py agents-smoke [--target main|test] [--skip-llm]
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

from pydantic import BaseModel

from finsight.core.portfolio_scan import scan_portfolio
from finsight.data import news, prices
from finsight.data.common import Unavailable
from finsight.data.llm import LLMBudgetError, LLMClient, LLMOutputError
from finsight.data.sector_signal import SectorProviderError, get_sector_provider
from finsight.schemas.state import Holding
from finsight.settings import AGENTS_ROOT, SettingsError, get_settings

SAMPLES = AGENTS_ROOT / "samples"
warnings.filterwarnings("ignore")        # yfinance / pandas deprecation chatter


class Ping(BaseModel):
    ok: bool


def fmt_signal(sig) -> str:
    if isinstance(sig, Unavailable):
        return f"unavailable ({sig.reason}: {sig.detail})" if sig.detail else f"unavailable ({sig.reason})"
    return f"{sig['score']:+.3f} (n={sig['n_articles']})"


def fmt_sector(sig) -> str:
    if isinstance(sig, Unavailable):
        return f"unavailable ({sig.reason}: {sig.detail})" if sig.detail else f"unavailable ({sig.reason})"
    return f"{sig['score']:+.3f} (confidence {sig['confidence']:.2f}, n={sig['n']}, source {sig['source']})"


def run_portfolio(path: Path, target: str, provider) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n=== {path.name}  ({data['user_id']}) ===")
    print(data.get("description", ""))
    holdings: list[Holding] = []
    rows = []
    for raw in data["holdings"]:
        h = Holding(ticker=raw["ticker"], quantity=raw["quantity"], average_cost=raw.get("average_cost"))
        info = news.security_info(h.ticker, target=target)
        if isinstance(info, Unavailable):
            rows.append((h, None, info, None, None))
            holdings.append(h)
            continue
        h.sector = info["sector"]
        price = prices.current_price(info["security_id"])
        if not isinstance(price, Unavailable):
            h.current_price = price
        holdings.append(h)
        rows.append((h, info, price, news.sentiment_signal(info["security_id"], target=target), None))
    sectors = sorted({h.sector for h, info, *_ in rows if info and h.sector})
    sector_sig = provider.sector_signals(sectors) if sectors else {}
    ok = True
    print(f"{'ticker':<14}{'security_id':<16}{'sector':<32}{'price':>11}  sentiment_signal")
    for h, info, price, sentiment, _ in rows:
        if info is None:
            print(f"{h.ticker:<14}{'-':<16}{'-':<32}{'-':>11}  NOT RESOLVED: {price.reason}: {price.detail}")
            ok = False
            continue
        ptxt = f"{price:,.2f}" if not isinstance(price, Unavailable) else f"n/a({price.reason})"
        print(f"{h.ticker:<14}{info['security_id']:<16}{str(info['sector']):<32}{ptxt:>11}  {fmt_signal(sentiment)}")
    print("sector signals (" + provider.source + "):")
    for sid in sectors:
        print(f"  {sid:<32}{fmt_sector(sector_sig[sid])}")
    scan = scan_portfolio(holdings)
    print("portfolio scan (existing thresholds, values summed as quoted - no currency conversion):")
    print("  sector_exposure:", {k: round(v, 3) for k, v in sorted(scan.sector_exposure.items(), key=lambda kv: -kv[1])})
    print("  concentration_flags:", scan.concentration_flags or "none")
    return ok


def llm_pings() -> bool:
    s = get_settings()
    client = LLMClient(s)
    ok = True
    print(f"\n=== LLM ping (provider {s.AGENTS_LLM_PROVIDER}) ===")
    for role in ("stock", "synth"):
        try:
            model = s.llm_model(role)
            out = client.complete_json("You are a connectivity check.", 'Return {"ok": true}.', Ping, model_role=role)
            rec = client.records[-1]
            print(f"  {role:<6} model={model}  valid_json={out.ok is True}  latency={rec.latency_s:.2f}s")
            ok = ok and out.ok is True
        except (SettingsError, LLMOutputError, LLMBudgetError) as exc:
            print(f"  {role:<6} FAILED: {type(exc).__name__}: {exc}")
            ok = False
        except Exception as exc:                       # provider/network errors: the message only, never the key
            print(f"  {role:<6} FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents-smoke")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args(argv)
    s = get_settings()
    print(f"news window {s.NEWS_WINDOW_DAYS} days; sentiment min {s.SENTIMENT_MIN_ARTICLES}; sector min {s.SECTOR_MIN_ARTICLES}; "
          f"shared_clause weight {s.SHARED_CLAUSE_WEIGHT}; sector provider {s.SECTOR_PROVIDER}; database {args.target}")
    try:
        provider = get_sector_provider(s, target=args.target) if s.SECTOR_PROVIDER == "tkg_lite" else get_sector_provider(s)
    except SectorProviderError as exc:
        print("sector provider:", exc)
        return 1
    ok = True
    try:
        for path in sorted(SAMPLES.glob("portfolio_*.json")):
            ok = run_portfolio(path, args.target, provider) and ok
    except SectorProviderError as exc:
        print("sector provider FAILED:", exc)
        return 1
    if not args.skip_llm:
        ok = llm_pings() and ok
    print("\nagents-smoke:", "OK" if ok else "FAILED (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
