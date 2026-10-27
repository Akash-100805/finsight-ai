"""Enrichment: security resolution, sentiment, classification.

ENRICHMENT_VERSION is stored on every article (news.articles.enrichment_version). Bump it whenever matching, classification or
sentiment LOGIC changes, so old rows can be told apart and re-enriched.
"""
ENRICHMENT_VERSION = "5.1"
