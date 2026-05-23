LIMIT_UP_ST_CODES = {"688", "689", "300", "301", "302"}
ST_LIMIT_PCT = 0.05  # ST 股票 ±5% 涨跌停


def is_limit_up(row: dict, prev_close: float, code_prefix: str,
                is_st: bool = False) -> bool:
    if is_st:
        limit_pct = ST_LIMIT_PCT
    elif code_prefix in LIMIT_UP_ST_CODES:
        limit_pct = 0.20
    else:
        limit_pct = 0.10
    pct = (row["close"] - prev_close) / prev_close if prev_close > 0 else 0
    return pct >= limit_pct - 1e-8


def is_limit_down(row: dict, prev_close: float, code_prefix: str,
                  is_st: bool = False) -> bool:
    if is_st:
        limit_pct = ST_LIMIT_PCT
    elif code_prefix in LIMIT_UP_ST_CODES:
        limit_pct = 0.20
    else:
        limit_pct = 0.10
    pct = (row["close"] - prev_close) / prev_close if prev_close > 0 else 0
    return pct <= -limit_pct + 1e-8
