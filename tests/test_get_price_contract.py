"""get_price 湖优先重写 — 返回契约 TDD (Step3 WS-A).

预注册裁决 D1: get_price 不再走 source_router 爬虫链 (旧实现位置参数误传恒空表),
终态 = 湖优先单源: StorageManager.read_data -> 缺失时 MootdxLocalSource 本地兜底
-> 仍缺失返回空表 (不 raise)。

全部用例只用 tmp_path 合成 parquet / mock, 不触真实数据湖、不写盘 (见用例⑧)。
"""

import inspect
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from uniquant.data.data_fetcher import (
    GET_PRICE_LAKE_COLUMNS,
    GET_PRICE_RETURN_CONTRACT,
    DataFetcher,
)

SYMBOL = "600000.SH"

# 合成除权事件: 2024-01-15 每 10 股送 10 股 (split_ratio=10 -> load_and_clean /10 = 1.0)
EX_DATE = "2024-01-15"


def _dates(n: int = 19) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-02", periods=n)


def _lake_frame(symbol: str = SYMBOL, dates: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """构造湖 9 列日线 (date/open/high/low/close/amount/volume/reserved/code)。"""
    dates = dates if dates is not None else _dates()
    n = len(dates)
    close = [10.0 if d < pd.Timestamp(EX_DATE) else 5.0 for d in dates]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": [c + 0.1 for c in close],
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "amount": [c * 1000 for c in close],
            "volume": [100000 + i for i in range(n)],
            "reserved": [0] * n,
            "code": [symbol] * n,
        }
    )


def _make_fetcher(
    tmp_path, df: pd.DataFrame | None = None, symbol: str = SYMBOL
) -> DataFetcher:
    # Step4 (D5 R-5): 主数据缺文件硬失败 → 测试提供最小主数据表
    pd.DataFrame(
        {
            "code": ["sh.600000"],
            "name": ["浦发银行"],
            "代码": ["600000"],
            "ipoDate": ["1999-11-10"],
            "outDate": [""],
            "type": ["1"],
            "status": ["1"],
        }
    ).to_csv(tmp_path / "all_stock_codes.csv", index=False, encoding="utf-8-sig")
    fetcher = DataFetcher(data_dir=str(tmp_path))
    if df is not None:
        fetcher.storage_manager.write_data(symbol, df, data_type="daily")
        fetcher.clear_price_cache()
    return fetcher


def _write_gbbq(tmp_path):
    """合成 gbbq 基线 (Step2 8 列契约的子集, 供 CorporateActionAdjuster 读取)。"""
    gbbq_path = tmp_path / "fq" / "gbbq.parquet"
    gbbq_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "code": ["600000"],
            "market": [0],
            "date": [20240115],
            "category": [1],
            "cash_div": [0.0],
            "split_ratio": [10.0],
            "rights_ratio": [0.0],
            "rights_price": [0.0],
        }
    ).to_parquet(gbbq_path)
    return gbbq_path


def _real_adjuster(tmp_path):
    from uniquant.data.corporate_action import CorporateActionAdjuster

    adjuster = CorporateActionAdjuster(gbbq_path=_write_gbbq(tmp_path))
    adjuster.load_events()
    return adjuster


