# FinSight AI demo kit

A five-minute walkthrough of the portfolio-insight flow: news pipeline → signals → agents → compliance. Everything runs locally.
Repo root `C:\FinSight\finsight-ai`, PowerShell.

## Before the demo (10 minutes)

1. **News pipeline is fresh.** Start the loop in its own window and leave it running:
   `python dev.py run-loop --interval 30`
   Then check the newest article with `http://127.0.0.1:8000/health` (after step 3): `news_db.latest_published_at` should be from today. If it is old, run `python dev.py ingest` once and wait (a gap can take 10–20 minutes to embed).
2. **Agents smoke test passes:** `python dev.py agents-smoke` → every portfolio lists prices, sentiment and sector signals, and both LLM pings say `valid_json=True`. If a ping says "503 UNAVAILABLE", the model is busy; wait a minute and repeat.
3. **Start the demo server:** `python dev.py agents-serve` → http://127.0.0.1:8000 (local only, no login).
4. **Warm the caches** by running each sample once from the page (or `python dev.py agents-run --sample concentrated_it`, `india_diversified`, `mixed_us`). This caches the day's prices and exchange rate, so the live run is faster and does not depend on Yahoo being quick.
5. **Open a browser tab** on http://127.0.0.1:8000 and keep the sticky disclaimer at the bottom in view.

## The 5-minute script

**0:00 – What you are looking at (30 s).** "This reads a portfolio and tells you what the news and the prices say about each holding. It does not tell you what to do. The disclaimer is pinned to the bottom of every screen."

**0:30 – Concentrated IT portfolio (90 s).** Pick *concentrated_it* → Run analysis. While it works (about 30–60 s) explain the stage list: "holdings and prices, a portfolio scan, three signals per stock, a fusion step that picks what deserves a closer look, a deep dive on those, then a written summary that is checked for advice language."
- Point at the overview: IT is about 88% of the portfolio, and Infosys and HCL are over 20% each — the concentration flags in the holdings table.
- Open the shortlist card for **Infosys**: negative news tone, a deep-drawdown risk flag, and the key points, each with a **Source headline** link you can click to read the original article.
- Say what the three chips mean: structural (price vs the Nifty over a year, plus concentration), news sentiment, sector news. Grey “neutral” on the sector chip is deliberate: sector news was quiet, so it is not counted.

**2:00 – Diversified portfolio (60 s).** Pick *india_diversified*. Ten companies across ten sectors, no concentration flags. Point out that the shortlist can be short or empty, and that is a result: "nothing here needs a closer look today" is information too. Read the summary, then the data notes.

**3:00 – Mixed US portfolio (60 s).** Pick *mixed_us*. NVIDIA and Morgan Stanley are priced in dollars; the chip at the top shows the USD/INR rate used (₹ per dollar) to put everything in rupees before the concentration check. The weights change because of that conversion — that is the point of showing it.

**4:00 – Where the data comes from (60 s).** "Articles from exchange filings, regulators, business publishers and news APIs are fetched every 30 minutes, de-duplicated, matched to companies and sectors, scored by a finance sentiment model, and stored with embeddings. The agents read only a read-only view of that. Prices come from Yahoo Finance. Then a language model writes the summary from the structured signals, and a code check rejects advice words like buy, sell or hold before anything reaches the page."

**4:45 – Close (15 s).** Return to the disclaimer. "Insights and education, not advice."

## If something goes wrong

| What you see | What it means / what to say |
|---|---|
| Run takes longer than a minute | The Gemini model is busy. The client retries (5, 15, 30 seconds), then uses the fallback model if one is configured. This is normal on free-tier models. |
| Banner “auto-summary (LLM unavailable)” | The language model stayed unavailable through the retries and the fallback, so the text was built by fixed rules from the same signals. The numbers are identical; only the prose is plain. |
| Banner “auto-summary (LLM output withheld: compliance)” | The model's text used advice wording twice, so it was withheld and replaced by the rule-based summary. This is the safety check working. |
| A stock shows “News recheck unavailable (llm_unavailable)” | The model was busy for that stock; the vote uses the price signal alone, and the card says so. |
| A price shows “n/a” or a holding is “Not analysed” | Yahoo Finance did not answer or the symbol is not in the security master. The reason is shown; nothing is guessed. Re-run in a minute. |
| “US holdings are left out” in the data notes | The USD/INR rate could not be fetched. US positions are excluded rather than converted at a guessed rate. |
| Red error box with 422 | The pasted holdings were not valid; the box lists which field. |
| Page does not load | `python dev.py agents-serve` is not running, or port 8000 is in use. |

## Honest limitations (say these out loud)

- **Sector signals are a news-based estimate (“TKG-lite”)**, not the full temporal knowledge graph. The chip says so. Most days sector news is quiet, so the sector chip is often neutral.
- **The sentiment model (FinBERT) is limited**: it leans neutral, and it is weak on short sentences and on sentences that contrast two companies. Scores are averaged over many articles and are weak evidence on their own. The page shows no single-article scores for that reason.
- **Free-tier language models**: they can be slow or briefly unavailable, which is why retries, a fallback model and the rule-based summary exist.
- **Sample portfolios are illustrative** (made-up quantities and costs); only the companies, news and prices are real. US news coverage is thinner than Indian coverage.
- **Prices come from a free source** (Yahoo Finance) and can be delayed or missing.
- The shortlist thresholds (±0.3) are provisional and have not been back-tested.
