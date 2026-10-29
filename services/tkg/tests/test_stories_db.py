"""Story grouping (guide 7.4 / F2.5) on the Postgres TEST database, using pgvector similarity."""
import pytest
from sqlalchemy import text

from fixtures.news_stub import _basis
from helpers import AS_OF, seed_event
from tkg.graph.stories import assign_story_groups

pytestmark = pytest.mark.db


def near(base: int, wiggle: int, dim: int = 768):
    """A vector at cosine ~0.99 from _basis(base) (and from its siblings)."""
    v = _basis(base, dim)
    v[wiggle] = 0.1
    return v


def stories(session):
    rows = session.execute(text("SELECT event_id, story_id FROM tkg.events ORDER BY occurred_at, event_id")).all()
    return [(str(e), str(s)) for e, s in rows]


def test_five_near_identical_articles_within_72h_form_one_story(pg_session):
    ids = [seed_event(pg_session, title=f"Crude jumps report {i}", age_days=1 + i * 0.5,
                      embedding=near(0, 10 + i))[0] for i in range(5)]
    assign_story_groups(pg_session, as_of=AS_OF)
    got = stories(pg_session)
    assert len({s for _, s in got}) == 1
    first_event = got[0][0]                         # earliest occurred_at (oldest = highest age)
    assert got[0][1] == first_event and {e for e, _ in got} == {str(i) for i in ids}


def test_same_five_spread_over_ten_days_are_separate_stories(pg_session):
    for i in range(5):
        seed_event(pg_session, title=f"Crude jumps report {i}", age_days=1 + i * 4, embedding=near(0, 10 + i))
    assign_story_groups(pg_session, as_of=AS_OF)
    assert len({s for _, s in stories(pg_session)}) == 5


def test_running_twice_gives_identical_ids(pg_session):
    for i in range(4):
        seed_event(pg_session, title=f"Crude jumps report {i}", age_days=1 + i * 0.5, embedding=near(0, 10 + i))
    seed_event(pg_session, title="Unrelated policy news", age_days=1, embedding=_basis(50))
    seed_event(pg_session, title="No embedding at all", age_days=1)
    assign_story_groups(pg_session, as_of=AS_OF)
    first = stories(pg_session)
    changed = assign_story_groups(pg_session, as_of=AS_OF)
    assert changed == 0 and stories(pg_session) == first
    assert len({s for _, s in first}) == 3          # crude cluster, unrelated, no-embedding event on its own


def test_dissimilar_articles_never_merge(pg_session):
    for i in range(3):
        seed_event(pg_session, title=f"Different story {i}", age_days=1, embedding=_basis(20 + i))
    assign_story_groups(pg_session, as_of=AS_OF)
    assert len({s for _, s in stories(pg_session)}) == 3
