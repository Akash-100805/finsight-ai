import pytest

from finsight_shared.security_id import SUPPORTED_EXCHANGES, make_security_id, parse_security_id
from finsight_shared import vocab


def test_make_uppercases_and_strips():
    assert make_security_id("nse", " reliance ") == "NSE:RELIANCE"
    assert make_security_id("BSE", "500325") == "BSE:500325"


def test_make_rejects_empty_or_colon():
    for bad in (("", "X"), ("NSE", ""), ("NSE", "  "), ("N:SE", "X"), ("NSE", "A:B")):
        with pytest.raises(ValueError):
            make_security_id(*bad)


def test_parse_roundtrip():
    assert parse_security_id("NASDAQ:AAPL") == ("NASDAQ", "AAPL")
    assert parse_security_id(make_security_id("nyse", "brk.b")) == ("NYSE", "BRK.B")


@pytest.mark.parametrize("bad", ["", "AAPL", "NSE:", ":AAPL", "NSE:A:B", "nse:aapl", None, 5])
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_security_id(bad)


def test_supported_exchanges():
    assert SUPPORTED_EXCHANGES == ("NSE", "BSE", "NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "CBOE", "OTC")


def test_vocab_sizes_and_uniqueness():
    assert len(vocab.CATEGORIES) == 7 and len(vocab.EVENT_TYPES) == 25
    assert len({c[0] for c in vocab.CATEGORIES}) == 7
    assert len({e[0] for e in vocab.EVENT_TYPES}) == 25