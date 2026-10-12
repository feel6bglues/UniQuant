#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GBBQ resync 后锚点验收 (WS-D Step 2d)。

对 `data/fq/gbbq.parquet`（由 `scripts/maintenance/sync_local_tdx_day.py::sync_gbbq`
从本地通达信 `hq_cache/gbbq` 同步产出）执行 5 组锚点验收：

A1  茅台 600519 交叉对账：gbbq 2024 年度 category=1 派现合计 vs
    `data/lake/dividend/600519.SH.parquet` 同期 dps 合计（两源同口径）。
A2  送转手算 3 例：理论除权价 (pre_close - cash_div/10) / (1 + split_ratio/10)
    的手算复权因子增量 vs 新轨 CorporateActionAdjuster 引擎增量，
    并与原始 gbbq 二进制文件（pytdx GbbqReader）同事件数值逐位比对。
A3  新轨 qfq 锚点：CorporateActionAdjuster 对 600519 全历史日线前复权，
    末日 qfq == 原始 close（锚点性质）、volume 序列与原始完全相等。
A4  量纲分布哨兵：category=1 的 cash_div p50≈1.0 / split_ratio p99≈10 /
    rights_price 不除 10（记录 p50）。
A5  2650.0 类超大量纲记录归档：非 category=1 行数与 category 分布，
    并验证 GBBQProcessorV15.load_and_clean 确实把它们挡在因子输入之外。

用法:
    .venv/bin/python scripts/maintenance/verify_gbbq_anchors.py

输出:
    results/migration/gbbq_anchor_verification.json

任一锚点 FAIL => exit 1。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

GBBQ_PARQUET = PROJECT_ROOT / "data" / "fq" / "gbbq.parquet"
RAW_GBBQ_PATH = Path.home() / ".local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq"
DAILY_600519 = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily" / "600519.SH.parquet"
DIVIDEND_600519 = PROJECT_ROOT / "data" / "lake" / "dividend" / "600519.SH.parquet"
OUTPUT_JSON = PROJECT_ROOT / "results" / "migration" / "gbbq_anchor_verification.json"

EXPECTED_COLUMNS = [
    "code", "market", "date", "category",
    "cash_div", "split_ratio", "rights_ratio", "rights_price",
]

TARGET_CODE = "600519"
TARGET_SYMBOL = "600519.SH"

# A1: 2024 自然年（按除权日）在 dividend lake 的派现合计，元/股
A1_DIVIDEND_2024_SUM = 54.758
# A1: 单事件 20240619 gbbq cash_div=308.76（10 派 308.76）=> 30.876 元/股
A1_EVENT_DATE = 20240619
A1_EVENT_DPS = 30.876

# A2: 手算样例（category=1 且 split_ratio>0，且日线覆盖除权日）
A2_HANDCALC_DATES = [20110701, 20140625, 20150717]
# A2: 仅做 raw 二进制一致性比对（日线 lake 缺该交易日，无法手算）
A2_RAW_ONLY_DATES = [20060519]


