"""DataCleaner 输入列契约 + 前视/审计红线契约测试 (WS-B, TDD 红绿).

预注册红线覆盖:
  C1 缺 date/close     → ValueError (消息含缺失列名 + "cleaner 输入列契约")
  C2 缺 amount         → ValueError (禁止 close*volume 兜底, 保护 illiq 因子)
  C3 bfill 前视        → 首日 NaN 保持 NaN (只 ffill, 不回填未来)
  C4 OHLC 修复审计     → df.attrs["cleaner_repaired"] 计数, 不加新列
  vol/volume 双 schema → ValueError (仅 vol 无 volume 时提示)
"""
import numpy as np
import pandas as pd
import pytest

from uniquant.data.pipeline.data_cleaner import DataCleaner


def _make_frame(rows: int = 5, *, with_amount: bool = True, volume_key: str = "volume"):
    """构造与湖 schema 对齐的健康日线帧 (date/open/high/low/close/amount/volume/reserved/code)."""
    dates = pd.bdate_range("2024-01-02", periods=rows)
    close = np.linspace(10.0, 14.0, rows)
    data = {
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close - 0.2,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        volume_key: np.full(rows, 1_000_000.0),
        "reserved": [0] * rows,
        "code": ["600519.SH"] * rows,
    }
    if with_amount:
        data["amount"] = close * 1_000_000.0
    return pd.DataFrame(data)


@pytest.fixture
def cleaner() -> DataCleaner:
    return DataCleaner()


# ─────────────────────────────────────────────────────────────
# ① 缺 date 列 → ValueError (契约消息, 不再是 KeyError)
# ─────────────────────────────────────────────────────────────
def test_missing_date_raises_contract_error(cleaner):
    df = _make_frame().drop(columns=["date"])
    with pytest.raises(ValueError) as exc_info:
        cleaner.clean(df)
    msg = str(exc_info.value)
    assert "cleaner 输入列契约" in msg, f"消息缺少契约标识: {msg}"
    assert "date" in msg, f"消息缺少缺失列名: {msg}"


# ─────────────────────────────────────────────────────────────
# ①b 缺 close 列 → 同契约 ValueError
# ─────────────────────────────────────────────────────────────
def test_missing_close_raises_contract_error(cleaner):
    df = _make_frame().drop(columns=["close"])
    with pytest.raises(ValueError) as exc_info:
        cleaner.clean(df)
    msg = str(exc_info.value)
    assert "cleaner 输入列契约" in msg, f"消息缺少契约标识: {msg}"
    assert "close" in msg, f"消息缺少缺失列名: {msg}"


# ─────────────────────────────────────────────────────────────
# ② 缺 amount 列 → ValueError, 禁止 close*volume 凭空兜底
# ─────────────────────────────────────────────────────────────
def test_missing_amount_raises_no_silent_fallback(cleaner):
    df = _make_frame(with_amount=False)
    with pytest.raises(ValueError) as exc_info:
        cleaner.clean(df)
    msg = str(exc_info.value)
    assert "amount 缺失禁止 close*volume 兜底，污染 illiq 因子" in msg, (
        f"消息缺少红线关键词: {msg}"
    )
    # 输入帧不被原地污染 (cleaner 不得给调用方补列)
    assert "amount" not in df.columns


# ─────────────────────────────────────────────────────────────
# ②b amount 存在但含 NaN → 保留 NaN (不 fill), 计数 warning
# ─────────────────────────────────────────────────────────────
def test_amount_nan_preserved_not_filled(cleaner):
    df = _make_frame()
    df.loc[2, "amount"] = np.nan
    result = cleaner.clean(df)
    assert len(result) == 5, "amount NaN 行不得被删除"
    assert result["amount"].isna().sum() == 1, "amount NaN 必须原样保留 (禁止 fill 兜底)"
    assert pd.notna(result.loc[0, "amount"]) and pd.notna(result.loc[4, "amount"])


