"""WS-C Step 2c: 旧轨 DataAdjuster 薄壳委托新轨 CorporateActionAdjuster 契约测试。

覆盖任务要求的 5 类用例:
① 薄壳 qfq 与直调新轨结果逐位相等
② volume 不变
③ 输出含 adj_factor 列
④ 签名兼容 (旧 import 方调用形式)
⑤ 缺 gbbq 抛硬失败 (路径 + "gbbq 基线缺失，禁止静默单位矩阵" + resync 指引)

gbbq 基线全部在 tmp_path 内合成，不读写 data/ 下任何文件。
"""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from uniquant.data.corporate_action import CorporateActionAdjuster
from uniquant.data.lake.storage_manager import StorageManager
from uniquant.data.pipeline import DataAdjuster as DataAdjusterFromPackage
from uniquant.data.pipeline.data_adjuster import DataAdjuster


# ---------------------------------------------------------------------------
# Fixtures / helpers (合成数据, 只写 tmp)
# ---------------------------------------------------------------------------

def _make_daily(rows: int = 20, start: str = "2024-01-02", code: str = "600000") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=rows)
    rng = np.random.default_rng(7)
    close = 10.0 + np.cumsum(rng.normal(0.0, 0.2, rows))
    close = np.maximum(close, 1.0)
    volume = rng.integers(1_000_000, 5_000_000, rows).astype(float)
    return pd.DataFrame({
        "date": dates,
        "code": code,
        "open": close + 0.05,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": volume,
        "amount": close * volume,
    })


def _write_gbbq(tmp_path: Path, df_daily: pd.DataFrame, code: str = "600000") -> Path:
    """合成 gbbq 基线: 日线中位日一笔现金分红 (原始口径 2.0 → 清洗后 /10 = 0.2 元)。"""
    fq = tmp_path / "fq"
    fq.mkdir(parents=True, exist_ok=True)
    event_date = pd.Timestamp(df_daily["date"].iloc[len(df_daily) // 2])
    path = fq / "gbbq.parquet"
    pd.DataFrame({
        "code": [code],
        "date": [event_date],
        "cash": [2.0],
        "split": [0.0],
        "rights": [0.0],
        "r_price": [0.0],
    }).to_parquet(path)
    return path


def _make_storage(tmp_path: Path) -> MagicMock:
    storage = MagicMock(spec=StorageManager)
    storage.data_dir = tmp_path
    return storage


def _make_shell(tmp_path: Path, gbbq_path: Path | None = None) -> DataAdjuster:
    return DataAdjuster(storage_manager=_make_storage(tmp_path), gbbq_path=gbbq_path)


def _direct_adjust(tmp_path: Path, df: pd.DataFrame, symbol: str, adjust_type: str) -> pd.DataFrame:
    adjuster = CorporateActionAdjuster(gbbq_path=tmp_path / "fq" / "gbbq.parquet")
    adjuster.load_events()
    return adjuster.adjust(df, symbol, adjust_type=adjust_type)


# ---------------------------------------------------------------------------
# ① 薄壳 == 直调新轨 (逐位)
# ---------------------------------------------------------------------------

def test_thin_shell_qfq_bitwise_equals_direct_new_track(tmp_path):
    df_raw = _make_daily()
    _write_gbbq(tmp_path, df_raw)

    result = _make_shell(tmp_path).apply_adjustment("600000.SH", df_raw, method="qfq")

    prepared = df_raw.copy()
    prepared["date"] = pd.to_datetime(prepared["date"])
    prepared = prepared.sort_values("date").reset_index(drop=True)
    expected = _direct_adjust(tmp_path, prepared, "600000.SH", "qfq")

    pd.testing.assert_frame_equal(result, expected, check_exact=True)
    # 防退化: 合成 gbbq 中位日有分红事件 → 早期 qfq 比例必须 < 1 (非恒等直通)
    assert result["adj_factor"].iloc[0] < 1.0
    assert result["close"].iloc[0] < df_raw["close"].iloc[0]


def test_thin_shell_hfq_bitwise_equals_direct_new_track(tmp_path):
    df_raw = _make_daily()
    _write_gbbq(tmp_path, df_raw)

    result = _make_shell(tmp_path).apply_adjustment("600000.SH", df_raw, method="hfq")

    prepared = df_raw.copy()
    prepared["date"] = pd.to_datetime(prepared["date"])
    prepared = prepared.sort_values("date").reset_index(drop=True)
    expected = _direct_adjust(tmp_path, prepared, "600000.SH", "hfq")

    pd.testing.assert_frame_equal(result, expected, check_exact=True)
    assert result["adj_factor"].iloc[-1] > 1.0  # 分红后累积因子 > 1


# ---------------------------------------------------------------------------
# ② volume 不变
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["qfq", "hfq"])
def test_thin_shell_volume_unchanged(tmp_path, method):
    df_raw = _make_daily()
    _write_gbbq(tmp_path, df_raw)

    result = _make_shell(tmp_path).apply_adjustment("600000.SH", df_raw, method=method)

    assert len(result) == len(df_raw)
    assert (result["volume"].to_numpy() == df_raw["volume"].to_numpy()).all(), (
        f"{method} 复权不得调整 volume"
    )
    # 价格确实被调整 (否则下面的 volume 断言可能是假阳性直通)
    assert not np.allclose(result["close"].to_numpy(), df_raw["close"].to_numpy())


# ---------------------------------------------------------------------------
# ③ 输出含 adj_factor 列
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["qfq", "hfq"])
def test_thin_shell_output_has_adj_factor(tmp_path, method):
    df_raw = _make_daily()
    _write_gbbq(tmp_path, df_raw)

    result = _make_shell(tmp_path).apply_adjustment("600000.SH", df_raw, method=method)

    assert "adj_factor" in result.columns
    assert result["adj_factor"].notna().all()
    assert (result["adj_factor"] > 0).all()
    # 原始列全保留
    assert set(df_raw.columns).issubset(set(result.columns))


