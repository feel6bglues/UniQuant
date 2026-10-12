"""回归测试：mootdx 离线源 Bug1（日期过滤失效）+ Bug2（freq/frequency 被 kwargs 吞）。

依据 docs/analysis/DATA_SOURCE_MIGRATION_PLAN.md §6 Step 1。

Bug1: StdReader.daily()/minute() 返回 DatetimeIndex，列中无 'date'，
      `if 'date' in df.columns` 恒 False -> 请求区间恒返回全历史泄露。
Bug2: StdReader.minute 签名为 (symbol=None, suffix=1, **kwargs)，
      传 freq=/frequency= 被 **kwargs 吞 -> 静默降级为 1min。

测试全部 mock，不触碰真实数据湖。
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from uniquant.data.sources.mootdx_local import MootdxLocalSource


def _make_ohlcv_frame(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "amount": 1000.0,
            "volume": 100.0,
        },
        index=index,
    )


def _daily_full_history(index_name: str = "date") -> pd.DataFrame:
    idx = pd.date_range("2015-01-05", "2025-08-01", freq="B")
    return _make_ohlcv_frame(idx.rename(index_name))


def _make_source(reader: MagicMock) -> MootdxLocalSource:
    src = MootdxLocalSource(tdx_dir="/fake/tdx")
    src._reader = reader
    return src


# --- Bug1: 日期过滤失效 ---


def test_fetch_daily_filters_to_requested_range():
    """红用例①: DatetimeIndex 场景下 fetch_daily 必须按 start/end 过滤，
    不得返回全历史。"""
    full = _daily_full_history("date")
    reader = MagicMock()
    reader.daily.return_value = full
    src = _make_source(reader)

    df = src.fetch_daily("600519.SH", "2020-01-01", "2020-12-31")

    assert not df.empty, "过滤后应有数据"
    assert len(df) < len(full), "返回行数必须小于全历史（过滤生效）"
    dates = pd.to_datetime(df["date"])
    assert (dates >= pd.Timestamp("2020-01-01")).all(), "存在早于 start 的行"
    assert (dates <= pd.Timestamp("2020-12-31")).all(), "存在晚于 end 的行"


def test_fetch_daily_filters_when_index_named_datetime():
    """index 列名为 'datetime' 时同样必须过滤（且列统一为 date）。"""
    full = _daily_full_history("datetime")
    reader = MagicMock()
    reader.daily.return_value = full
    src = _make_source(reader)

    df = src.fetch_daily("600519.SH", "2021-06-01", "2021-06-30")

    assert not df.empty
    assert len(df) < len(full)
    assert "date" in df.columns, "datetime index 应统一重命名为 date 列"
    dates = pd.to_datetime(df["date"])
    assert (dates >= pd.Timestamp("2021-06-01")).all()
    assert (dates <= pd.Timestamp("2021-06-30")).all()


def test_fetch_daily_keeps_existing_date_column_semantics():
    """已含 date 列的输入仍按 start/end 过滤（语义不变）。"""
    idx = pd.date_range("2022-01-01", periods=260, freq="B")
    df_in = _make_ohlcv_frame(pd.RangeIndex(len(idx)))
    df_in["date"] = idx
    reader = MagicMock()
    reader.daily.return_value = df_in
    src = _make_source(reader)

    df = src.fetch_daily("600519.SH", "2022-03-01", "2022-03-31")

    assert not df.empty
    assert len(df) < len(df_in)
    dates = pd.to_datetime(df["date"])
    assert (dates >= pd.Timestamp("2022-03-01")).all()
    assert (dates <= pd.Timestamp("2022-03-31")).all()


# --- Bug2: freq/frequency 被 kwargs 吞 ---


def test_fetch_minute_passes_suffix_not_freq():
    """红用例②: fetch_minute 必须以 suffix=5 调用 StdReader.minute，
    不得传 freq=（被 **kwargs 吞后静默降级 1min）。"""
    idx = pd.date_range("2026-06-01 09:35", periods=10, freq="5min")
    reader = MagicMock()
    reader.minute.return_value = _make_ohlcv_frame(idx.rename("date"))
    src = _make_source(reader)

    src.fetch_minute("600519.SH", freq=5)

    kwargs = reader.minute.call_args.kwargs
    assert kwargs.get("suffix") == 5, f"应收到 suffix=5，实际 kwargs={kwargs}"
    assert "freq" not in kwargs, "freq= 会被 **kwargs 吞导致降级 1min"
    assert "frequency" not in kwargs, "frequency= 会被 **kwargs 吞导致降级 1min"


def _minute_frame() -> pd.DataFrame:
    idx = pd.date_range("2026-06-01 09:35", periods=10, freq="5min")
    return _make_ohlcv_frame(idx.rename("date"))


def test_sync_minute_uses_suffix_and_matching_data_type(tmp_path, monkeypatch):
    """红用例③: sync 脚本以 frequency='5min' 调用时，
    reader 必须收到 suffix=5，且写湖 data_type 为 '5mins'（两者一致）。"""
    from uniquant.data.scripts import sync_minute_mootdx

    monkeypatch.setattr(sync_minute_mootdx, "PROGRESS_FILE", tmp_path / "progress.json")

    reader = MagicMock()
    reader.minute.return_value = _minute_frame()
    storage = MagicMock()

    with patch("mootdx.reader.Reader.factory", return_value=reader), patch(
        "uniquant.data.lake.storage_manager.StorageManager", return_value=storage
    ):
        success, fail = sync_minute_mootdx.sync_minute(
            "/fake/tdx", str(tmp_path), "5min", symbols=["600519.SH"]
        )

    kwargs = reader.minute.call_args.kwargs
    assert kwargs.get("suffix") == 5, f"应收到 suffix=5，实际 kwargs={kwargs}"
    assert "frequency" not in kwargs, "frequency= 被 **kwargs 吞 -> 降级 1min"
    assert "freq" not in kwargs, "freq= 被 **kwargs 吞 -> 降级 1min"

    storage.write_data.assert_called_once()
    write_kwargs = storage.write_data.call_args.kwargs
    assert write_kwargs["data_type"] == "5mins", f"data_type 应为 5mins，实际 {write_kwargs['data_type']}"
    assert (success, fail) == (1, 0)


def test_sync_minute_1min_suffix_matches_data_type(tmp_path, monkeypatch):
    """frequency='1min' 时 suffix=1 且 data_type='1mins'。"""
    from uniquant.data.scripts import sync_minute_mootdx

    monkeypatch.setattr(sync_minute_mootdx, "PROGRESS_FILE", tmp_path / "progress.json")

    idx = pd.date_range("2026-06-01 09:31", periods=10, freq="1min")
    reader = MagicMock()
    reader.minute.return_value = _make_ohlcv_frame(idx.rename("date"))
    storage = MagicMock()

    with patch("mootdx.reader.Reader.factory", return_value=reader), patch(
        "uniquant.data.lake.storage_manager.StorageManager", return_value=storage
    ):
        success, fail = sync_minute_mootdx.sync_minute(
            "/fake/tdx", str(tmp_path), "1min", symbols=["600519.SH"]
        )

    kwargs = reader.minute.call_args.kwargs
    assert kwargs.get("suffix") == 1, f"应收到 suffix=1，实际 kwargs={kwargs}"
    assert "frequency" not in kwargs
    write_kwargs = storage.write_data.call_args.kwargs
    assert write_kwargs["data_type"] == "1mins"
    assert (success, fail) == (1, 0)
