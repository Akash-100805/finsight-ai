"""Strong context cues for ambiguous aliases (guide 6.3, step 3). A cue must occur in the SAME sentence as the matched text.

Three cues count, nothing else (rupee signs, crore, Nifty, Sensex, results and quarters do NOT):
  (a) the match is followed within two tokens by Ltd | Limited | Inc | Corp | Industries | shares | stock | share price | scrip;
  (b) the security's own ticker appears in upper case in the sentence (outside the match);
  (c) an exchange-qualified ticker of the security: "NSE: INFY", "BSE: 500209", "(NASDAQ: AAPL)", "(NYSE: SE)".
Capitalization is never evidence: a capital letter at the start of a sentence says nothing about a name.
"""
import re

FOLLOWING_CUES = frozenset({"ltd", "limited", "inc", "corp", "industries", "shares", "stock", "scrip"})
FOLLOW_WINDOW = 2
QUALIFIED_TICKER = re.compile(r"\b(NSE|BSE|NASDAQ|NYSE|CBOE)\s*:\s*([A-Za-z0-9&.\-]+)")


def following_cue(next_norms: list[str]) -> bool:
    """next_norms: the normalized tokens after the match, inside the same sentence (any length; only the first two are looked at)."""
    window = next_norms[:FOLLOW_WINDOW]
    if any(n in FOLLOWING_CUES for n in window):
        return True
    return any(n == "share" and next_norms[i + 1:i + 2] == ["price"] for i, n in enumerate(window))


def qualified_tickers(sentence: str) -> set[tuple[str, str]]:
    """{(EXCHANGE, SYMBOL)} for every exchange-qualified ticker written in the sentence."""
    return {(m.group(1).upper(), m.group(2).upper().rstrip(".")) for m in QUALIFIED_TICKER.finditer(sentence)}