# ---------------------------------------------------------------------------
# ④ 签名兼容 (旧 import 方调用形式)
# ---------------------------------------------------------------------------

def test_legacy_call_signatures_still_work(tmp_path):
    df_raw = _make_daily(30)
    _write_gbbq(tmp_path, df_raw)
    storage = _make_storage(tmp_path)

    # 旧 import 面: package 导入与模块导入同一对象
    assert DataAdjusterFromPackage is DataAdjuster

    # 位置参数形式 (data_pipeline_service.process)
    adjuster = DataAdjuster(storage)
    r1 = adjuster.apply_adjustment("600000.SH", df_raw, "qfq")
    assert "adj_factor" in r1.columns

    # 关键字 + cutoff_date (data_fetcher / get_adjusted_data)
    r2 = DataAdjuster(storage_manager=storage).apply_adjustment(
        symbol="600000.SH", df_raw=df_raw, method="hfq", cutoff_date="2024-01-15"
    )
    assert len(r2) > 0
    assert (r2["date"] <= pd.Timestamp("2024-01-15")).all()
    assert "adj_factor" in r2.columns

    # get_adjusted_data (storage 直读 + 复权)
    storage.read_local_raw.return_value = df_raw
    r3 = adjuster.get_adjusted_data("600000.SH", "2024-01-02", "2024-01-31", adjust="qfq")
    assert not r3.empty
    assert "adj_factor" in r3.columns
    # adjust 非 qfq/hfq → 原样返回 (不加载 gbbq)
    r4 = adjuster.get_adjusted_data("600000.SH", "2024-01-02", "2024-01-31", adjust="")
    assert "adj_factor" not in r4.columns

    # update_factors 已 deprecated 直通, 不再读写 data/factors/
    assert adjuster.update_factors("600000.SH") is True
    assert adjuster.factor_manager is None

    # is_valid_stock_code 保留
    assert adjuster.is_valid_stock_code("600000", "SH") is True
    assert adjuster.is_valid_stock_code("60000", "SH") is False


# ---------------------------------------------------------------------------
# ⑤ 缺 gbbq 硬失败 (D2 裁决: 禁止静默单位矩阵)
# ---------------------------------------------------------------------------

def test_missing_gbbq_raises_hard_failure(tmp_path):
    df_raw = _make_daily(5)
    missing = tmp_path / "not_here.parquet"
    adjuster = _make_shell(tmp_path, gbbq_path=missing)

    with pytest.raises(FileNotFoundError) as exc_info:
        adjuster.apply_adjustment("600000.SH", df_raw, method="qfq")

    msg = str(exc_info.value)
    assert str(missing) in msg, "异常消息必须含缺失路径"
    assert "gbbq 基线缺失，禁止静默单位矩阵" in msg
    assert "sync_local_tdx_day.py" in msg, "异常消息必须含 resync 指引"


def test_missing_gbbq_under_storage_data_dir_raises(tmp_path):
    """storage.data_dir 下无 fq/gbbq.parquet → 同样硬失败 (不做静默回退)。"""
    df_raw = _make_daily(5)
    assert not (tmp_path / "fq" / "gbbq.parquet").exists()
    adjuster = _make_shell(tmp_path)

    with pytest.raises(FileNotFoundError) as exc_info:
        adjuster.apply_adjustment("600000.SH", df_raw, method="hfq")

    msg = str(exc_info.value)
    assert str(tmp_path / "fq" / "gbbq.parquet") in msg
    assert "gbbq 基线缺失，禁止静默单位矩阵" in msg
