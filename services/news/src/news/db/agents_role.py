"""Create (or rotate) the login role `finsight_agents` on both Neon projects and write its connection strings to the root .env.

    python dev.py agents-role

The role is a member of `news_reader` (SELECT on the three views, the recency table, securities, aliases and embeddings; EXECUTE on
news.recency_weight) and has no other privilege: it cannot read news.articles. The passwords are random, written to .env only, and never printed.
"""
from __future__ import annotations

import re
import secrets
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.news.db.engine import get_engine
from src.news.settings import ENV_FILE, get_settings

ROLE = "finsight_agents"
ENV_NAMES = {"main": "AGENTS_DATABASE_URL", "test": "AGENTS_TEST_DATABASE_URL"}


def agents_url(owner_url: str, password: str) -> str:
    url = make_url(owner_url).set(username=ROLE, password=password)
    rendered = url.render_as_string(hide_password=False)
    if rendered.startswith("postgresql+psycopg2://"):
        rendered = "postgresql://" + rendered[len("postgresql+psycopg2://"):]
    return rendered


def set_env_line(name: str, value: str) -> None:
    """Replace or append NAME=value in the .env file (nothing is printed)."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    new = f"{name}={value}"
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{name}\s*=", line):
            lines[i] = new
            break
    else:
        lines.append(new)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_role(target: str) -> str:
    password = secrets.token_urlsafe(32)                      # [A-Za-z0-9_-]: safe inside a SQL string literal
    engine = get_engine(target)
    owner_url = (get_settings().DATABASE_URL if target == "main" else get_settings().TEST_DATABASE_URL).get_secret_value()
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}).scalar()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(text(f"{verb} ROLE {ROLE} LOGIN PASSWORD '{password}'"))
        conn.execute(text(f"GRANT news_reader TO {ROLE}"))
    set_env_line(ENV_NAMES[target], agents_url(owner_url, password))
    return "rotated" if exists else "created"


def main() -> int:
    for target in ("main", "test"):
        print(f"{target}: role {ROLE} {ensure_role(target)}; {ENV_NAMES[target]} written to .env (value not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
