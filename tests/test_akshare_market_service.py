from types import SimpleNamespace

import pandas as pd

from uniquant.data.utils.akshare_market_service import AkshareMarketService


def test_akshare_market_service_fetch_stock_daily_uses_first_valid_dataset():
    calls = []
    service = AkshareMarketService(
        lambda method_name, **kwargs: calls.append((method_name, kwargs))
        or (
            pd.DataFrame({"bad": [1]})
            if method_name == "stock_zh_a_daily"
            else pd.DataFrame({"date": ["2026-04-24"], "volume": [1], "amount": [2]})
        )
    )

    result = service.fetch_stock_daily("000001.SZ", "2026-04-01", "2026-04-24")

    assert not result.empty
    assert calls[0][0] == "stock_zh_a_daily"
    assert calls[1][0] == "stock_zh_a_hist"


def test_akshare_market_service_fetch_stock_spot_falls_back():
    method_results = {
        "stock_zh_a_spot": pd.DataFrame(),
        "stock_zh_a_spot_em": pd.DataFrame({"symbol": ["000001"]}),
    }
    service = AkshareMarketService(lambda method_name, **kwargs: method_results.get(method_name))

    result = service.fetch_stock_spot("sina")

    assert result.iloc[0]["symbol"] == "000001"


def test_akshare_market_service_filters_dragon_tiger_rows():
    source = pd.DataFrame({"代码": ["000001", "600519"], "名称": ["平安银行", "茅台"]})
    service = AkshareMarketService(lambda method_name, **kwargs: source)

    result = service.fetch_dragon_tiger_list("000001.SZ", "20260401", "20260424")

    assert result["代码"].tolist() == ["000001"]