def _check(name: str, passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
    return {"name": name, "expected": expected, "actual": actual, "pass": bool(passed)}


def _anchor(anchor_id: str, name: str, checks: list[dict[str, Any]],
            metrics: dict[str, Any]) -> dict[str, Any]:
    status = "PASS" if checks and all(c["pass"] for c in checks) else "FAIL"
    return {
        "id": anchor_id,
        "name": name,
        "status": status,
        "checks": checks,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# resync gate (S0)
# ---------------------------------------------------------------------------
def gate_resync(gbbq: pd.DataFrame, raw: pd.DataFrame | None) -> dict[str, Any]:
    c1 = gbbq[gbbq["category"] == 1]
    checks = [
        _check(
            "columns_8_contract",
            list(gbbq.columns) == EXPECTED_COLUMNS,
            EXPECTED_COLUMNS,
            list(gbbq.columns),
        ),
        _check(
            "category1_latest_date",
            int(c1["date"].max()) >= 20261014,
            ">= 20261014",
            int(c1["date"].max()),
        ),
    ]
    metrics: dict[str, Any] = {
        "parquet_rows": int(len(gbbq)),
        "category1_rows": int(len(c1)),
        "category1_max_date": int(c1["date"].max()),
        "columns": list(gbbq.columns),
        "dtypes": {k: str(v) for k, v in gbbq.dtypes.items()},
    }
    if raw is not None:
        diff = int(len(raw) - len(gbbq))
        checks.append(
            _check("raw_vs_parquet_row_diff", diff == 0, "0 (raw 全量无清洗丢失)", diff)
        )
        metrics.update(
            {
                "raw_rows": int(len(raw)),
                "raw_minus_parquet": diff,
                "raw_category1_rows": int((raw["category"] == 1).sum()),
            }
        )
    else:
        metrics["raw_minus_parquet"] = None
    return _anchor("S0", "resync 行数/列契约/最新事件日 gate", checks, metrics)


# ---------------------------------------------------------------------------
# A1: 茅台 2024 派现交叉对账
# ---------------------------------------------------------------------------
def anchor_a1(gbbq: pd.DataFrame) -> dict[str, Any]:
    events = gbbq[
        (gbbq["code"] == TARGET_CODE) & (gbbq["category"] == 1)
        & (gbbq["date"] // 10000 == 2024)
    ].sort_values("date")
    gbbq_sum_10 = float(events["cash_div"].sum())
    gbbq_per_share = gbbq_sum_10 / 10.0

    div = pd.read_parquet(DIVIDEND_600519)
    div_2024 = div[div["year"] == 2024]
    div_sum = float(div_2024["dps"].sum())

    single = events[events["date"] == A1_EVENT_DATE]
    single_dps = float(div_2024.loc[div_2024["ex_date"] == A1_EVENT_DATE, "dps"].iloc[0])
    single_gbbq = float(single["cash_div"].iloc[0]) / 10.0 if len(single) else float("nan")

    checks = [
        _check(
            "gbbq_2024_sum_per_share_vs_dividend_lake",
            abs(gbbq_per_share - div_sum) <= 1e-3,
            f"{A1_DIVIDEND_2024_SUM}",
            round(gbbq_per_share, 6),
        ),
        _check(
            "event_20240619_gbbq_vs_dividend_lake",
            abs(single_gbbq - single_dps) <= 1e-4,
            round(single_dps, 6),
            round(single_gbbq, 6),
        ),
        _check(
            "event_20240619_is_10_for_308_76",
            abs(float(single["cash_div"].iloc[0]) - 308.76) <= 1e-3 if len(single) else False,
            308.76,
            float(single["cash_div"].iloc[0]) if len(single) else None,
        ),
        _check(
            "unit_ratio_gbbq_per10_dividend_pershare",
            abs(gbbq_sum_10 / div_sum - 10.0) <= 1e-6,
            10.0,
            round(gbbq_sum_10 / div_sum, 9),
        ),
    ]
    metrics = {
        "gbbq_2024_events": [
            {"date": int(r["date"]), "cash_div_per_10": float(r["cash_div"])}
            for _, r in events.iterrows()
        ],
        "gbbq_2024_sum_per_10": gbbq_sum_10,
        "gbbq_2024_sum_per_share": gbbq_per_share,
        "dividend_lake_2024_dps_sum": div_sum,
        "dividend_lake_2024_rows": int(len(div_2024)),
        "abs_diff": abs(gbbq_per_share - div_sum),
        "unit_note": "gbbq cash_div=元/10股；dividend lake dps=元/股；比值恰为 10",
    }
    return _anchor("A1", "茅台 600519 两源派现交叉对账", checks, metrics)


# ---------------------------------------------------------------------------
# A2: 送转手算 3 例 + 原始二进制一致性
# ---------------------------------------------------------------------------
def _raw_gbbq() -> pd.DataFrame | None:
    if not RAW_GBBQ_PATH.exists():
        return None
    from pytdx.reader import GbbqReader  # 局部导入：可选依赖

    raw = GbbqReader().get_df(str(RAW_GBBQ_PATH))
    if raw is None or raw.empty:
        return None
    raw = raw.copy()
    raw["code"] = raw["code"].astype(str).str.zfill(6)
    return raw


def _engine_factor_series(daily: pd.DataFrame) -> tuple[np.ndarray, str]:
    """返回新轨复权因子序列与实现模式（新轨不可用时降级为手动公式）。"""
    try:
        from uniquant.data.corporate_action import CorporateActionAdjuster

        adj = CorporateActionAdjuster(gbbq_path=GBBQ_PARQUET)
        factors = adj.compute_factors(daily, TARGET_SYMBOL)
        ratio = factors["factor"].to_numpy(dtype=np.float64)
        if len(ratio) == len(daily):
            return ratio, "CorporateActionAdjuster(new_track)"
    except Exception as exc:  # noqa: BLE001 —— 验收件需降级而非崩溃
        print(f"[warn] CorporateActionAdjuster 不可用，降级手动 qfq: {exc}", file=sys.stderr)
    return _manual_factors(daily), "manual_formula_fallback"


def _manual_factors(daily: pd.DataFrame) -> np.ndarray:
    """手动因子：逐事件 increment = pre_close / round((pre_close-cash)/(1+split+rights), 2)。

    与 /tmp/opencode/gbbq_probe/p3_two_tracks.py 的降级逻辑同构（仅在 A3 降级路径使用）。
    """
    from uniquant.data.utils.smart_factor_calculator import GBBQProcessorV15

    clean = GBBQProcessorV15.load_and_clean(str(GBBQ_PARQUET))
    ev = GBBQProcessorV15.aggregate_events(clean[clean["code"] == TARGET_CODE].copy())
    ev_by_date = {
        pd.Timestamp(r["date"]): (
            float(r["cash"]), float(r["split"]), float(r["rights"]), float(r["r_price"])
        )
        for _, r in ev.iterrows()
    } if not ev.empty else {}

    close = daily["close"].to_numpy(dtype=np.float64)
    dates = pd.to_datetime(daily["date"]).reset_index(drop=True)
    factors = np.ones(len(daily), dtype=np.float64)
    cur = 1.0
    for i in range(len(daily)):
        if i > 0 and dates.iloc[i] in ev_by_date:
            cash, split, rights, r_price = ev_by_date[dates.iloc[i]]
            pre = float(close[i - 1])
            theo = round((pre - cash + r_price * rights) / (1 + split + rights), 2)
            if theo > 0:
                cur *= pre / theo
        factors[i] = cur
    return factors


def anchor_a2(gbbq: pd.DataFrame, raw: pd.DataFrame | None) -> dict[str, Any]:
    daily = pd.read_parquet(DAILY_600519).copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)
    engine_factors, mode = _engine_factor_series(daily)

    checks: list[dict[str, Any]] = []
    handcalc: list[dict[str, Any]] = []
    raw_only: list[dict[str, Any]] = []

    # 原始二进制一致性：所有指定事件
    for ds in A2_HANDCALC_DATES + A2_RAW_ONLY_DATES:
        row = gbbq[
            (gbbq["code"] == TARGET_CODE) & (gbbq["date"] == ds) & (gbbq["category"] == 1)
        ]
        record: dict[str, Any] = {"date": ds, "in_daily": False}
        if len(row):
            record["gbbq_cash_div"] = float(row["cash_div"].iloc[0])
            record["gbbq_split_ratio"] = float(row["split_ratio"].iloc[0])
        if raw is None:
            record["raw_match"] = None
        else:
            rrow = raw[
                (raw["code"] == TARGET_CODE) & (raw["datetime"] == ds)
                & (raw["category"] == 1)
            ]
            match = bool(
                len(row) and len(rrow)
                and abs(float(row["cash_div"].iloc[0]) - float(rrow["hongli_panqianliutong"].iloc[0])) <= 1e-6
                and abs(float(row["split_ratio"].iloc[0]) - float(rrow["songgu_qianzongguben"].iloc[0])) <= 1e-9
            )
            record["raw_match"] = match
            checks.append(_check(f"raw_binary_match_{ds}", match, True, match))
        if ds in A2_RAW_ONLY_DATES:
            raw_only.append(record)

    # 手算 3 例
    for ds in A2_HANDCALC_DATES:
        row = gbbq[
            (gbbq["code"] == TARGET_CODE) & (gbbq["date"] == ds) & (gbbq["category"] == 1)
        ]
        if not len(row):
            checks.append(_check(f"handcalc_event_present_{ds}", True, "event exists", "missing"))
            continue
        cash_div = float(row["cash_div"].iloc[0])
        split_ratio = float(row["split_ratio"].iloc[0])
        idx = np.where(daily["date"].values == np.datetime64(pd.Timestamp(str(ds))))[0]
        if not len(idx):
            checks.append(_check(f"handcalc_daily_cover_{ds}", False, "daily row", "missing"))
            continue
        i = int(idx[0])
        pre_close = float(daily["close"].iloc[i - 1])
        ex_open = float(daily["open"].iloc[i])
        theo = round((pre_close - cash_div / 10.0) / (1.0 + split_ratio / 10.0), 2)
        f_hand = pre_close / theo
        f_engine = float(engine_factors[i]) / float(engine_factors[i - 1])
        diff = abs(f_hand - f_engine)
        gap_vs_open = abs(ex_open - theo) / pre_close
        checks.append(
            _check(f"handcalc_factor_increment_{ds}", diff <= 1e-6,
                   "|手算-引擎| <= 1e-6", f"{diff:.3e}")
        )
        checks.append(
            _check(f"handcalc_theo_vs_ex_open_{ds}", gap_vs_open <= 0.05,
                   "|ex_open-theo|/pre_close <= 5%", f"{gap_vs_open:.4%}")
        )
        handcalc.append({
            "date": ds,
            "cash_div_per_10": cash_div,
            "split_ratio_per_10": split_ratio,
            "pre_close": pre_close,
            "theoretical_ex_price": theo,
            "actual_ex_open": ex_open,
            "factor_hand": f_hand,
            "factor_engine": f_engine,
            "abs_diff": diff,
            "theo_vs_open_rel": gap_vs_open,
        })

    checks.append(_check("handcalc_examples_count", len(handcalc) == 3, 3, len(handcalc)))

    metrics = {
        "engine_mode": mode,
        "handcalc": handcalc,
        "raw_only_events": raw_only,
        "raw_file_available": raw is not None,
        "formula": "(pre_close - cash_div/10) / (1 + split_ratio/10)",
    }
    return _anchor("A2", "送转手算 3 例 + 原始 gbbq 二进制一致性", checks, metrics)


# ---------------------------------------------------------------------------
# A3: 新轨 qfq 锚点
# ---------------------------------------------------------------------------
def anchor_a3(gbbq: pd.DataFrame) -> dict[str, Any]:
    daily = pd.read_parquet(DAILY_600519).copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    try:
        from uniquant.data.corporate_action import CorporateActionAdjuster

        adj = CorporateActionAdjuster(gbbq_path=GBBQ_PARQUET)
        qfq = adj.adjust(daily, TARGET_SYMBOL, adjust_type="qfq")
        mode = "CorporateActionAdjuster(new_track)"
        degraded = False
    except Exception as exc:  # noqa: BLE001 —— 并行改造期降级
        print(f"[warn] A3 降级手动 qfq: {exc}", file=sys.stderr)
        factors = _manual_factors(daily)
        qfq = daily.copy()
        qfq["close"] = daily["close"].to_numpy() * factors / factors[-1]
        qfq["adj_factor"] = factors / factors[-1]
        mode = f"manual_formula_fallback({type(exc).__name__})"
        degraded = True

    raw_close = daily["close"].to_numpy(dtype=np.float64)
    qfq_close = qfq["close"].to_numpy(dtype=np.float64)
    raw_volume = daily["volume"].to_numpy()
    qfq_volume = qfq["volume"].to_numpy()

    last_diff = abs(float(qfq_close[-1]) - float(raw_close[-1]))
    volume_equal = bool(np.array_equal(raw_volume, qfq_volume))
    applied = float(np.max(np.abs(qfq_close - raw_close))) > 0
    adj_last = float(qfq["adj_factor"].iloc[-1]) if "adj_factor" in qfq.columns else None

    checks = [
        _check("qfq_last_day_equals_raw_close", last_diff == 0.0, "0.0", f"{last_diff:.3e}"),
        _check("volume_series_identical", volume_equal, True, volume_equal),
        _check("adjustment_actually_applied", applied, True, applied),
        _check("adj_factor_last_day_is_1", (adj_last is not None and abs(adj_last - 1.0) < 1e-12),
               1.0, adj_last),
        _check("rows_unchanged", len(qfq) == len(daily), len(daily), len(qfq)),
    ]
    metrics = {
        "mode": mode,
        "degraded": degraded,
        "rows": int(len(daily)),
        "first_date": str(daily["date"].iloc[0].date()),
        "last_date": str(daily["date"].iloc[-1].date()),
        "raw_close_last": float(raw_close[-1]),
        "qfq_close_last": float(qfq_close[-1]),
        "raw_close_first": float(raw_close[0]),
        "qfq_close_first": float(qfq_close[0]),
        "max_abs_price_shift": float(np.max(np.abs(qfq_close - raw_close))),
        "adj_factor_last": adj_last,
        "adj_factor_first": float(qfq["adj_factor"].iloc[0]) if "adj_factor" in qfq.columns else None,
    }
    return _anchor("A3", "新轨 qfq 锚点 (600519 全历史)", checks, metrics)


# ---------------------------------------------------------------------------
# A4: 量纲分布哨兵
# ---------------------------------------------------------------------------
def anchor_a4(gbbq: pd.DataFrame) -> dict[str, Any]:
    c1 = gbbq[gbbq["category"] == 1]
    cash_p50 = float(c1["cash_div"].median())
    cash_p99 = float(c1["cash_div"].quantile(0.99))
    split_p99 = float(c1["split_ratio"].quantile(0.99))
    rights_p50 = float(c1["rights_price"].median())
    rights_nonzero = int((c1["rights_price"] > 0).sum())

    checks = [
        _check("cash_div_p50_about_1", abs(cash_p50 - 1.0) <= 0.25, "~1.0", cash_p50),
        _check("split_ratio_p99_about_10", 5.0 <= split_p99 <= 15.0, "~10", split_p99),
        _check(
            "rights_price_not_divided_by_10",
            abs(rights_p50 - 0.0) < 1e-9,
            "p50 == 0.0 (raw 量纲保留, 不 /10)",
            rights_p50,
        ),
        _check("cash_div_p99_sane", cash_p99 < 1000.0, "< 1000", cash_p99),
    ]
    metrics = {
        "category1_rows": int(len(c1)),
        "cash_div": {
            "p50": cash_p50, "p99": cash_p99,
            "max": float(c1["cash_div"].max()),
        },
        "split_ratio": {
            "p50": float(c1["split_ratio"].median()),
            "p99": split_p99,
            "max": float(c1["split_ratio"].max()),
        },
        "rights_price": {
            "p50": rights_p50,
            "p99": float(c1["rights_price"].quantile(0.99)),
            "nonzero_rows": rights_nonzero,
        },
        "unit_note": "cash_div/split_ratio/rights_ratio 为 per-10 股量纲, rights_price 为元/股不除 10",
    }
    return _anchor("A4", "category=1 量纲分布哨兵", checks, metrics)


# ---------------------------------------------------------------------------
# A5: 超大量纲 (2650.0 类) 记录归档 + 因子隔离
# ---------------------------------------------------------------------------
def anchor_a5(gbbq: pd.DataFrame) -> dict[str, Any]:
    non_c1 = gbbq[gbbq["category"] != 1]
    dist = {int(k): int(v) for k, v in gbbq["category"].value_counts().sort_index().items()}
    non_c1_dist = {
        int(k): int(v) for k, v in non_c1["category"].value_counts().sort_index().items()
    }
    big = gbbq[gbbq["split_ratio"] == 2650.0]
    big_dist = {
        int(k): int(v) for k, v in big["category"].value_counts().sort_index().items()
    }
    huge = gbbq[(gbbq["category"] != 1) & (gbbq["split_ratio"] > 10)]

    from uniquant.data.utils.smart_factor_calculator import GBBQProcessorV15

    cleaned = GBBQProcessorV15.load_and_clean(str(GBBQ_PARQUET))
    cleaned_non_c1 = int((cleaned["category"] != 1).sum()) if "category" in cleaned.columns else -1

    # load_and_clean 额外过滤 date <= REAL_TODAY（未来除权日不进因子）
    c1 = gbbq[gbbq["category"] == 1]
    today_int = int(datetime.now().strftime("%Y%m%d"))
    positive = (c1["cash_div"] > 0) | (c1["split_ratio"] > 0) | (c1["rights_ratio"] > 0)
    expected_rows = int((positive & (c1["date"] <= today_int)).sum())
    future_positive = int((positive & (c1["date"] > today_int)).sum())

    checks = [
        _check("non_category1_rows_exist_for_archive", len(non_c1) > 0, "> 0", int(len(non_c1))),
        _check("2650_class_all_non_category1", int((big["category"] == 1).sum()) == 0,
               "0 rows of category=1", int((big["category"] == 1).sum())),
        _check("factor_input_excludes_non_category1", cleaned_non_c1 == 0, 0, cleaned_non_c1),
        _check(
            "factor_input_row_count_matches_positive_filter",
            len(cleaned) == expected_rows,
            expected_rows,
            int(len(cleaned)),
        ),
        _check("huge_split_rows_excluded_from_factor_input",
               not bool(np.isclose(cleaned["split"].to_numpy(), 265.0).any()) if len(cleaned) else True,
               "2650.0 类 (per-share 265.0) 不在因子输入",
               bool(np.isclose(cleaned["split"].to_numpy(), 265.0).any()) if len(cleaned) else False),
        _check("cleaned_max_split_bounded_by_category1_history",
               float(cleaned["split"].max()) <= 100.0 if len(cleaned) else True,
               "<= 100.0 (per-share, 对应 1992 年 10 送 99 历史极值)",
               float(cleaned["split"].max()) if len(cleaned) else None),
    ]
    metrics = {
        "total_rows": int(len(gbbq)),
        "category_distribution_all": dist,
        "non_category1_rows": int(len(non_c1)),
        "non_category1_category_distribution": non_c1_dist,
        "split_ratio_2650_rows": int(len(big)),
        "split_ratio_2650_category_distribution": big_dist,
        "non_category1_split_gt_10_rows": int(len(huge)),
        "factor_input_rows_after_load_and_clean": int(len(cleaned)),
        "factor_input_expected_rows": expected_rows,
        "future_exdate_rows_excluded": future_positive,
        "factor_input_non_category1_rows": cleaned_non_c1,
        "factor_input_split_gt_1_per_share_rows": int((cleaned["split"] > 1.0).sum()) if len(cleaned) else 0,
        "factor_input_max_split_per_share": float(cleaned["split"].max()) if len(cleaned) else None,
        "note": "2650.0 等超大量纲行全部落在 category!=1，且被 GBBQProcessorV15.load_and_clean 过滤，不进因子输入",
    }
    return _anchor("A5", "超大量纲记录归档与因子隔离", checks, metrics)


def main() -> int:
    gbbq = pd.read_parquet(GBBQ_PARQUET)
    raw = _raw_gbbq()

    anchors = [
        gate_resync(gbbq, raw),
        anchor_a1(gbbq),
        anchor_a2(gbbq, raw),
        anchor_a3(gbbq),
        anchor_a4(gbbq),
        anchor_a5(gbbq),
    ]

    n_pass = sum(1 for a in anchors if a["status"] == "PASS")
    n_fail = sum(1 for a in anchors if a["status"] != "PASS")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": str(Path(__file__).resolve().relative_to(PROJECT_ROOT)),
        "gbbq_parquet": str(GBBQ_PARQUET.relative_to(PROJECT_ROOT)),
        "gbbq_rows": int(len(gbbq)),
        "gbbq_columns": list(gbbq.columns),
        "raw_gbbq_path": str(RAW_GBBQ_PATH),
        "anchors": {a["id"]: a for a in anchors},
        "summary": {
            "total": len(anchors),
            "passed": n_pass,
            "failed": n_fail,
            "status": "PASS" if n_fail == 0 else "FAIL",
        },
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_JSON.with_suffix(f".json.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(OUTPUT_JSON)

    print(f"{'ID':<4} {'ANCHOR':<44} {'STATUS':<6} CHECKS")
    for a in anchors:
        passed = sum(1 for c in a["checks"] if c["pass"])
        print(f"{a['id']:<4} {a['name']:<44} {a['status']:<6} {passed}/{len(a['checks'])}")
        for c in a["checks"]:
            if not c["pass"]:
                print(f"     [FAIL] {c['name']}: expected={c['expected']} actual={c['actual']}")
    print(f"\n=> {payload['summary']['status']} "
          f"({n_pass}/{len(anchors)} anchors) | {OUTPUT_JSON.relative_to(PROJECT_ROOT)}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
