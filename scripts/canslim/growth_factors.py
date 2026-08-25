"""CANSLIM 成长因子构造器 — 从 data/lake/financial/ 构建季度成长指标。

红蓝对抗修正案落地 (docs/analysis/CANSLIM_RED_BLUE_ADVERSARY_20260824.md):
- A3 边界规则: R-BASE-NEG / R-BASE-TINY / R-MIN-HIST / R-YOUNG / R-FIN
- A2 金融剔除: 静态名单 financial_codes.json (名称验证, 生成时冻结)
- §7.5 双判据: 本模块产出季度面板; 事件法判据在 gate 脚本实现

关键语义 (P4 实测锁定): 财报行为同年累计值(YTD), 单季值须按年边界差分;
跨年 Q1 即新累计起点。公告日期为 YYMMDD 浮点 → 归一化为 YYYYMMDD 整数。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FINANCIAL_DIR = PROJECT_ROOT / "data" / "lake" / "financial"
FINANCIAL_CODES_JSON = Path(__file__).resolve().parent / "financial_codes.json"

TINY_BASE = 5e6          # R-BASE-TINY: 基数绝对值下限 (元)
TTM_WINDOW = 4           # R-MIN-HIST: TTM 满窗
MIN_ANNUAL_OBS = 4       # R-YOUNG: 年报数下限 (3 年 CAGR + 连续增长判定)
Q_OFFSET_MONTHS = {3: 3, 6: 2, 9: 3, 12: 4}   # 公告缺失兜底偏移 (桥接同款)


def normalize_announcement_int(raw) -> float:
    """YYMMDD 浮点 → YYYYMMDD 整数; 缺失/非法 → NaN。"""
    try:
        fv = float(raw)
    except (TypeError, ValueError):
        return np.nan
    if np.isnan(fv) or fv <= 0:
        return np.nan
    iv = int(fv)
    if iv < 1000000:
        return float(20000000 + iv)
    return float(iv)


def single_quarter_diff(cum: pd.Series, report_dates: pd.Series) -> pd.Series:
    """同年累计值差分为单季; 年首行(含首行整体)保留原值。输入须按报告期升序。"""
    years = (report_dates.astype("int64") // 10000).astype(int)
    same_year_as_prev = years.eq(years.shift(1))
    return cum.where(~same_year_as_prev, cum - cum.shift(1))


def _yoy(base: pd.Series, cur: pd.Series) -> pd.Series:
    """同比增速, 应用基数规则: base<=0 或 |base|<TINY_BASE → NaN。"""
    valid = base.notna() & cur.notna() & (base > 0) & (base.abs() >= TINY_BASE)
    out = cur / base - 1.0
    return out.where(valid)


def ttm_and_yoy(single_quarter: pd.Series) -> tuple[pd.Series, pd.Series]:
    """单季序列 → (滚动4季TTM[满窗], TTM同比[对 shift(4)])。"""
    ttm = single_quarter.rolling(TTM_WINDOW, min_periods=TTM_WINDOW).sum()
    yoy = _yoy(ttm.shift(TTM_WINDOW), ttm)
    return ttm, yoy


def annual_metrics(fy_rows: pd.DataFrame) -> pd.DataFrame:
    """年报行 → 年度指标。

    输入列: report_date(int YYYYMMDD), effective_date(datetime), eps。
    输出追加: a_cagr3, a_consec_growth, n_fy_so_far, is_young。
    """
    out = fy_rows.sort_values("report_date").copy()
    fy_eps = out.set_index("report_date")["eps"]

    cagr = []
    consec = []
    for i in range(len(out)):
        if i < 3:
            cagr.append(np.nan)
            consec.append(False)
            continue
        e_now = fy_eps.iloc[i]
        e_base = fy_eps.iloc[i - 3]
        window = fy_eps.iloc[i - 3 : i + 1]
        diffs = window.diff().dropna()
        ok = (
            pd.notna(e_now)
            and pd.notna(e_base)
            and e_now > 0
            and e_base > 0
        )
        cagr.append((e_now / e_base) ** (1.0 / 3) - 1.0 if ok else np.nan)
        consec.append(bool((diffs > 0).all()) and len(diffs) == 3)

    out["a_cagr3"] = cagr
    out["a_consec_growth"] = consec
    out["n_fy_so_far"] = range(1, len(out) + 1)
    out["is_young"] = out["n_fy_so_far"] < MIN_ANNUAL_OBS
    return out


def effective_dates(report_date: pd.Series, ann_int: pd.Series) -> pd.Series:
    """公告日优先; 缺失用报告期+季度偏移兜底 (桥接 _apply_report_date_offset 同款)。"""
    rep_dt = pd.to_datetime(report_date.astype("int64").astype(str), format="%Y%m%d", errors="coerce")
    ann_dt = pd.to_datetime(
        ann_int.map(lambda v: str(int(v)) if pd.notna(v) else None),
        format="%Y%m%d",
        errors="coerce",
    )
    fallback = rep_dt.apply(
        lambda d: d + pd.DateOffset(months=Q_OFFSET_MONTHS[d.month]) if pd.notna(d) else pd.NaT
    )
    eff = ann_dt.fillna(fallback)
    # 公告日早于报告期(数据异常)钳位回报告期
    earlier = eff < rep_dt
    eff = eff.where(~earlier, rep_dt)
    return eff


def build_quarterly_metrics(fin_df: pd.DataFrame, financial_codes: set[str]) -> pd.DataFrame | None:
    """单只股票的原始财务 parquet 内容 → 季度成长指标面板。

    输入: TDX 原始中文列 (须先经 bridge.map_fields 得标准列)。
    输出行 = 季度; 列含 code/report_date/effective_date/c_*/a_*/roe/is_fin/is_young。
    """
    if fin_df is None or fin_df.empty:
        return None

    from uniquant.brain.factors.financial_bridge import FinancialFactorBridge

    mapped = FinancialFactorBridge().map_fields(fin_df.copy())
    required = {"code", "report_date", "eps"}
    if not required.issubset(mapped.columns):
        return None

    df = mapped.sort_values("report_date").reset_index(drop=True)
    df["effective_date"] = effective_dates(df["report_date"], df.get("财报公告日期"))

    # ── C: 单季扣非净利同比 / TTM 同比 ──
    for src_col, sq_name in [("net_profit_deducted", "sq_deducted"), ("net_profit_parent", "sq_parent")]:
        if src_col in df.columns:
            df[sq_name] = single_quarter_diff(pd.Series(df[src_col], dtype=float), df["report_date"])
        else:
            df[sq_name] = np.nan

    if df["sq_deducted"].notna().any():
        _, df["c_ttm_yoy"] = ttm_and_yoy(df["sq_deducted"].astype(float))
        base_q = df["sq_deducted"].shift(TTM_WINDOW)
        df["c_single_yoy"] = _yoy(base_q, df["sq_deducted"])
    elif df["sq_parent"].notna().any():
        # 扣非缺失时降级用归母口径 (如实记录, 因子名不变但 quality 列标记)
        _, df["c_ttm_yoy"] = ttm_and_yoy(df["sq_parent"].astype(float))
        df["c_single_yoy"] = _yoy(df["sq_parent"].shift(TTM_WINDOW), df["sq_parent"])
        df["uses_parent_fallback"] = True
    else:
        df["c_ttm_yoy"] = np.nan
        df["c_single_yoy"] = np.nan
    if "uses_parent_fallback" not in df.columns:
        df["uses_parent_fallback"] = False

    # ── 营收 TTM 同比 ──
    if "revenue" in df.columns:
        sq_rev = single_quarter_diff(pd.Series(df["revenue"], dtype=float), df["report_date"])
        _, df["rev_ttm_yoy"] = ttm_and_yoy(sq_rev.astype(float))
    else:
        df["rev_ttm_yoy"] = np.nan

    # ── ROE ──
    df["roe"] = pd.to_numeric(df.get("roe"), errors="coerce")

    # ── A: 年度指标 (仅年报行参与构造, 前向填充到各季度) ──
    fy_mask = df["report_date"].astype("int64") % 10000 == 1231
    a_cols = {}
    if fy_mask.any():
        ann = annual_metrics(df.loc[fy_mask, ["report_date", "effective_date", "eps"]])
        ann = (
            ann.dropna(subset=["effective_date"])
            .drop_duplicates(subset="effective_date", keep="last")
        )
        ann = ann.set_index("effective_date")[["a_cagr3", "a_consec_growth", "is_young"]]
        aligned = df["effective_date"].map(ann["a_cagr3"]).astype(float)
        a_cols["a_cagr3"] = aligned
        a_cols["a_consec_growth"] = df["effective_date"].map(ann["a_consec_growth"])
        young_by_eff = ann["is_young"]
        a_cols["is_young"] = df["effective_date"].map(young_by_eff).astype("boolean")
    else:
        a_cols["a_cagr3"] = np.nan
        a_cols["a_consec_growth"] = False
        a_cols["is_young"] = True
    for k, v in a_cols.items():
        df[k] = v.values if isinstance(v, pd.Series) else v

    code6 = str(df["code"].iloc[0]).split(".")[0]
    df["is_fin"] = code6 in financial_codes

    keep = [
        "code", "report_date", "effective_date",
        "c_single_yoy", "c_ttm_yoy", "rev_ttm_yoy", "roe",
        "a_cagr3", "a_consec_growth", "is_young", "is_fin", "uses_parent_fallback",
    ]
    return df[[c for c in keep if c in df.columns]]


def load_financial_codes() -> set[str]:
    data = json.loads(FINANCIAL_CODES_JSON.read_text(encoding="utf-8"))
    return set(data["codes"])


def build_universe_metrics(symbols: list[str], financial_codes: set[str] | None = None) -> pd.DataFrame:
    """批量构建全部股票的季度成长指标长表。"""
    codes = load_financial_codes() if financial_codes is None else financial_codes
    frames = []
    skipped = 0
    for sym in symbols:
        p = FINANCIAL_DIR / f"{sym}.parquet"
        if not p.exists():
            skipped += 1
            continue
        qm = build_quarterly_metrics(pd.read_parquet(p), codes)
        if qm is None or qm.empty:
            skipped += 1
            continue
        frames.append(qm)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if skipped:
        import logging

        logging.getLogger(__name__).info("build_universe_metrics: 跳过 %d 只 (缺文件/字段)", skipped)
    return out


def merge_factors_to_daily(daily_df: pd.DataFrame, qm: pd.DataFrame) -> pd.DataFrame:
    """把季度因子按公告日 merge_asof 到日线面板 (point-in-time, backward)。"""
    daily = daily_df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    qm = qm.rename(columns={"effective_date": "date"})
    factor_cols = [
        c for c in ["c_single_yoy", "c_ttm_yoy", "rev_ttm_yoy", "roe", "a_cagr3",
                    "a_consec_growth", "is_young", "is_fin", "uses_parent_fallback"]
        if c in qm.columns
    ]
    qm_min = qm[["code", "date"] + factor_cols].sort_values("date")
    merged_parts = []
    for sym, g in daily.groupby("code"):
        sub = g.sort_values("date")
        qsub = qm_min[qm_min["code"] == sym]
        if qsub.empty:
            for c in factor_cols:
                sub[c] = np.nan
        else:
            sub = pd.merge_asof(sub, qsub.drop(columns=["code"]), on="date", direction="backward")
        merged_parts.append(sub)
    return pd.concat(merged_parts, ignore_index=True)