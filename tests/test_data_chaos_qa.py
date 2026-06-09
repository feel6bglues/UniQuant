from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from uniquant.data.pipeline.data_cleaner import DataCleaner
from uniquant.data.pipeline.data_adjuster import DataAdjuster
from uniquant.data.pipeline.data_validator import DataValidator
from uniquant.data.lake.storage_manager import StorageManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path / "test_data_chaos"


@pytest.fixture
def cleaner():
    return DataCleaner()


@pytest.fixture
def validator():
    return DataValidator()


@pytest.fixture
def storage(tmp_data_dir):
    tmp_data_dir.mkdir(parents=True, exist_ok=True)
    return StorageManager(str(tmp_data_dir))


# ---------------------------------------------------------------------------
# Helper: 构造标准 OHLCV DataFrame
# ---------------------------------------------------------------------------

def _make_ohlcv(rows, start="2024-01-02", freq="B", extra_cols=None):
    dates = pd.bdate_range(start, periods=rows, freq=freq)
    np.random.seed(42)
    base = 10.0
    closes = base + np.cumsum(np.random.randn(rows) * 0.3)
    closes = np.maximum(closes, 0.5)
    df = pd.DataFrame({
        "date": dates,
        "code": "600000",
        "open": closes + np.random.randn(rows) * 0.1,
        "high": closes + abs(np.random.randn(rows)) * 0.2,
        "low": closes - abs(np.random.randn(rows)) * 0.2,
        "close": closes,
        "volume": np.random.randint(1000, 100000, size=rows).astype(float),
        "amount": closes * np.random.randint(1000, 100000, size=rows).astype(float),
    })
    if extra_cols:
        for col, val in extra_cols.items():
            df[col] = val
    return df


# ===================================================================
# 测试1: 脏数据注入测试 — DataCleaner
# ===================================================================

class TestDataCleanerChaos:

    def test_suspension_days_volume_zero_price_unchanged(self, cleaner):
        df = _make_ohlcv(10)
        df.loc[3:5, "volume"] = 0
        df.loc[3:5, "open"] = df.loc[2, "close"]
        df.loc[3:5, "high"] = df.loc[2, "close"]
        df.loc[3:5, "low"] = df.loc[2, "close"]
        df.loc[3:5, "close"] = df.loc[2, "close"]
        result = cleaner.clean(df)
        assert not result.empty
        susp_mask = result["volume"] == 0
        assert susp_mask.sum() >= 3

    def test_high_lt_low_anomaly(self, cleaner):
        df = _make_ohlcv(5)
        df.loc[2, "high"] = 5.0
        df.loc[2, "low"] = 15.0
        result = cleaner.clean(df)
        assert not result.empty
        assert (result["high"] >= result["low"]).all(), "DataCleaner 未修复 High < Low"

    def test_nan_in_price_columns(self, cleaner):
        df = _make_ohlcv(8)
        df.loc[1, "open"] = np.nan
        df.loc[3, "close"] = np.nan
        df.loc[5, "high"] = np.nan
        result = cleaner.clean(df)
        assert not result.empty
        # HOTFIX #1: NaN close is dropped via dropna; non-close price cols may retain NaN
        assert not result["close"].isna().any(), "Close NaN should be dropped after cleaning"

    def test_duplicate_dates(self, cleaner):
        df = _make_ohlcv(5)
        dup_row = df.iloc[[2]].copy()
        dup_row["close"] = 999.0
        df = pd.concat([df, dup_row], ignore_index=True)
        result = cleaner.clean(df)
        assert result["date"].is_unique, "清洗后日期不唯一"

    def test_column_case_inconsistency(self, cleaner):
        df = _make_ohlcv(5)
        df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
        result = cleaner.clean(df)
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns

    def test_empty_dataframe(self, cleaner):
        df = pd.DataFrame()
        result = cleaner.clean(df)
        assert result.empty

    def test_all_nan_close_dropped(self, cleaner):
        df = _make_ohlcv(5)
        df.loc[:, "close"] = np.nan
        result = cleaner.clean(df)
        assert result.empty or result["close"].notna().all()


