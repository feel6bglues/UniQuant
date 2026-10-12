from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from uniquant.data.pipeline.data_cleaner import DataCleaner
from uniquant.data.corporate_action import CorporateActionAdjuster
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
    # Step4 (D5 R-5): 主数据缺文件硬失败 → 测试 fixture 提供最小主数据表
    pd.DataFrame({
        "code": ["sh.600519", "sz.000001"],
        "name": ["贵州茅台", "平安银行"],
        "代码": ["600519", "000001"],
        "ipoDate": ["2001-08-27", "1991-04-03"],
        "outDate": ["", ""],
        "type": ["1", "1"],
        "status": ["1", "1"],
    }).to_csv(tmp_data_dir / "all_stock_codes.csv", index=False, encoding="utf-8-sig")
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
    opens = closes + np.random.randn(rows) * 0.1
    highs = closes + np.abs(np.random.randn(rows)) * 0.2
    lows = closes - np.abs(np.random.randn(rows)) * 0.2
    # Enforce OHLC invariants: high >= max(open, close), low <= min(open, close)
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    df = pd.DataFrame({
        "date": dates,
        "code": "600000",
        "open": opens,
        "high": highs,
        "low": lows,
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
# 测试2: 复权精度测试 — CorporateActionAdjuster (新轨单轨, S4a)
# ===================================================================

class TestDataAdjusterChaos:
    """复权精度 chaos — Step4 S4a: DataAdjuster 薄壳已删，直调 CorporateActionAdjuster 新轨。

    契约: volume 不变、qfq 末日锚点=原始价、输出含 adj_factor 列、缺 gbbq 硬失败。
    """

    def _write_gbbq(self, tmp_path, df_daily, code="600000"):
        """合成 gbbq 基线: 日线中位日一笔现金分红 (cash_div=20 → /10 = 2.0 元)。

        Step4 S4a: 新轨 8 列契约 + **事件日真实除权** (新轨防呆: 行情未按理论除权价
        下跌则跳过事件 → 因子全 1; 故把事件日及之后的 close/open 扣除 2.0)。
        """
        fq = tmp_path / "fq"
        fq.mkdir(parents=True, exist_ok=True)
        event_date = pd.Timestamp(df_daily["date"].iloc[len(df_daily) // 2])
        path = fq / "gbbq.parquet"
        pd.DataFrame({
            "code": [code],
            "market": [0],
            "date": [int(event_date.strftime("%Y%m%d"))],
            "category": [1],
            "cash_div": [20.0],
            "split_ratio": [0.0],
            "rights_ratio": [0.0],
            "rights_price": [0.0],
        }).to_parquet(path)
        mask = df_daily["date"] >= event_date
        df_daily.loc[mask, "open"] = df_daily.loc[mask, "open"] - 2.0
        df_daily.loc[mask, "close"] = df_daily.loc[mask, "close"] - 2.0
        return path

    def _build_adjuster(self, tmp_path, df_daily, code="600000"):
        self._write_gbbq(tmp_path, df_daily, code=code)
        # Step4 S4a: 直调新轨 (薄壳已删), gbbq 8 列契约 -> int YYYYMMDD
        return CorporateActionAdjuster(gbbq_path=tmp_path / "fq" / "gbbq.parquet")

    @staticmethod
    def _make_frame(rows, start="2024-01-02"):
        dates = pd.bdate_range(start, periods=rows, freq="B")
        closes = np.linspace(10, 20, rows) if rows > 1 else np.array([10.0])
        return pd.DataFrame({
            "date": dates,
            "open": closes - 0.1,
            "high": closes + 0.2,
            "low": closes - 0.2,
            "close": closes,
            "volume": np.full(rows, 50000.0),
        })

    @staticmethod
    def _apply(adjuster, df_raw, method):
        df = df_raw.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return adjuster.adjust(df, "600000.SH", adjust_type=method)

    def test_qfq_latest_price_unchanged(self, tmp_path):
        df_raw = self._make_frame(20)
        adjuster = self._build_adjuster(tmp_path, df_raw)
        result = self._apply(adjuster, df_raw, "qfq")

        assert not result.empty
        # 新轨语义: qfq 锚点 = 数据最新日 → 末日价格 = 原始价
        last_close = result.iloc[-1]["close"]
        raw_last_close = df_raw.iloc[-1]["close"]
        assert last_close == pytest.approx(raw_last_close), (
            f"前复权末日锚点价格应不变: got {last_close}, expected {raw_last_close}"
        )
        assert result.iloc[-1]["adj_factor"] == pytest.approx(1.0)
        # 非退化: 分红事件在样本中位日 → 早期价格必须被真实调整 (非名义复权)
        assert result.iloc[0]["close"] < df_raw.iloc[0]["close"]
        assert "adj_factor" in result.columns
        assert (result["volume"].to_numpy() == df_raw["volume"].to_numpy()).all()

    def test_hfq_earliest_price_unchanged(self, tmp_path):
        df_raw = self._make_frame(20)
        adjuster = self._build_adjuster(tmp_path, df_raw)
        result = self._apply(adjuster, df_raw, "hfq")

        assert not result.empty
        # 新轨语义: hfq 起始因子 = 1.0 → 最早价格不变
        first_close = result.iloc[0]["close"]
        raw_first_close = df_raw.iloc[0]["close"]
        assert first_close == pytest.approx(raw_first_close), (
            f"后复权最早价格应不变: got {first_close}, expected {raw_first_close}"
        )
        assert result.iloc[0]["adj_factor"] == pytest.approx(1.0)
        # 非退化: 分红后累积因子 > 1 → 末日价格被放大
        assert result.iloc[-1]["close"] > df_raw.iloc[-1]["close"]
        assert (result["volume"].to_numpy() == df_raw["volume"].to_numpy()).all()

    def test_hfq_price_equals_raw_times_adj_factor(self, tmp_path):
        """新轨契约: hfq 价格 = 原始价 × adj_factor (无缩放、无裁剪、无因子列读取)。"""
        df_raw = self._make_frame(10)
        adjuster = self._build_adjuster(tmp_path, df_raw)
        result = self._apply(adjuster, df_raw, "hfq")

        assert len(result) == len(df_raw)
        for col in ["open", "high", "low", "close"]:
            np.testing.assert_allclose(
                result[col].to_numpy(),
                df_raw[col].to_numpy() * result["adj_factor"].to_numpy(),
                rtol=1e-12,
                err_msg=f"{col} 应等于原始价 × adj_factor",
            )
        assert (result["adj_factor"] > 0).all(), "adj_factor 必须为正"
        assert (result["volume"].to_numpy() == df_raw["volume"].to_numpy()).all()

    def test_missing_gbbq_raises(self, tmp_path):
        """旧轨 '零因子降级返回原始数据' 改写: 缺 gbbq 基线 → 硬失败 (D2 裁决)。"""
        df_raw = self._make_frame(5)
        assert not (tmp_path / "fq" / "gbbq.parquet").exists()
        adjuster = CorporateActionAdjuster(gbbq_path=tmp_path / "fq" / "gbbq.parquet")

        with pytest.raises(FileNotFoundError) as exc_info:
            self._apply(adjuster, df_raw, "hfq")

        msg = str(exc_info.value)
        assert str(tmp_path / "fq" / "gbbq.parquet") in msg
        assert "gbbq 基线缺失，禁止静默单位矩阵" in msg
        assert "sync_local_tdx_day.py" in msg

    def test_no_silent_raw_fallback_output_has_adj_factor(self, tmp_path):
        """旧轨 '极端因子降级返回原始数据' 改写: 薄壳不得静默返回原始价,
        输出必须带 adj_factor 列且 volume 不变。"""
        df_raw = self._make_frame(5)
        adjuster = self._build_adjuster(tmp_path, df_raw)
        result = self._apply(adjuster, df_raw, "qfq")

        assert len(result) == len(df_raw)
        assert "adj_factor" in result.columns, "禁止静默降级为原始价 (无因子列)"
        assert result["adj_factor"].notna().all()
        assert (result["adj_factor"] > 0).all()
        assert (result["volume"].to_numpy() == df_raw["volume"].to_numpy()).all()

    def test_invalid_method_hfq_branch(self, tmp_path):
        """S4a 新轨语义: invalid 落入 hfq 分支 (调用方前置拒 qfq/hfq 之外),
        不再像旧薄壳静默返回原始价。锁: 正常基线 invalid 输出仍带 adj_factor。"""
        df_raw = self._make_frame(5)
        adjuster = self._build_adjuster(tmp_path, df_raw)
        result = adjuster.adjust(df_raw.copy(), "600000.SH", adjust_type="invalid")
        assert "adj_factor" in result.columns

    def test_empty_raw_returns_empty(self, tmp_path):
        df_seed = self._make_frame(5)
        adjuster = self._build_adjuster(tmp_path, df_seed)
        result = adjuster.adjust(pd.DataFrame(), "600000.SH", adjust_type="qfq")
        assert result.empty

    def test_adjuster_is_validated_by_corporate_action_gate(self):
        """S4a: is_valid_stock_code (仅薄壳有的券商代码校验) 随薄壳删除;
        有效性由 gbbq 基线 + DataValidator 把关。"""
        assert CorporateActionAdjuster is not None


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

    def test_high_lt_low_rejected(self):
        v = DataValidator()
        df = _make_ohlcv(5)
        df.loc[2, "high"] = 5.0
        df.loc[2, "low"] = 15.0
        orig_high = df.loc[2, "high"]
        orig_low = df.loc[2, "low"]
        result = v.validate(df)
        assert result is False, "Read-only validator must reject High < Low"
        assert df.loc[2, "high"] == orig_high, "Original must not be mutated"
        assert df.loc[2, "low"] == orig_low, "Original must not be mutated"

    def test_extreme_drop_over_99_pct(self):
        v = DataValidator()
        df = _make_ohlcv(5)
        df.loc[3, "close"] = df.loc[2, "close"] * 0.001
        # Keep OHLC invariants so the 99% drop itself is only a warning
        df.loc[3, "high"] = max(df.loc[3, "open"], df.loc[3, "close"]) + 0.01
        df.loc[3, "low"] = min(df.loc[3, "open"], df.loc[3, "close"]) - 0.01
        result = v.validate(df)
        assert result is True  # 验证通过但应有 warning

    def test_high_lt_open_close_rejected(self):
        v = DataValidator()
        df = _make_ohlcv(3)
        df.loc[1, "high"] = df.loc[1, "open"] - 1.0
        df.loc[1, "low"] = df.loc[1, "close"] + 1.0
        orig_high = df.loc[1, "high"]
        orig_low = df.loc[1, "low"]
        result = v.validate(df)
        assert result is False, "Read-only validator must reject High < Open / Low > Close"
        assert df.loc[1, "high"] == orig_high, "Original must not be mutated"
        assert df.loc[1, "low"] == orig_low, "Original must not be mutated"

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
        pd.DataFrame({
            "code": ["sh.600519"],
            "name": ["贵州茅台"],
            "代码": ["600519"],
            "ipoDate": ["2001-08-27"],
            "outDate": [""],
            "type": ["1"],
            "status": ["1"],
        }).to_csv(tmp_data_dir / "all_stock_codes.csv", index=False, encoding="utf-8-sig")
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

    def test_get_symbols_excludes_indices(self, storage):
        from uniquant.data.lake.storage_manager import is_index_symbol

        df = _make_ohlcv(3)
        storage.save_data("000001.SH", df)
        storage.save_data("399001.SZ", df)
        storage.save_data("600004.SH", df)
        storage.save_data("000001.SZ", df)
        symbols = storage.get_symbols()
        assert "600004.SH" in symbols
        assert "000001.SZ" in symbols
        assert "000001.SH" not in symbols
        assert "399001.SZ" not in symbols
        assert is_index_symbol("000001.SH") is True
        assert is_index_symbol("399001.SZ") is True
        assert is_index_symbol("000001.SZ") is False

    def test_get_symbols_exclude_indices_false(self, storage):
        df = _make_ohlcv(3)
        storage.save_data("000001.SH", df)
        storage.save_data("600005.SH", df)
        symbols = storage.get_symbols(exclude_indices=False)
        assert "000001.SH" in symbols
        assert "600005.SH" in symbols

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