# ─────────────────────────────────────────────────────────────
# ③ 首日 open NaN → 保持 NaN (bfill 前视回归红线)
# ─────────────────────────────────────────────────────────────
def test_first_row_open_nan_stays_nan_no_bfill(cleaner):
    df = _make_frame()
    df.loc[0, "open"] = np.nan  # 首日缺开盘价: 若被回填则必来自未来 → 前视
    result = cleaner.clean(df)
    assert len(result) == 5, "首日 close 有效, 行不得被删"
    assert pd.isna(result.loc[0, "open"]), (
        "首日 open 必须保持 NaN — 用未来值回填构成前视偏差 (bfill 已移除)"
    )


# ─────────────────────────────────────────────────────────────
# ④ 中段 NaN → ffill 保留 (因果方向填充不受影响)
# ─────────────────────────────────────────────────────────────
def test_mid_sequence_open_nan_ffilled_from_history(cleaner):
    df = _make_frame()
    df.loc[2, "open"] = np.nan
    result = cleaner.clean(df)
    assert len(result) == 5
    assert pd.notna(result.loc[2, "open"]), "中段 open 应由历史值 ffill"
    assert result.loc[2, "open"] == pytest.approx(result.loc[1, "open"]), (
        "中段 ffill 必须取前值 (历史), 而非后值 (未来)"
    )


# ─────────────────────────────────────────────────────────────
# ⑤ OHLC 修复 → df.attrs["cleaner_repaired"] 计数, 不加新列
# ─────────────────────────────────────────────────────────────
def test_ohlc_repair_counted_in_attrs_no_new_column(cleaner):
    df = _make_frame()
    df.loc[2, "high"] = 5.0   # high < low 异常注入
    df.loc[2, "low"] = 15.0
    cols_before = set(df.columns)
    result = cleaner.clean(df)

    repaired = result.attrs.get("cleaner_repaired")
    assert repaired is not None, "缺少 df.attrs['cleaner_repaired'] 审计标记"
    assert repaired["high"] >= 1, f"high 修复数应 >=1, got {repaired}"
    assert repaired["low"] >= 1, f"low 修复数应 >=1, got {repaired}"
    assert set(result.columns) == cols_before, "修复计数禁止落成新列"
    assert (result["high"] >= result["low"]).all()


# ─────────────────────────────────────────────────────────────
# ⑤b 健康帧 → 零修复, 审计计数全 0
# ─────────────────────────────────────────────────────────────
def test_clean_frame_reports_zero_repairs(cleaner):
    result = cleaner.clean(_make_frame())
    repaired = result.attrs.get("cleaner_repaired")
    assert repaired is not None, "健康帧也必须带审计标记 (可审计性)"
    assert repaired["high"] == 0 and repaired["low"] == 0, (
        f"健康帧不应有修复计数: {repaired}"
    )


# ─────────────────────────────────────────────────────────────
# ⑥ 仅 vol 列 (无 volume) → ValueError 提示双 schema
# ─────────────────────────────────────────────────────────────
def test_vol_only_schema_raises(cleaner):
    df = _make_frame(volume_key="vol")
    with pytest.raises(ValueError) as exc_info:
        cleaner.clean(df)
    msg = str(exc_info.value)
    assert "vol" in msg and "volume" in msg, f"消息未提示 vol/volume 双 schema: {msg}"


# ─────────────────────────────────────────────────────────────
# ⑦ 正常 9 列 → 行数/数值逐位不变 (仅类型归一)
# ─────────────────────────────────────────────────────────────
def test_normal_9col_frame_values_unchanged(cleaner):
    df = _make_frame(rows=6)
    assert len(df.columns) == 9, "前提: 湖 schema 9 列"
    result = cleaner.clean(df)

    assert len(result) == len(df), "健康帧行数不变"
    assert set(result.columns) == set(df.columns), "健康帧列集合不变"
    for col in ["open", "high", "low", "close", "amount", "volume", "reserved"]:
        assert np.array_equal(
            result[col].to_numpy(dtype="float64"), df[col].to_numpy(dtype="float64")
        ), f"{col} 数值被改写"
    assert (result["date"].to_numpy() == pd.to_datetime(df["date"]).to_numpy()).all(), (
        "date 归一为 datetime 后不应改变取值"
    )
    assert (result["code"] == df["code"]).all()