class TestGetPriceContract:
    """①-⑧ 预注册契约用例 + ⑨-⑬ 延伸契约 (量纲/符号解析/默认值/调用路径)。"""

    # ① 湖有数据: 9 列 + 行数 + date 升序 + 去重
    def test_lake_hit_returns_contract_columns_sorted_deduped(self, tmp_path):
        raw = _lake_frame()
        # 打乱顺序 + 注入重复 date, 契约要求升序去重
        shuffled = pd.concat([raw.iloc[::-1], raw.iloc[[0]]], ignore_index=True)
        fetcher = _make_fetcher(tmp_path, shuffled)

        result = fetcher.get_price(SYMBOL)

        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS
        assert len(result) == len(raw)
        assert result["date"].is_monotonic_increasing
        assert result["date"].duplicated().sum() == 0
        assert pd.api.types.is_datetime64_any_dtype(result["date"])
        assert len(result) == 19

    # ② 湖 miss -> MootdxLocalSource 本地兜底被调用
    def test_lake_miss_falls_back_to_mootdx_local(self, tmp_path):
        fallback = _lake_frame()

        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = fallback
            # 构造须在 patch 内: DataFetcher __init__ 即挂载本地源
            fetcher = _make_fetcher(tmp_path, None)
            result = fetcher.get_price(SYMBOL)

        local_cls.return_value.fetch_daily.assert_called_once()
        called_args = local_cls.return_value.fetch_daily.call_args[0]
        assert called_args[0] == SYMBOL
        assert len(result) == len(fallback)
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS

    # ②b 湖 hit 时不触发本地兜底
    def test_lake_hit_does_not_touch_local_source(self, tmp_path):
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            fetcher = _make_fetcher(tmp_path, _lake_frame())
            result = fetcher.get_price(SYMBOL)

        assert not result.empty
        local_cls.return_value.fetch_daily.assert_not_called()

    # ③ 双 miss -> 空表 + warning, 不 raise
    def test_double_miss_returns_empty_frame_and_warns(self, tmp_path):
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = pd.DataFrame()
            fetcher = _make_fetcher(tmp_path, None)
            with patch("uniquant.data.data_fetcher.logger") as mock_logger:
                result = fetcher.get_price(SYMBOL)

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS
        assert mock_logger.warning.called

    # ④ adjust="qfq": 含 adj_factor (10 列) + 末日锚点=原始价 + volume 不动
    def test_qfq_adds_adj_factor_keeps_anchor_and_volume(self, tmp_path):
        raw = _lake_frame()
        fetcher = _make_fetcher(tmp_path, raw)

        with patch(
            "uniquant.data.data_fetcher.get_corporate_action_adjuster",
            return_value=_real_adjuster(tmp_path),
        ):
            result = fetcher.get_price(SYMBOL, adjust="qfq")

        assert list(result.columns) == GET_PRICE_RETURN_CONTRACT["adjusted_columns"]
        assert len(result) == len(raw)
        # 末日锚点: qfq 后最后一日价格 == 湖原始价
        assert result["close"].iloc[-1] == raw["close"].iloc[-1]
        assert result["open"].iloc[-1] == raw["open"].iloc[-1]
        # volume 恒不调整 (量纲契约: 湖 volume = 股)
        assert (result["volume"].to_numpy() == raw["volume"].to_numpy()).all()
        # 复权确实生效: 除权日前价格减半 (10 送 10 -> factor 2.0, qfq_ratio 0.5)
        assert result["close"].iloc[0] == raw["close"].iloc[0] * 0.5
        assert result["adj_factor"].iloc[0] == 0.5
        assert result["adj_factor"].iloc[-1] == 1.0

    # ④b adjust="hfq" 同样带 adj_factor
    def test_hfq_returns_adjusted_contract(self, tmp_path):
        raw = _lake_frame()
        fetcher = _make_fetcher(tmp_path, raw)

        with patch(
            "uniquant.data.data_fetcher.get_corporate_action_adjuster",
            return_value=_real_adjuster(tmp_path),
        ):
            result = fetcher.get_price(SYMBOL, adjust="hfq")

        assert "adj_factor" in result.columns
        assert result["adj_factor"].iloc[0] == 1.0
        assert result["adj_factor"].iloc[-1] > 1.0

    # ⑤ adjust="" 不触发复权
    def test_adjust_empty_does_not_trigger_adjustment(self, tmp_path):
        raw = _lake_frame()
        fetcher = _make_fetcher(tmp_path, raw)

        with patch(
            "uniquant.data.data_fetcher.get_corporate_action_adjuster"
        ) as factory:
            result = fetcher.get_price(SYMBOL, adjust="")

        factory.assert_not_called()
        assert "adj_factor" not in result.columns
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS
        assert result["close"].tolist() == raw["close"].tolist()

    # ⑥ start/end 切片生效 (且切片在复权之后, 锚点不受窗口影响)
    def test_start_end_slicing(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, _lake_frame())

        result = fetcher.get_price(
            SYMBOL, adjust="", start_date="2024-01-08", end_date="2024-01-12"
        )

        assert len(result) == 5
        assert result["date"].min() == pd.Timestamp("2024-01-08")
        assert result["date"].max() == pd.Timestamp("2024-01-12")
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS

    # ⑦ 返回契约常量存在且列序正确
    def test_return_contract_constant(self):
        assert GET_PRICE_RETURN_CONTRACT["columns"] == [
            "date",
            "open",
            "high",
            "low",
            "close",
            "amount",
            "volume",
            "reserved",
            "code",
        ]
        assert GET_PRICE_RETURN_CONTRACT["columns"] == GET_PRICE_LAKE_COLUMNS
        assert GET_PRICE_RETURN_CONTRACT["adjusted_columns"] == (
            GET_PRICE_LAKE_COLUMNS + ["adj_factor"]
        )
        assert GET_PRICE_RETURN_CONTRACT["date_dtype"] == "datetime64[ns]"
        assert GET_PRICE_RETURN_CONTRACT["order"] == "date ascending"
        assert GET_PRICE_RETURN_CONTRACT["sources"] == ("lake", "mootdx_local")
        assert GET_PRICE_RETURN_CONTRACT["volume_unit"] == "shares"
        assert GET_PRICE_RETURN_CONTRACT["amount_unit"] == "CNY"

    # ⑧ 禁止回写: get_price 全路径 storage.write_data 零调用 (含湖 miss 兜底)
    def test_get_price_never_writes_back_to_lake(self, tmp_path):
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = _lake_frame()
            fetcher = _make_fetcher(tmp_path, None)
            spy = MagicMock(side_effect=AssertionError("get_price 禁止回写数据湖"))
            fetcher.storage_manager.write_data = spy
            with patch(
                "uniquant.data.data_fetcher.get_corporate_action_adjuster",
                return_value=_real_adjuster(tmp_path),
            ):
                fetcher.get_price(SYMBOL)
                fetcher.get_price(SYMBOL, adjust="qfq")

        spy.assert_not_called()

    # ⑨ 湖 miss + 双源全空时也不回写
    def test_double_miss_never_writes_back(self, tmp_path):
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = pd.DataFrame()
            fetcher = _make_fetcher(tmp_path, None)
            spy = MagicMock(side_effect=AssertionError("get_price 禁止回写数据湖"))
            fetcher.storage_manager.write_data = spy
            result = fetcher.get_price(SYMBOL, adjust="qfq")

        assert result.empty
        spy.assert_not_called()

    # ⑩ 本地兜底量纲: volume 对齐湖契约 (股), 自校准不误伤已是股的数据
    def test_local_fallback_volume_harmonized_to_shares(self, tmp_path):
        def _fallback(amount_per_unit: float) -> pd.DataFrame:
            dates = pd.bdate_range("2024-02-01", periods=8)
            volume = [100.0 + i for i in range(8)]
            close = [10.0] * 8
            return pd.DataFrame(
                {
                    "date": dates,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "amount": [c * v * amount_per_unit for c, v in zip(close, volume)],
                    "volume": volume,
                    "code": [SYMBOL] * 8,
                }
            )

        # 本地输出 volume=手 (amount/(close*vol) ≈ 100) -> 校正为股
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = _fallback(100.0)
            fetcher = _make_fetcher(tmp_path, None)
            hand = fetcher.get_price(SYMBOL)

        assert hand["volume"].iloc[0] == 100.0 * 100
        # amount 恒不动 (已是元)
        assert hand["amount"].iloc[0] == 10.0 * 100.0 * 100.0

        # 本地输出已是股 (比值 ≈ 1, 如 ETF) -> 不做任何缩放
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = _fallback(1.0)
            fetcher2 = _make_fetcher(tmp_path, None)
            share = fetcher2.get_price(SYMBOL)

        assert share["volume"].iloc[0] == 100.0
        assert share["amount"].iloc[0] == 10.0 * 100.0

    # ⑪ fetch_stock_daily 默认 adjust="qfq" 保持不变 + 内部改走 get_price 切片
    @pytest.mark.requires_gbbq  # 默认 qfq 需 GBBQ 基线 (data/fq/gbbq.parquet, gitignored)
    def test_fetch_stock_daily_routes_through_get_price(self, tmp_path):
        sig = inspect.signature(DataFetcher.fetch_stock_daily)
        assert sig.parameters["adjust"].default == "qfq"

        fetcher = _make_fetcher(tmp_path, _lake_frame())
        with patch.object(
            fetcher, "get_price", wraps=fetcher.get_price
        ) as spy_get_price:
            df = fetcher.fetch_stock_daily(SYMBOL, "2024-01-02", "2024-01-05")

        spy_get_price.assert_called_once()
        kwargs = spy_get_price.call_args.kwargs
        assert kwargs.get("start_date") == "2024-01-02"
        assert kwargs.get("end_date") == "2024-01-05"
        assert len(df) == 4

    # ⑫ 裸代码解析湖后缀: '600519' 命中 '600519.SH' 而非滑进本地兜底
    def test_bare_symbol_resolves_lake_suffix(self, tmp_path):
        raw = _lake_frame(symbol="600519.SH")
        fetcher = _make_fetcher(tmp_path, raw, symbol="600519.SH")

        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = pd.DataFrame(
                columns=GET_PRICE_LAKE_COLUMNS
            )
            result = fetcher.get_price("600519")

        assert not result.empty
        assert len(result) == len(raw)
        assert result["code"].iloc[0] == "600519.SH"
        local_cls.return_value.fetch_daily.assert_not_called()

    # ⑬ fetch_for_brain 走湖原始价 (adjust="")
    def test_fetch_for_brain_reads_lake_raw(self, tmp_path):
        raw = _lake_frame()
        fetcher = _make_fetcher(tmp_path, raw)

        payload = fetcher.fetch_for_brain(SYMBOL)

        assert payload["symbol"] == SYMBOL
        assert not payload["stock"].empty
        assert "adj_factor" not in payload["stock"].columns
        assert payload["stock"]["close"].tolist() == raw["close"].tolist()
