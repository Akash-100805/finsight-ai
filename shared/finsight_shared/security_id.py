"""Security ID format: EXCHANGE:SYMBOL, e.g. NSE:RELIANCE, BSE:500325, NASDAQ:AAPL."""

SUPPORTED_EXCHANGES = ("NSE", "BSE", "NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "CBOE", "OTC")


def make_security_id(exchange: str, symbol: str) -> str:
    exchange = (exchange or "").strip().upper()
    symbol = (symbol or "").strip().upper()
    if not exchange or not symbol:
        raise ValueError("exchange and symbol must both be non-empty")
    if ":" in exchange or ":" in symbol:
        raise ValueError("exchange and symbol must not contain ':'")
    return f"{exchange}:{symbol}"


def parse_security_id(security_id: str) -> tuple[str, str]:
    if not isinstance(security_id, str) or security_id.count(":") != 1:
        raise ValueError(f"malformed security id: {security_id!r}")
    exchange, symbol = security_id.split(":")
    if not exchange or not symbol or exchange != exchange.strip().upper() or symbol != symbol.strip().upper():
        raise ValueError(f"malformed security id: {security_id!r}")
    return exchange, symbol