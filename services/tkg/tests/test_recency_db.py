"""
DB test for Step 6.5:
Compares local compute_recency_weight with news.recency_weight(published_at, category, as_of)
in the database for every category at ages 0, 1, 3, 30 and 90 days (tolerance 1e-6).
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from tkg.graph.scoring import compute_recency_weight
from tkg.settings import settings
from tkg.database import get_engine

CATEGORIES = [
    "company",
    "markets",
    "economy_macro",
    "central_bank_monetary_policy",
    "geopolitical",
    "commodities_energy",
    "government_regulation",
]

AGES_DAYS = [0, 1, 3, 30, 90]


def test_recency_weight_comparison_with_db():
    """
    Step 6.5: Compare local recency function with news.recency_weight(published_at, category)
    for every category at ages 0, 1, 3, 30 and 90 days (tolerance 1e-6).
    """
    db_url = settings.TKG_TEST_DATABASE_URL or settings.TKG_DATABASE_URL
    if not db_url or "sqlite" in db_url:
        pytest.skip("Postgres DB URL not configured; skipping live DB recency function test")

    engine = get_engine(db_url)
    as_of = datetime.now(timezone.utc)

    with engine.connect() as conn:
        for cat in CATEGORIES:
            for age in AGES_DAYS:
                published_at = as_of - timedelta(days=age)
                # Compute using local Python function
                py_weight = compute_recency_weight(published_at, cat, as_of)

                # Compute using DB SQL function
                sql = text("SELECT news.recency_weight(:published_at, :category, :as_of)")
                db_result = conn.execute(
                    sql,
                    {"published_at": published_at, "category": cat, "as_of": as_of}
                ).scalar()

                assert db_result is not None, f"news.recency_weight returned None for {cat}"
                db_weight = float(db_result)

                assert abs(py_weight - db_weight) < 1e-6, (
                    f"Mismatch for category='{cat}', age={age}d: "
                    f"python={py_weight}, db={db_weight}, diff={abs(py_weight - db_weight)}"
                )
