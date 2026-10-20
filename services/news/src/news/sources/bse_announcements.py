"""BSE corporate announcements (unofficial JSON endpoint, the one the `bse` PyPI package uses).

STATUS: DISABLED (enabled: false in config/sources.yaml). On 2026-10-20 the single trial request to
https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w returned HTTP 403 "Access Denied" (Akamai), exactly like
the scrip-list API. Browser automation is not allowed for recurring ingestion, so this adapter stays dormant. The mapping
below follows the `bse` package's documented response (Table[] with NEWSID, SCRIP_CD, SLONGNAME, NEWSSUB/HEADLINE,
NEWS_DT, ATTACHMENTNAME) and has NOT been verified against a live response.
"""
from __future__ import annotations

from src.news.canonical import FilingInfo
from src.news.normalizers.text import clean_text
from src.news.sources.base import BROWSER_UA, Adapter, AdapterResult, Candidate, FetchContext, sanitize_error

URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
ATTACH_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"


def row_to_candidate(row: dict) -> Candidate:
    company = clean_text(row.get("SLONGNAME")) or ""
    subject = clean_text(row.get("HEADLINE") or row.get("NEWSSUB")) or ""
    attachment = row.get("ATTACHMENTNAME")
    attach_url = f"{ATTACH_BASE}{attachment}" if attachment else None
    return Candidate(
        url=attach_url or f"https://www.bseindia.com/corporates/ann.html?scrip={row.get('SCRIP_CD')}",
        title=f"{company}: {subject}".strip(": ") if company else subject or None,
        published=row.get("NEWS_DT") or row.get("DT_TM"),
        source_article_id=str(row["NEWSID"]) if row.get("NEWSID") else None,
        description=clean_text(row.get("MORE")),
        filing=FilingInfo(exchange="BSE", company_name=company, symbol_or_code=str(row.get("SCRIP_CD") or "") or None,
                          filing_type=str(row.get("CATEGORYNAME") or "announcement"), attachment_url=attach_url) if company else None,
        canonical_suffix=f"bse_item={row['NEWSID']}" if row.get("NEWSID") else None,
        raw_payload=dict(row),
    )


class BseAnnouncementsAdapter(Adapter):
    name = "bse_announcements"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        params = {"pageno": 1, "strCat": "-1", "strPrevDate": ctx.since.strftime("%Y%m%d"), "strScrip": "", "strSearch": "P",
                  "strToDate": ctx.now.strftime("%Y%m%d"), "strType": "C", "subcategory": "-1"}
        try:
            response = await ctx.http.get(URL, params=params, headers={"User-Agent": BROWSER_UA, "Referer": "https://www.bseindia.com/",
                                                                         "Accept": "application/json"})
        except Exception as exc:
            if type(exc).__name__ == "BudgetExhausted":
                raise
            result.status, result.error = "failure", sanitize_error(f"{type(exc).__name__}: {exc}")
            result.requests_made = ctx.http.requests_made
            return result
        result.requests_made = ctx.http.requests_made
        if response.status_code != 200:
            result.status, result.error = "failure", f"HTTP {response.status_code}"
            return result
        result.candidates = [row_to_candidate(r) for r in response.json().get("Table", [])]
        return result
