#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2b (WS-B): tdx_parser GBBQ 列映射冻结契约测试 — TDD 先红后绿。

背景（2026-10-12 考古结论，勿重复调查）:
    ``tdx_parser.parse_gbbq_file`` 原 ``column_mapping`` 为全中文 key
    （代码/证券代码/日期/除权除息日/分红/派息/送股/送转股/配股/配股价），
    而 pytdx ``GbbqReader.get_df`` 输出恒为 8 拼音列
    ``market, code, datetime, category, hongli_panqianliutong,
      peigujia_qianzongguben, songgu_qianzongguben, peigu_houzongguben``
    → 0/10 命中、rename no-op、``if 'date' in df.columns`` 恒 False 跳过日期转换。

冻结对照组 = ``scripts/maintenance/sync_local_tdx_day.py:106-112``（5/5 命中）。

输出契约（= data/fq/gbbq.parquet 现列）::

    code, market, date, category, cash_div, split_ratio, rights_ratio, rights_price

date 语义 = **int YYYYMMDD**（与 sync 脚本 ``date.astype(int)`` 同口径）。

纪律: 本文件绝不写真实 ``data/fq/gbbq.parquet``（save 测试只写 tmp_path 且校验 mtime）。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

from uniquant.data.parsers import tdx_parser as tdx_parser_mod
from uniquant.data.parsers.tdx_parser import TDXParser, parse_gbbq_native

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GBBQ_REAL_PATH = "/home/james/.local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq"
FQ_GBBQ_PATH = PROJECT_ROOT / "data" / "fq" / "gbbq.parquet"
SYNC_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "maintenance" / "sync_local_tdx_day.py"

# 冻结输出契约（8 列，顺序亦冻结）
TARGET_COLS = [
    "code",
    "market",
    "date",
    "category",
    "cash_div",
    "split_ratio",
    "rights_ratio",
    "rights_price",
]

# 冻结拼音映射（与 sync_local_tdx_day.py:106-112 完全同口径，5/5 命中 pytdx）
PYDX_MAPPING = {
    "datetime": "date",
    "hongli_panqianliutong": "cash_div",
    "peigujia_qianzongguben": "rights_price",
    "songgu_qianzongguben": "split_ratio",
    "peigu_houzongguben": "rights_ratio",
}

# 真实文件首行锚点（000001 / 19900301），与 data/fq/gbbq.parquet 第 0 行一致
ANCHOR_RAW_ROW = {
    "market": 0,
    "code": "000001",
    "datetime": 19900301,
    "category": 1,
    "hongli_panqianliutong": 0.0,
    "peigujia_qianzongguben": 3.56,
    "songgu_qianzongguben": 0.0,
    "peigu_houzongguben": 1.0,
}

requires_real_gbbq = pytest.mark.skipif(
    not os.path.exists(GBBQ_REAL_PATH),
    reason="本机通达信 gbbq 真文件不存在",
)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """取模块级归一化函数（缺失 = Step2b 修复未落地，以断言形式报红而非 import error）。"""
    fn = getattr(tdx_parser_mod, "_normalize_gbbq_frame", None)
    assert callable(fn), "Step2b 缺失: tdx_parser 模块级 _normalize_gbbq_frame()"
    return fn(df)


def _pinyin_frame() -> pd.DataFrame:
    """合成 pytdx GbbqReader 口径的拼音列 DataFrame。"""
    return pd.DataFrame([ANCHOR_RAW_ROW])


@pytest.fixture(scope="module")
def cached_gbbq_reader():
    """
    pytdx GbbqReader.get_df 实测 40s/193,506 行（纯 Python TEA 解密）。
    模块级 memoize: 整个测试文件只解密一次；每次返回副本防止调用方就地改写污染缓存。
    """
    from pytdx.reader import GbbqReader

    original = GbbqReader.get_df
    cache: dict = {}

    def cached(self, path):
        key = str(path)
        if key not in cache:
            cache[key] = original(self, str(path))
        return cache[key].copy()

    GbbqReader.get_df = cached
    yield
    GbbqReader.get_df = original


# ---------------------------------------------------------------------------
# ① 冻结常量本身
# ---------------------------------------------------------------------------


def test_frozen_constants_match_contract():
    assert getattr(tdx_parser_mod, "_GBBQ_TARGET_COLS", None) == TARGET_COLS
    assert getattr(tdx_parser_mod, "_GBBQ_PYDX_COLUMN_MAPPING", None) == PYDX_MAPPING
    mapping = getattr(tdx_parser_mod, "_GBBQ_COLUMN_MAPPING", None)
    assert isinstance(mapping, dict)
    # 拼音表（主）与中文表（兼容别名）合并进同一 dict
    for key, value in PYDX_MAPPING.items():
        assert mapping.get(key) == value
    for key in ("代码", "日期", "分红", "派息", "送股", "送转股", "配股", "配股价", "证券代码", "除权除息日"):
        assert key in mapping, f"中文兼容别名丢失: {key}"


