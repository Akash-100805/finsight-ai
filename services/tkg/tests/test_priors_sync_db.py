"""
DB test: priors-load makes the tkg prior tables mirror the CSVs exactly (TEST database only).

Uses a tiny temporary CSV set and runs inside an outer transaction that is rolled back,
so the full priors loaded in the TEST database are left untouched.
"""
import csv

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tkg.database import get_engine
from tkg.settings import settings
from tkg.priors_loader import load_priors_from_csv

pytestmark = pytest.mark.db

SECTOR_SENS = [
    ("drv:crude_oil_price", "oil_gas_and_consumable_fuels", 0.2),
    ("drv:crude_oil_price", "chemicals", -0.65),
    ("drv:steel_price", "construction", -0.4),
]
SECURITY_SENS = [
    ("drv:crude_oil_price", "NSE:IOC", -0.65),
    ("drv:crude_oil_price", "NSE:BPCL", -0.65),
    ("drv:natural_gas_price", "NSE:IGL", -0.6),
]
LINKS = [
    ("metals_and_mining", "capital_goods", "supplier_of", -0.4),
    ("metals_and_mining", "construction", "supplier_of", -0.4),
]


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([*r[:-1], r[-1], "tiny set", "true"] if len(header) == 5 and header[0] != "from_sector"
                       else [*r, "tiny set", "true"])


def _write_csvs(data_dir):
    _write(data_dir / "tkg_sector_sensitivity.csv",
           ["driver_id", "sector_id", "sensitivity", "rationale", "reviewed"], SECTOR_SENS)
    _write(data_dir / "tkg_security_sensitivity.csv",
           ["driver_id", "security_id", "sensitivity", "rationale", "reviewed"], SECURITY_SENS)
    _write(data_dir / "tkg_sector_links.csv",
           ["from_sector", "to_sector", "link", "weight", "rationale", "reviewed"], LINKS)


def test_priors_load_removes_rows_not_in_csv(tmp_path):
    test_url = settings.TKG_TEST_DATABASE_URL
    if not test_url:
        pytest.skip("TKG_TEST_DATABASE_URL not configured")
    if test_url == settings.TKG_DATABASE_URL:
        pytest.fail("TKG_TEST_DATABASE_URL equals TKG_DATABASE_URL; refusing to run against main")

    from fixtures.news_stub import setup_stub_news_schema

    engine = get_engine(test_url)
    boot = Session(engine)
    try:
        setup_stub_news_schema(boot)
    finally:
        boot.close()

    _write_csvs(tmp_path)
    data_dir = str(tmp_path)

    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        # Whatever full priors the TEST DB holds is pruned down to the tiny set, then rolled back below.
        first = load_priors_from_csv(session, data_dir=data_dir, news_schema="news_stub")
        assert first["sector_sensitivity"]["total"] == len(SECTOR_SENS)

        # Stale rows left over from an earlier CSV version.
        session.execute(text(
            "INSERT INTO tkg.sector_sensitivity (driver_id, sector_id, sensitivity, rationale, reviewed) "
            "VALUES ('drv:gold_price', 'financial_services', 0.6, 'stale', false)"))
        session.execute(text(
            "INSERT INTO tkg.sector_links (from_sector, to_sector, link, weight, rationale, reviewed) "
            "VALUES ('financial_services', 'realty', 'supplier_of', -0.6, 'stale', false)"))
        session.execute(text(
            "INSERT INTO tkg.security_sensitivity (driver_id, security_id, sensitivity, rationale, reviewed) "
            "VALUES ('drv:gold_price', 'NSE:TCS', 0.1, 'stale', false)"))
        session.commit()

        second = load_priors_from_csv(session, data_dir=data_dir, news_schema="news_stub")
        assert second["deleted"] == {"sector_sensitivity": 1, "security_sensitivity": 1, "sector_links": 1}

        for table, expected in (("sector_sensitivity", len(SECTOR_SENS)),
                                ("security_sensitivity", len(SECURITY_SENS)),
                                ("sector_links", len(LINKS))):
            assert session.execute(text(f"SELECT count(*) FROM tkg.{table}")).scalar() == expected
            assert session.execute(text(f"SELECT count(*) FROM tkg.{table} WHERE NOT reviewed")).scalar() == 0

        # Idempotent: a further load deletes nothing.
        third = load_priors_from_csv(session, data_dir=data_dir, news_schema="news_stub")
        assert sum(third["deleted"].values()) == 0
    finally:
        session.close()
        outer.rollback()
        conn.close()
