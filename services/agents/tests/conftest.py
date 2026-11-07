"""Test configuration: live_smoke tests make REAL LLM calls and are skipped unless explicitly requested.

    pytest -m live_smoke --run-live-smoke -s tests/test_live_smoke.py
"""
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-live-smoke", action="store_true", default=False, help="run the live_smoke tests (real LLM calls; uses quota)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live-smoke"):
        return
    skip = pytest.mark.skip(reason="live_smoke: real LLM calls; run with --run-live-smoke when the owner says so")
    for item in items:
        if "live_smoke" in item.keywords:
            item.add_marker(skip)