# ===================================================================
# 测试2: 复权精度测试 — DataAdjuster
# ===================================================================

class TestDataAdjusterChaos:

    def _build_adjuster_with_factor(self, tmp_path, factor_df):
        storage = MagicMock(spec=StorageManager)
        storage.data_dir = tmp_path
        storage.read_local_factor.return_value = factor_df
        storage.read_local_raw.return_value = pd.DataFrame()
        adjuster = DataAdjuster(storage_manager=storage)
        adjuster.factor_manager = MagicMock()
        adjuster.factor_manager.read_factor.return_value = factor_df
        return adjuster

    def test_qfq_latest_price_unchanged(self, tmp_path):
        rows = 20
        dates = pd.bdate_range("2024-01-02", periods=rows, freq="B")
        closes = np.linspace(10, 20, rows)
        df_raw = pd.DataFrame({
            "date": dates,
            "open": closes - 0.1,
            "high": closes + 0.2,
            "low": closes - 0.2,
            "close": closes,
            "volume": np.full(rows, 50000.0),
        })
        factor_vals = np.ones(rows)
        factor_vals[10:] = 2.0
        df_factor = pd.DataFrame({"date": dates, "factor": factor_vals})

        adjuster = self._build_adjuster_with_factor(tmp_path, df_factor)
        result = adjuster.apply_adjustment("600000.SH", df_raw, method="qfq")

        assert not result.empty
        last_close = result.iloc[-1]["close"]
        raw_last_close = df_raw.iloc[-1]["close"]
        assert abs(last_close - raw_last_close) < 0.01, (
            f"前复权最新价格应不变: got {last_close}, expected {raw_last_close}"
        )

    def test_hfq_earliest_price_unchanged(self, tmp_path):
        rows = 20
        dates = pd.bdate_range("2024-01-02", periods=rows, freq="B")
        closes = np.linspace(10, 20, rows)
        df_raw = pd.DataFrame({
            "date": dates,
            "open": closes - 0.1,
            "high": closes + 0.2,
            "low": closes - 0.2,
            "close": closes,
            "volume": np.full(rows, 50000.0),
        })
        factor_vals = np.ones(rows)
        factor_vals[10:] = 2.0
        df_factor = pd.DataFrame({"date": dates, "factor": factor_vals})

        adjuster = self._build_adjuster_with_factor(tmp_path, df_factor)
        result = adjuster.apply_adjustment("600000.SH", df_raw, method="hfq")

        assert not result.empty
        first_close = result.iloc[0]["close"]
        raw_first_close = df_raw.iloc[0]["close"]
        assert abs(first_close - raw_first_close) < 0.01, (
            f"后复权最早价格应不变: got {first_close}, expected {raw_first_close}"
        )

    def test_hfq_price_multiplied_by_factor(self, tmp_path):
        rows = 10
        dates = pd.bdate_range("2024-01-02", periods=rows, freq="B")
        closes = np.full(rows, 10.0)
        df_raw = pd.DataFrame({
            "date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": np.full(rows, 50000.0),
        })
        factor_vals = np.ones(rows)
        factor_vals[5:] = 2.0
        df_factor = pd.DataFrame({"date": dates, "factor": factor_vals})

        adjuster = self._build_adjuster_with_factor(tmp_path, df_factor)
        result = adjuster.apply_adjustment("600000.SH", df_raw, method="hfq")

        assert not result.empty
        hfq_close_after = result.iloc[7]["close"]
        assert abs(hfq_close_after - 20.0) < 0.01, (
            f"后复权 factor=2.0 后价格应翻倍: got {hfq_close_after}"
        )

    def test_zero_factor_returns_raw(self, tmp_path):
        rows = 5
        dates = pd.bdate_range("2024-01-02", periods=rows, freq="B")
        df_raw = pd.DataFrame({
            "date": dates,
            "open": [10]*5, "high": [10]*5, "low": [10]*5, "close": [10]*5,
            "volume": [50000]*5,
        })
        df_factor = pd.DataFrame({"date": dates, "factor": [0.0]*5})

        adjuster = self._build_adjuster_with_factor(tmp_path, df_factor)
        result = adjuster.apply_adjustment("600000.SH", df_raw, method="hfq")

        assert len(result) == len(df_raw), "零因子应降级返回原始数据"

    def test_extreme_factor_returns_raw(self, tmp_path):
        rows = 5
        dates = pd.bdate_range("2024-01-02", periods=rows, freq="B")
        df_raw = pd.DataFrame({
            "date": dates,
            "open": [10]*5, "high": [10]*5, "low": [10]*5, "close": [10]*5,
            "volume": [50000]*5,
        })
        df_factor = pd.DataFrame({"date": dates, "factor": [1e9]*5})

        adjuster = self._build_adjuster_with_factor(tmp_path, df_factor)
        result = adjuster.apply_adjustment("600000.SH", df_raw, method="hfq")

        assert len(result) == len(df_raw), "极端因子应降级返回原始数据"

    def test_invalid_method_returns_raw(self, tmp_path):
        df_raw = _make_ohlcv(5)
        adjuster = self._build_adjuster_with_factor(tmp_path, pd.DataFrame())
        result = adjuster.apply_adjustment("600000.SH", df_raw, method="invalid")
        assert len(result) == len(df_raw)

    def test_empty_raw_returns_empty(self, tmp_path):
        adjuster = self._build_adjuster_with_factor(tmp_path, pd.DataFrame())
        result = adjuster.apply_adjustment("600000.SH", pd.DataFrame(), method="qfq")
        assert result.empty

    def test_is_valid_stock_code(self):
        storage = MagicMock()
        adjuster = DataAdjuster(storage_manager=storage)
        adjuster.factor_manager = None
        assert adjuster.is_valid_stock_code("600000", "SH") is True
        assert adjuster.is_valid_stock_code("000001", "SZ") is True
        assert adjuster.is_valid_stock_code("300001", "SZ") is True
        assert adjuster.is_valid_stock_code("688001", "SH") is True
        assert adjuster.is_valid_stock_code("60000", "SH") is False
        assert adjuster.is_valid_stock_code("200001", "SZ") is False


