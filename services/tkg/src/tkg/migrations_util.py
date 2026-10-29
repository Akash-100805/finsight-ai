"""Helpers shared by the Alembic revisions (raw multi-statement SQL, news-schema placeholder)."""
from pathlib import Path

NEWS_PLACEHOLDER = "{{NEWS_SCHEMA}}"
SQL_DIR = Path(__file__).resolve().parents[2] / "alembic" / "sql"


def render_sql(sql: str, news_schema: str) -> str:
    """Substitute the news schema (news on main, news_stub on test). The schema name is validated."""
    if not news_schema.replace("_", "").isalnum():
        raise ValueError(f"Invalid news schema name: {news_schema!r}")
    return sql.replace(NEWS_PLACEHOLDER, news_schema)


def run_sql(connection, sql: str, news_schema: str = "news") -> None:
    """Execute a multi-statement SQL script on an Alembic/SQLAlchemy connection (no bind parameters)."""
    cursor = connection.connection.cursor()
    try:
        cursor.execute(render_sql(sql, news_schema))
    finally:
        cursor.close()


def read_sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")
