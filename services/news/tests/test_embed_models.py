"""The REAL embedding model (BAAI/bge-base-en-v1.5, CPU). Not part of the default run:  python dev.py test -m models"""
import numpy as np
import pytest

from src.news.embed.model import Embedder, embed_query

pytestmark = pytest.mark.models


@pytest.fixture(scope="module")
def embedder():
    return Embedder()


def test_real_embedding_has_768_dimensions_and_is_normalized(embedder):
    v = np.array(embedder.encode(["Infosys raises revenue guidance"])[0])
    assert embedder.dim == 768 and v.shape == (768,) and abs(np.linalg.norm(v) - 1.0) < 1e-3


def test_a_similar_pair_scores_higher_than_an_unrelated_pair(embedder):
    a, b, c = np.array(embedder.encode(["Infosys raises FY27 revenue guidance after strong deal wins",
                                        "Infosys lifts its FY27 revenue outlook on large deals", "Monsoon rains flood parts of Kerala"]))
    assert a @ b > a @ c + 0.2 and a @ b > 0.8


def test_query_embedding_uses_the_prefix(embedder):
    q = np.array(embed_query("repo rate decision", embedder))
    d = np.array(embedder.encode(["repo rate decision"])[0])
    assert q.shape == d.shape and not np.allclose(q, d)