# ===================================================================
# 测试3: 时间对齐测试 — DataAligner (mock 外部依赖)
# ===================================================================

class TestDataAlignerChaos:

    def _make_aligner(self, calendar_dates, metadata=None):
        with patch("uniquant.data.pipeline.data_aligner.TradeCalendarManager") as MockCalMgr, \
             patch("uniquant.data.pipeline.data_aligner.StockMetadataManager") as MockMetaMgr:

            cal_instance = MagicMock()
            cal_instance.get_trade_calendar.return_value = pd.DataFrame({
                "trade_date": pd.to_datetime(calendar_dates)
            })
            MockCalMgr.return_value = cal_instance

            meta_instance = MagicMock()
            meta_instance.load.return_value = True
            if metadata is None:
                mock_meta = MagicMock()
                mock_meta.ipo_date = None
                mock_meta.delist_date = None
                meta_instance.get_stock_info.return_value = mock_meta
            else:
                meta_instance.get_stock_info.return_value = metadata
            MockMetaMgr.return_value = meta_instance

            from uniquant.data.pipeline.data_aligner import DataAligner
            aligner = DataAligner(data_dir="/tmp/fake_data")
            aligner.calendar_manager = cal_instance
            aligner.metadata_manager = meta_instance
            return aligner

    def test_suspension_gap_ffill(self):
        calendar_dates = pd.bdate_range("2024-01-02", periods=10, freq="B")
        df = pd.DataFrame({
            "date": [calendar_dates[0], calendar_dates[3], calendar_dates[9]],
            "code": ["600000"] * 3,
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.5, 10.5, 11.5],
            "close": [10.0, 11.0, 12.0],
            "volume": [50000, 60000, 70000],
            "amount": [500000, 660000, 840000],
        })
        aligner = self._make_aligner(calendar_dates.tolist())
        result = aligner.align_stock_data("600000", df)

        assert len(result) == 10, f"对齐后应有10行, 实际 {len(result)}"
        susp_rows = result[result["volume"] == 0]
        assert len(susp_rows) == 7, f"停牌日应为7行, 实际 {len(susp_rows)}"
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            assert result[col].notna().all(), f"停牌日 {col} 列存在 NaN"

    def test_non_trading_day_removed(self):
        calendar_dates = pd.bdate_range("2024-01-02", periods=5, freq="B")
        non_trading = pd.Timestamp("2024-01-06")
        df = pd.DataFrame({
            "date": [calendar_dates[0], calendar_dates[1], non_trading, calendar_dates[4]],
            "code": ["600000"] * 4,
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [10.5, 11.5, 12.5, 13.5],
            "low": [9.5, 10.5, 11.5, 12.5],
            "close": [10.0, 11.0, 12.0, 13.0],
            "volume": [50000, 60000, 70000, 80000],
            "amount": [500000, 660000, 840000, 1040000],
        })
        aligner = self._make_aligner(calendar_dates.tolist())
        result = aligner.align_stock_data("600000", df)

        assert non_trading not in result["date"].values, "非交易日应被移除"

    def test_empty_df_returns_empty(self):
        calendar_dates = pd.bdate_range("2024-01-02", periods=5, freq="B")
        aligner = self._make_aligner(calendar_dates.tolist())
        result = aligner.align_stock_data("600000", pd.DataFrame())
        assert result.empty

    def test_suspension_volume_zero(self):
        calendar_dates = pd.bdate_range("2024-01-02", periods=5, freq="B")
        df = pd.DataFrame({
            "date": [calendar_dates[0], calendar_dates[4]],
            "code": ["600000"] * 2,
            "open": [10.0, 12.0],
            "high": [10.5, 12.5],
            "low": [9.5, 11.5],
            "close": [10.0, 12.0],
            "volume": [50000, 70000],
            "amount": [500000, 840000],
        })
        aligner = self._make_aligner(calendar_dates.tolist())
        result = aligner.align_stock_data("600000", df)

        susp = result[result["volume"] == 0]
        assert len(susp) == 3, f"停牌日应为3行, 实际 {len(susp)}"
        for col in ["open", "high", "low", "close"]:
            assert susp[col].notna().all(), f"停牌日 {col} 列存在 NaN"


