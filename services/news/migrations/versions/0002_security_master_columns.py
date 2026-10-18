"""security master columns, article sentiment label check, NSE sector seed

Revision ID: 0002_security_master_columns
Revises: 0001_news_schema_baseline
Create Date: 2026-10-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_security_master_columns"
down_revision: Union[str, Sequence[str], None] = "0001_news_schema_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen NSE sector list (literal; sector_id = slug of the label). Must equal shared/finsight_shared/sectors.py.
NSE_SECTORS = [
    ("automobile_and_auto_components", "Automobile and Auto Components"),
    ("capital_goods", "Capital Goods"),
    ("chemicals", "Chemicals"),
    ("construction", "Construction"),
    ("construction_materials", "Construction Materials"),
    ("consumer_durables", "Consumer Durables"),
    ("consumer_services", "Consumer Services"),
    ("diversified", "Diversified"),
    ("fast_moving_consumer_goods", "Fast Moving Consumer Goods"),
    ("financial_services", "Financial Services"),
    ("forest_materials", "Forest Materials"),
    ("healthcare", "Healthcare"),
    ("information_technology", "Information Technology"),
    ("media_entertainment_and_publication", "Media Entertainment & Publication"),
    ("metals_and_mining", "Metals & Mining"),
    ("oil_gas_and_consumable_fuels", "Oil Gas & Consumable Fuels"),
    ("power", "Power"),
    ("realty", "Realty"),
    ("services", "Services"),
    ("telecommunication", "Telecommunication"),
    ("textiles", "Textiles"),
    ("utilities", "Utilities"),
]


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("ALTER TABLE news.securities ADD COLUMN cik TEXT")
    op.execute("ALTER TABLE news.securities ADD COLUMN alt_symbol TEXT")
    op.execute("ALTER TABLE news.securities ADD COLUMN sector_method TEXT "
               "CONSTRAINT ck_securities_sector_method CHECK (sector_method IN ('nifty_index','bse_industry_map','sic_map'))")
    op.execute("CREATE INDEX ix_securities_cik ON news.securities (cik)")
    op.execute("CREATE INDEX ix_securities_alt_symbol ON news.securities (alt_symbol)")
    op.execute("ALTER TABLE news.articles ADD CONSTRAINT ck_articles_sentiment_label "
               "CHECK (article_sentiment_label IN ('positive','neutral','negative'))")
    op.execute("INSERT INTO news.sectors (sector_id, label, is_macro) VALUES "
               + ", ".join(f"({_q(i)}, {_q(l)}, false)" for i, l in NSE_SECTORS))


def downgrade() -> None:
    op.execute("UPDATE news.securities SET sector = NULL WHERE sector IN (SELECT sector_id FROM news.sectors WHERE NOT is_macro)")
    op.execute("DELETE FROM news.article_sectors WHERE sector IN (SELECT sector_id FROM news.sectors WHERE NOT is_macro)")
    op.execute("DELETE FROM news.sectors WHERE NOT is_macro")
    op.execute("ALTER TABLE news.articles DROP CONSTRAINT ck_articles_sentiment_label")
    op.execute("DROP INDEX news.ix_securities_alt_symbol")
    op.execute("DROP INDEX news.ix_securities_cik")
    op.execute("ALTER TABLE news.securities DROP COLUMN sector_method")
    op.execute("ALTER TABLE news.securities DROP COLUMN alt_symbol")
    op.execute("ALTER TABLE news.securities DROP COLUMN cik")