# BSE industry fetch (browser-driven)

BSE's `ComHeader` API returns `Industry`, `Sector` and `IndustryNew` per scrip but answers HTTP 403 to scripts, so the fetch
runs inside a real browser tab on bseindia.com. The browser pane could not reach a local receiver, so the page keeps the
results in memory and they are exported in compact batches into `tools/bse_industry_import.py`.

1. `cd services/news`, then `.venv\Scripts\python.exe -m src.news.security_master.bse_industry` â€” writes the scrips that still
   need an industry to `data_cache/bse_industry/_needed.json`.
2. Open https://www.bseindia.com/ in a browser tab. In its console, fetch the needed scrips one at a time, at most 2 per
   second, store `[Industry, Sector, IndustryNew, ISIN, SecurityCode]` per scrip code in `window.__res`, and on a 403/429 pause
   with growing backoff and stop after 10 consecutive blocks:

   `https://api.bseindia.com/BseIndiaAPI/api/ComHeader/w?quotetype=EQ&scripcode=<code>&seriesid=`

3. Export `window.__res` as JSON (in batches if large), save it to a file and run
   `.venv\Scripts\python.exe tools\bse_industry_import.py <file.json>` â€” it writes one
   `data_cache/bse_industry/<scrip_code>.json` per scrip and skips codes that are already cached.
4. `python dev.py securities-refresh` picks the cache up.