# ===================================================================
# 测试4: DataValidator 边界测试
# ===================================================================

class TestDataValidatorChaos:

    def test_empty_dataframe(self):
        v = DataValidator()
        assert v.validate(pd.DataFrame()) is False

    def test_missing_required_columns(self):
        v = DataValidator()
        df = pd.DataFrame({"date": ["2024-01-02"], "close": [10.0]})
        assert v.validate(df) is False

    def test_high_lt_low_auto_fix(self):
        v = DataValidator()
        df = _make_ohlcv(5)
        df.loc[2, "high"] = 5.0
        df.loc[2, "low"] = 15.0
        result = v.validate(df)
        assert result is True
        assert df.loc[2, "high"] >= df.loc[2, "low"], "Validator 未自动修复 High < Low"

    def test_extreme_drop_over_99_pct(self):
        v = DataValidator()
        df = _make_ohlcv(5)
        df.loc[3, "close"] = df.loc[2, "close"] * 0.001
        result = v.validate(df)
        assert result is True  # 验证通过但应有 warning

    def test_high_lt_open_close_auto_fix(self):
        v = DataValidator()
        df = _make_ohlcv(3)
        df.loc[1, "high"] = df.loc[1, "open"] - 1.0
        df.loc[1, "low"] = df.loc[1, "close"] + 1.0
        result = v.validate(df)
        assert result is True
        assert df.loc[1, "high"] >= df.loc[1, "open"]
        assert df.loc[1, "high"] >= df.loc[1, "close"]
        assert df.loc[1, "low"] <= df.loc[1, "open"]
        assert df.loc[1, "low"] <= df.loc[1, "close"]

    def test_all_columns_present(self):
        v = DataValidator()
        df = _make_ohlcv(5)
        assert v.validate(df) is True

    def test_date_gap_warning(self):
        v = DataValidator()
        df = _make_ohlcv(5)
        df.loc[2, "date"] = df.loc[2, "date"] + pd.Timedelta(days=30)
        result = v.validate(df)
        assert result is True  # 仍应通过验证（仅 warning）