# ---------------------------------------------------------------------------
# ② 合成拼音 DataFrame → rename 精确命中（5 key）
# ---------------------------------------------------------------------------


def test_pinyin_frame_rename_hits_all_five_keys():
    out = _normalize(_pinyin_frame())

    assert list(out.columns) == TARGET_COLS
    # 5 个拼音原名全部被消费（输出中不再残留）
    for src in PYDX_MAPPING:
        assert src not in out.columns, f"拼音列未被消费: {src}"
    # 值精确落到契约列
    assert out.loc[0, "date"] == 19900301
    assert out.loc[0, "cash_div"] == 0.0
    assert out.loc[0, "rights_price"] == 3.56
    assert out.loc[0, "split_ratio"] == 0.0
    assert out.loc[0, "rights_ratio"] == 1.0


# ---------------------------------------------------------------------------
# ③ 中文列名输入（兼容别名）也收敛到 8 列
# ---------------------------------------------------------------------------


def test_chinese_alias_frame_converges_to_contract():
    # 同义别名（分红/派息、送股/送转股）给一致值，验证两套写法都收敛到同一目标列
    cn = pd.DataFrame(
        {
            "代码": ["1"],  # 未补零，须 zfill 到 6 位（与 sync 脚本一致）
            "日期": ["19900301"],
            "分红": [3.0],
            "派息": [3.0],
            "送股": [4.0],
            "送转股": [4.0],
            "配股": [1.0],
            "配股价": [3.56],
        }
    )
    out = _normalize(cn)

    assert list(out.columns) == TARGET_COLS
    assert out.loc[0, "code"] == "000001"
    assert out.loc[0, "date"] == 19900301
    assert out.loc[0, "cash_div"] == 3.0
    assert out.loc[0, "split_ratio"] == 4.0
    assert out.loc[0, "rights_ratio"] == 1.0
    assert out.loc[0, "rights_price"] == 3.56
    # 缺失的 market/category 以 unknown 占位补齐（宽进容错），保证 8 列契约
    assert "market" in out.columns
    assert "category" in out.columns


# ---------------------------------------------------------------------------
# ④ datetime(int YYYYMMDD) → date 语义与 sync 脚本一致（抽查锚点）
# ---------------------------------------------------------------------------


def test_date_is_int_yyyymmdd_like_sync_script():
    # int 输入: 原值保持 int YYYYMMDD，绝不能变成 datetime64
    out_int = _normalize(_pinyin_frame())
    assert not pd.api.types.is_datetime64_any_dtype(out_int["date"])
    assert pd.api.types.is_integer_dtype(out_int["date"])
    assert int(out_int.loc[0, "date"]) == 19900301

    # 字符串 / 带连字符日期输入同样收敛到 int YYYYMMDD
    for raw_date in ("19900301", "1990-03-01"):
        frame = _pinyin_frame()
        frame["datetime"] = raw_date
        out = _normalize(frame)
        assert int(out.loc[0, "date"]) == 19900301, f"date 语义不一致: {raw_date}"


@requires_real_gbbq
def test_real_parse_matches_sync_dry_run(cached_gbbq_reader, tmp_path):
    """与 sync_local_tdx_day.sync_gbbq(dry_run=True) 对账: 记录数与日期跨度必须完全一致。"""
    spec = importlib.util.spec_from_file_location("sync_local_tdx_day_under_test", SYNC_SCRIPT_PATH)
    sync_mod = importlib.util.module_from_spec(spec)
    # dataclass 在 exec 期经 sys.modules 解析字符串注解，必须先注册
    sys.modules[spec.name] = sync_mod
    try:
        spec.loader.exec_module(sync_mod)
    finally:
        sys.modules.pop(spec.name, None)

    parsed = TDXParser().parse_gbbq_file(GBBQ_REAL_PATH)
    res = sync_mod.sync_gbbq(Path(GBBQ_REAL_PATH), tmp_path / "gbbq.parquet", dry_run=True)

    assert res["status"] == "success", res
    assert len(parsed) == res["records"]
    assert int(parsed["date"].min()) == res["min_date"]
    assert int(parsed["date"].max()) == res["max_date"]
    assert parsed["date"].dtype.kind in "iu"


