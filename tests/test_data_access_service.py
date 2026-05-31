from types import SimpleNamespace

import pandas as pd

from uniquant.services.data_access_service import DataAccessService


def test_data_access_service_fetch_data_prefers_cache():
    cached = pd.DataFrame({"date": ["2026-04-24"], "close": [10.0]})
    service = SimpleNamespace(
        _get_cache_key=lambda *args, **kwargs: "k",
        _clone_dataframe=lambda df: None if df is None else df.copy(deep=True),
        _get_cached=lambda key: cached,
    )

    result = DataAccessService(service).fetch_data("000001.SZ", "2026-04-01", "2026-04-24")

    assert result.iloc[0]["close"] == 10.0
    assert result is not cached


def test_data_access_service_load_data_with_fallback_checks_index_aliases():
    frames = {
        "000300.SH": pd.DataFrame({"date": ["2026-04-24"], "close": [1.0]}),
    }
    lake = SimpleNamespace(read_data=lambda symbol, **kwargs: frames.get(symbol, pd.DataFrame()))
    service = SimpleNamespace(
        lake=lake,
        _clone_dataframe=lambda df: None if df is None else df.copy(deep=True),
        fetcher=SimpleNamespace(get_price=lambda *args, **kwargs: pd.DataFrame()),
        cleaner=SimpleNamespace(clean_stock_daily=lambda df: df),
    )

    result = DataAccessService(service).load_data_with_fallback(
        "sh000300", "index", "benchmark"
    )

    assert result.iloc[0]["close"] == 1.0


def test_data_access_service_fetch_and_save_dataset_writes_cleaned_stock():
    written = {}
    source = pd.DataFrame({"date": ["2026-04-24"], "close": [10.0]})
    service = SimpleNamespace(
        fetcher=SimpleNamespace(fetch_stock_daily=lambda *args, **kwargs: source),
        cleaner=SimpleNamespace(clean_stock_daily=lambda df: df.assign(cleaned=True)),
        lake=SimpleNamespace(
            write_data=lambda symbol, df, data_type, market="cn", overwrite=True: written.update(
                {"symbol": symbol, "data_type": data_type, "rows": len(df)}
            ),
            read_data=lambda symbol, data_type, market="cn": pd.DataFrame(
                {"date": ["2026-04-24"], "cleaned": [True]}
            ),
        ),
    )

    result = DataAccessService(service).fetch_and_save_dataset(
        "000001.SZ", "2026-04-01", "2026-04-24", data_type="stock"
    )

    assert written == {"symbol": "000001.SZ", "data_type": "stock", "rows": 1}
    assert result.iloc[0]["cleaned"]