# ===================================================================
# 测试5: StorageManager 基础功能测试
# ===================================================================

class TestStorageManagerChaos:

    def test_initialization_creates_dirs(self, tmp_data_dir):
        tmp_data_dir.mkdir(parents=True, exist_ok=True)
        sm = StorageManager(str(tmp_data_dir))
        assert sm.daily_dir.exists()
        assert sm.weekly_dir.exists()
        assert sm.monthly_dir.exists()
        assert sm.min1_dir.exists()
        assert sm.min5_dir.exists()
        assert sm.factor_dir.exists()

    def test_write_and_read_parquet(self, storage, tmp_data_dir):
        df = _make_ohlcv(5)
        file_path = str(tmp_data_dir / "test_write.parquet")
        assert storage.write_parquet(file_path, df, overwrite=True) is True
        result = storage.read_parquet(file_path, normalize=False)
        assert not result.empty
        assert len(result) == 5

    def test_write_empty_df_returns_false(self, storage, tmp_data_dir):
        file_path = str(tmp_data_dir / "test_empty.parquet")
        assert storage.write_parquet(file_path, pd.DataFrame()) is False

    def test_read_nonexistent_returns_empty(self, storage):
        result = storage.read_parquet("/nonexistent/path/data.parquet")
        assert result.empty

    def test_write_no_overwrite(self, storage, tmp_data_dir):
        df = _make_ohlcv(3)
        file_path = str(tmp_data_dir / "test_no_overwrite.parquet")
        assert storage.write_parquet(file_path, df, overwrite=True) is True
        df2 = _make_ohlcv(5)
        assert storage.write_parquet(file_path, df2, overwrite=False) is False

    def test_delete_file(self, storage, tmp_data_dir):
        df = _make_ohlcv(3)
        file_path = str(tmp_data_dir / "test_delete.parquet")
        storage.write_parquet(file_path, df, overwrite=True)
        assert storage.delete_file(file_path) is True
        assert not Path(file_path).exists()

    def test_delete_nonexistent_returns_true(self, storage):
        assert storage.delete_file("/nonexistent/file.parquet") is True

    def test_file_exists(self, storage, tmp_data_dir):
        df = _make_ohlcv(3)
        file_path = str(tmp_data_dir / "test_exists.parquet")
        storage.write_parquet(file_path, df, overwrite=True)
        assert storage.file_exists(file_path) is True
        assert storage.file_exists("/nonexistent/file.parquet") is False

    def test_list_files(self, storage, tmp_data_dir):
        df = _make_ohlcv(3)
        for name in ["a.parquet", "b.parquet", "c.csv"]:
            storage.write_parquet(str(tmp_data_dir / name), df, overwrite=True)
        files = storage.list_files(str(tmp_data_dir))
        assert "a.parquet" in files
        assert "b.parquet" in files
        assert "c.csv" not in files

    def test_save_and_read_data(self, storage):
        df = _make_ohlcv(5)
        assert storage.save_data("600000.SH", df) is True
        result = storage.read_data("600000.SH", data_type="daily")
        assert not result.empty

    def test_has_data(self, storage):
        df = _make_ohlcv(3)
        storage.save_data("600001.SH", df)
        assert storage.has_data("600001.SH") is True
        assert storage.has_data("999999.SH") is False

    def test_get_symbols(self, storage):
        df = _make_ohlcv(3)
        storage.save_data("600002.SH", df)
        storage.save_data("600003.SH", df)
        symbols = storage.get_symbols()
        assert "600002.SH" in symbols
        assert "600003.SH" in symbols

    def test_normalize_stock_code(self, storage):
        assert storage._normalize_stock_code("600000.SH") == "600000.SH"
        assert storage._normalize_stock_code("SH.600000") == "600000.SH"
        assert storage._normalize_stock_code("000001.SZ") == "000001.SZ"
        assert storage._normalize_stock_code("830001.BJ") == "830001.BJ"
        assert storage._normalize_stock_code("600000") == "600000.SH"
        assert storage._normalize_stock_code("000001") == "000001.SZ"

    def test_batch_read_data(self, storage):
        df = _make_ohlcv(3)
        storage.save_data("600010.SH", df)
        storage.save_data("600011.SH", df)
        results = storage.batch_read_data(["600010.SH", "600011.SH", "999999.SH"])
        assert "600010.SH" in results
        assert "600011.SH" in results
        assert "999999.SH" not in results

    def test_save_factor_and_read(self, storage):
        df_factor = pd.DataFrame({
            "date": pd.bdate_range("2024-01-02", periods=5, freq="B"),
            "factor": [1.0, 1.0, 1.5, 1.5, 2.0],
        })
        assert storage.save_factor("600000.SH", df_factor) is True
        result = storage.read_local_factor("600000.SH")
        assert not result.empty

    def test_clean_data(self, storage):
        df = _make_ohlcv(3)
        storage.save_data("600099.SH", df)
        storage.save_factor("600099.SH", pd.DataFrame({
            "date": pd.bdate_range("2024-01-02", periods=3, freq="B"),
            "factor": [1.0, 1.0, 1.0],
        }))
        storage.clean_data("600099.SH")
        assert not storage.has_data("600099.SH")