# ---------------------------------------------------------------------------
# ① 真文件解析 → 8 列契约 + date 已转换 + 行数 ≈193,506
# ---------------------------------------------------------------------------


@requires_real_gbbq
def test_parse_gbbq_file_real_file_contract(cached_gbbq_reader):
    df = TDXParser().parse_gbbq_file(GBBQ_REAL_PATH)

    assert not df.empty
    assert list(df.columns) == TARGET_COLS
    assert pd.api.types.is_integer_dtype(df["date"])
    assert not pd.api.types.is_datetime64_any_dtype(df["date"])
    # pytdx 真文件实测 193,506 行（允许 TDX 客户端后续小幅更新）
    assert abs(len(df) - 193_506) <= 1_000, f"行数异常: {len(df)}"

    # 锚点行: 5 键映射方向正确（peigujia→rights_price / peigu_hou→rights_ratio…）
    anchor = df[(df["code"] == "000001") & (df["date"] == 19900301)]
    assert len(anchor) == 1
    # 源值为 float32 精度（3.559999942779541），用近似比较
    assert float(anchor.iloc[0]["rights_price"]) == pytest.approx(3.56, abs=1e-5)
    assert float(anchor.iloc[0]["rights_ratio"]) == 1.0
    assert float(anchor.iloc[0]["cash_div"]) == 0.0
    assert float(anchor.iloc[0]["split_ratio"]) == 0.0

    # 与 data/fq/gbbq.parquet（只读）锚点行逐列一致
    if FQ_GBBQ_PATH.exists():
        fq = pd.read_parquet(FQ_GBBQ_PATH)
        fq_anchor = fq[(fq["code"] == "000001") & (fq["date"] == 19900301)]
        assert len(fq_anchor) == 1
        for col in ("cash_div", "split_ratio", "rights_ratio", "rights_price"):
            assert float(anchor.iloc[0][col]) == float(fq_anchor.iloc[0][col]), col


# ---------------------------------------------------------------------------
# ⑤ save_gbbq_to_fq 只写 tmp_path，输出列 = 契约
# ---------------------------------------------------------------------------


@requires_real_gbbq
def test_save_gbbq_to_fq_writes_contract_to_tmp_only(cached_gbbq_reader, tmp_path):
    fq_mtime_before = FQ_GBBQ_PATH.stat().st_mtime_ns if FQ_GBBQ_PATH.exists() else None

    out_path = tmp_path / "gbbq.parquet"
    ok = TDXParser().save_gbbq_to_fq(GBBQ_REAL_PATH, str(out_path))

    assert ok is True
    assert out_path.exists()
    written = pd.read_parquet(out_path)
    assert list(written.columns) == TARGET_COLS
    assert pd.api.types.is_integer_dtype(written["date"])
    assert abs(len(written) - 193_506) <= 1_000

    # 红线: 真实 data/fq/gbbq.parquet 绝不能被测试路径覆写
    if fq_mtime_before is not None:
        assert FQ_GBBQ_PATH.stat().st_mtime_ns == fq_mtime_before, "真实 gbbq.parquet 被测试改写!"


# ---------------------------------------------------------------------------
# ⑥ _parse_gbbq_manually 输出列 ⊆ 契约（且归一到精确契约 + int date）
# ---------------------------------------------------------------------------


@requires_real_gbbq
def test_parse_gbbq_manually_within_contract(tmp_path):
    """用真文件前 500 条记录的截断副本（记录边界对齐），避免 193k 行纯 Python 解密超时。"""
    raw = Path(GBBQ_REAL_PATH).read_bytes()
    truncated = tmp_path / "gbbq_truncated"
    truncated.write_bytes(raw[: 4 + 500 * 29])

    df = TDXParser()._parse_gbbq_manually(str(truncated))

    assert not df.empty
    assert set(df.columns) <= set(TARGET_COLS), f"越界列: {set(df.columns) - set(TARGET_COLS)}"
    assert list(df.columns) == TARGET_COLS, "输出未归一到契约列序"
    assert pd.api.types.is_integer_dtype(df["date"]), f"date 须为 int YYYYMMDD, 实为 {df['date'].dtype}"
    assert int(df["date"].iloc[0]) == 19900301


# ---------------------------------------------------------------------------
# ⑦ parse_gbbq_native（主/备两条路径）同样收敛到契约
# ---------------------------------------------------------------------------


@requires_real_gbbq
def test_parse_gbbq_native_returns_contract(cached_gbbq_reader):
    df = parse_gbbq_native(GBBQ_REAL_PATH)

    assert not df.empty
    assert list(df.columns) == TARGET_COLS
    assert pd.api.types.is_integer_dtype(df["date"])
