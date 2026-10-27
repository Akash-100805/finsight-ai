"""Startup checks (guide L4). Raise StartupCheckError with a clear message on the first failure."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from src.news.settings import Settings, get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
MIN_PGVECTOR = (0, 7)


class StartupCheckError(RuntimeError):
    pass


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split(".") if p.isdigit())


def alembic_head() -> str:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        raise StartupCheckError("no Alembic revisions found in migrations/versions")
    return head


def check_embedding_dimension(embedder, settings: Settings | None = None) -> None:
    """The model's output dimension must equal EMBEDDING_DIM (which run_startup_checks already matched to the DB column)."""
    settings = settings or get_settings()
    if int(embedder.dim) != settings.EMBEDDING_DIM:
        raise StartupCheckError(f"embedding model {getattr(embedder, 'model_name', '?')} outputs {embedder.dim} dimensions, "
                                f"but EMBEDDING_DIM / the database column is {settings.EMBEDDING_DIM}")


def run_startup_checks(engine: Engine, settings: Settings | None = None, embedder=None) -> None:
    settings = settings or get_settings()
    with engine.connect() as conn:
        # (i) pgvector >= 0.7
        installed = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
        if installed is None:
            raise StartupCheckError("pgvector extension is not installed in this database; run: python dev.py migrate")
        if _version_tuple(installed) < MIN_PGVECTOR:
            raise StartupCheckError(f"pgvector {installed} is installed; version >= 0.7 is required")

        # (ii) migrations at head
        head = alembic_head()
        try:
            current = conn.execute(text("SELECT version_num FROM news.alembic_version")).scalar()
        except DBAPIError:
            conn.rollback()
            raise StartupCheckError("migrations have not been applied (news.alembic_version is missing); run: python dev.py migrate") from None
        if current != head:
            raise StartupCheckError(f"database is at migration {current!r} but head is {head!r}; run: python dev.py migrate")

        # (iii) embedding column is halfvec(EMBEDDING_DIM)
        declared = conn.execute(text(
            "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
            "WHERE a.attrelid = 'news.article_embeddings'::regclass AND a.attname = 'embedding' AND NOT a.attisdropped"
        )).scalar()
        expected = f"halfvec({settings.EMBEDDING_DIM})"
        if declared != expected:
            raise StartupCheckError(f"news.article_embeddings.embedding is {declared}, but config requires {expected}")

    # (iv) the embedding model's output dimension == EMBEDDING_DIM == the column (only when a model is given: ingest loads it once)
    if embedder is not None:
        check_embedding_dimension(embedder, settings)