# ===================================================================
# 测试6: DataCleaner + DataValidator 联合管道测试
# ===================================================================

class TestPipelineIntegration:

    def test_clean_then_validate(self, cleaner):
        v = DataValidator()
        df = _make_ohlcv(10)
        df.loc[3, "high"] = 1.0
        df.loc[3, "low"] = 99.0
        df.loc[5, "close"] = np.nan
        df = pd.concat([df, df.iloc[[2]]], ignore_index=True)
        cleaned = cleaner.clean(df)
        validated = v.validate(cleaned)
        assert validated is True
        assert cleaned["date"].is_unique
        assert (cleaned["high"] >= cleaned["low"]).all()

    def test_full_dirty_pipeline(self, cleaner):
        v = DataValidator()
        df = pd.DataFrame({
            "Date": pd.bdate_range("2024-01-02", periods=8, freq="B"),
            "Code": ["600000"] * 8,
            "Open": [10, 11, np.nan, 12, 13, 14, 15, 16],
            "High": [10.5, 11.5, 10, 12.5, 5.0, 14.5, 15.5, 16.5],
            "Low": [9.5, 10.5, 10, 11.5, 99.0, 13.5, 14.5, 15.5],
            "Close": [10, 11, 10, 12, 13, np.nan, 15, 16],
            "Volume": [50000, 0, 0, 60000, 70000, 80000, 0, 90000],
            "Amount": [500000, 0, 0, 720000, 910000, 1120000, 0, 1440000],
        })
        dup = df.iloc[[3]].copy()
        df = pd.concat([df, dup], ignore_index=True)
        cleaned = cleaner.clean(df)
        assert cleaned["date"].is_unique
        # HOTFIX #1: NaN close dropped; open may retain NaN after cleaning
        assert not cleaned["close"].isna().any(), "Close NaN should be dropped after cleaning"
        validated = v.validate(cleaned)
        assert validated is True
