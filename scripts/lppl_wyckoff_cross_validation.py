#!/usr/bin/env python3
"""
LPPL × Wyckoff 交叉验证诊断脚本

验证 12 项假设 (H1-H12) 并生成结构化报告。

三阶段:
  1. 数据采集 — 对 golden_100 运行 LPPL + Wyckoff 诊断
  2. 统计分析 — 计算假设验证指标
  3. 报告输出 — Markdown + JSON
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ─── 路径 ───────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ────────────────────────────────────────────────────────
#  数据加载
# ────────────────────────────────────────────────────────


@dataclass
class StockSample:
    symbol: str
    name: str
    board: str  # "SH_Main" | "GEM" | "STAR"
    df: pd.DataFrame  # OHLCV data
    years: float  # data span in years


def load_golden_list(path: Path) -> List[str]:
    symbols = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sym = line.split("#")[0].split()[0].strip()
        if sym:
            symbols.append(sym)
    return symbols


def load_golden_100() -> List[str]:
    return load_golden_list(PROJECT_ROOT / "tests/benchmark/golden_100.txt")


def load_golden_20() -> List[str]:
    return load_golden_list(PROJECT_ROOT / "tests/benchmark/golden_20.txt")


def load_stock_data(symbol: str) -> Optional[pd.DataFrame]:
    path = PROJECT_ROOT / f"data/lake/quotes/daily/{symbol}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def get_stock_metadata() -> Dict[str, str]:
    """Return {symbol: board_type} mapping from qualified_universe.csv"""
    path = PROJECT_ROOT / "data/qualified_universe.csv"
    if not path.exists():
        return {}
    meta = {}
    import csv
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get("symbol", "")
            board = row.get("board", "SH_Main")
            if sym:
                meta[sym] = board
    return meta


def prepare_samples(symbols: List[str], start: str = "2022-01-01") -> List[StockSample]:
    meta = get_stock_metadata()
    samples = []
    for sym in symbols:
        df = load_stock_data(sym)
        if df is None or len(df) < 120:
            continue
        df = df[df["date"] >= start].copy().reset_index(drop=True)
        if len(df) < 120:
            continue
        years = (df["date"].max() - df["date"].min()).days / 365.25
        board = meta.get(sym, "SH_Main")
        samples.append(StockSample(
            symbol=sym,
            name=board,
            board=board,
            df=df,
            years=years,
        ))
    return samples


# ────────────────────────────────────────────────────────
#  LPPL 诊断
# ────────────────────────────────────────────────────────


@dataclass
class LpplFitRecord:
    symbol: str
    window: int
    date_idx: int
    date: str
    optimizer: str  # "de" | "lbfgsb"
    success: bool
    r_squared: float
    rmse: float
    m: float
    w: float
    days_to_crash: float
    tc: float
    a: float
    b: float
    c: float
    phi: float
    sornette_valid: bool
    n_data: int
    elapsed_ms: float
    error: str = ""


@dataclass
class LpplDiagnostics:
    """Aggregated LPPL diagnostics across all stocks"""
    # H1: DE timeout rate
    de_total: int = 0
    de_success: int = 0
    de_timeout: int = 0
    lbfgsb_total: int = 0
    lbfgsb_success: int = 0

    # H2: Sornette constraint pass rate
    sornette_valid_count: int = 0
    sornette_invalid_count: int = 0
    m_values: List[float] = field(default_factory=list)
    w_values: List[float] = field(default_factory=list)

    # H3: R² comparison (engine.py vs calculator.py)
    r2_engine: List[float] = field(default_factory=list)
    r2_calculator: List[float] = field(default_factory=list)

    # H4: confidence vs days_to_tc
    confidence_values: List[float] = field(default_factory=list)
    days_to_tc_values: List[float] = field(default_factory=list)
    rmse_values: List[float] = field(default_factory=list)

    # H5: AIC/BIC
    aic_values: List[float] = field(default_factory=list)
    bic_values: List[float] = field(default_factory=list)
    n_data_values: List[int] = field(default_factory=list)

    # H6: false positive in range-bound markets
    fp_danger_in_ranging: int = 0
    fp_total_ranging_windows: int = 0

    # all records
    records: List[LpplFitRecord] = field(default_factory=list)

    # cache collision
    cache_hit_64: int = 0
    cache_hit_32: int = 0


def compute_aic_bic(rmse: float, n_data: int, n_params: int = 7) -> Tuple[float, float]:
    """Compute AIC and BIC from RMSE"""
    if n_data <= n_params or rmse <= 0:
        return 999999.0, 999999.0
    ll = -n_data * math.log(rmse) - 0.5 * n_data * math.log(2 * math.pi) - 0.5 * n_data
    aic = -2 * ll + 2 * n_params
    bic = -2 * ll + n_params * math.log(n_data)
    return aic, bic


def run_lppl_diagnostics(
    samples: List[StockSample],
    windows: List[int] = None,
    max_stocks: int = 100,
) -> LpplDiagnostics:
    """Run LPPL diagnostic tests across all stocks"""
    if windows is None:
        windows = [40, 60, 80]

    from uniquant.brain.lppl.engine import (
        LPPLEngine,
        LPPLConfig,
        fit_single_window as de_fit,
        fit_single_window_lbfgsb,
    )
    from uniquant.brain.lppl.calculator import LPPLCalculator

    diag = LpplDiagnostics()
    calculator = LPPLCalculator()
    total = min(len(samples), max_stocks)

    for si, sample in enumerate(samples):
        if si >= max_stocks:
            break
        sym = sample.symbol
        close = sample.df["close"].values
        dates = sample.df["date"].values
        n = len(close)

        print(f"[{si+1}/{total}] LPPL diagnostics: {sym}  ({n} bars)")

        # H6: detect range-bound periods
        ranging_windows = _detect_ranging_periods(close, dates, window=60)

        # Run fits at semi-annual intervals (reduce from 40 to ~8 per stock)
        step = max(1, n // 15)
        for idx in range(max(windows), n, step):
            current_date = str(pd.Timestamp(dates[idx]).date())

            # Only L-BFGS-B on the hot path (fast)
            config = LPPLConfig(
                window_range=windows,
                optimizer="lbfgsb",
                maxiter=30,
                popsize=5,
                tol=0.05,
                n_workers=1,
            )
            t0 = time.perf_counter()
            try:
                lbfgsb_result = fit_single_window_lbfgsb(close, windows[-1], config)
            except Exception as e:
                lbfgsb_result = None
            elapsed_lbfgsb = (time.perf_counter() - t0) * 1000
            diag.lbfgsb_total += 1
            if lbfgsb_result is not None:
                diag.lbfgsb_success += 1

            # DE only every 5th window for timeout comparison
            de_result = None
            if idx % (step * 5) == 0:
                config_de = LPPLConfig(
                    window_range=windows,
                    optimizer="de",
                    maxiter=50,
                    popsize=10,
                    tol=0.05,
                    n_workers=1,
                )
                t0 = time.perf_counter()
                try:
                    de_result = de_fit(close, windows[-1], config_de)
                except Exception:
                    de_result = None
                elapsed_de = (time.perf_counter() - t0) * 1000
                diag.de_total += 1
                if de_result is not None:
                    diag.de_success += 1
                else:
                    diag.de_timeout += 1

            # Use L-BFGS-B result for diagnostics (faster)
            result = lbfgsb_result

            if result is not None:
                m_val = result.get("m", 0)
                w_val = result.get("w", 0)
                r2 = result.get("r_squared", 0)
                diag.m_values.append(m_val)
                diag.w_values.append(w_val)

                # H2: Sornette constraint
                params_tuple = result.get("params")
                b_val = params_tuple[4] if params_tuple and len(params_tuple) >= 6 else 0
                c_val = abs(params_tuple[5]) if params_tuple and len(params_tuple) >= 6 else 0
                sornette_ok = (0.1 < m_val < 0.9) and (6 < w_val < 13) and b_val < 0 and c_val > 0.01
                if sornette_ok:
                    diag.sornette_valid_count += 1
                else:
                    diag.sornette_invalid_count += 1

                # H6: false positive in ranging
                if result.get("is_danger", False):
                    for rw_start, rw_end in ranging_windows:
                        if rw_start <= idx <= rw_end:
                            diag.fp_danger_in_ranging += 1
                            break

                # H5: AIC/BIC
                n_data = windows[-1]
                aic, bic = compute_aic_bic(result.get("rmse", 1.0), n_data, 7)
                diag.aic_values.append(aic)
                diag.bic_values.append(bic)
                diag.n_data_values.append(n_data)
                diag.days_to_tc_values.append(result.get("days_to_crash", 999))
                diag.rmse_values.append(result.get("rmse", 1.0))

                rec = LpplFitRecord(
                    symbol=sym, window=windows[-1], date_idx=idx,
                    date=current_date, optimizer="lbfgsb", success=True,
                    r_squared=r2, rmse=result.get("rmse", 0),
                    m=m_val, w=w_val,
                    days_to_crash=result.get("days_to_crash", 999),
                    tc=result.get("tc", 0),
                    a=params_tuple[3] if params_tuple and len(params_tuple) >= 4 else 0,
                    b=b_val,
                    c=result.get("params", [0]*7)[5] if result.get("params") else 0,
                    phi=result.get("params", [0]*7)[6] if result.get("params") else 0,
                    sornette_valid=sornette_ok,
                    n_data=n_data,
                    elapsed_ms=round(elapsed_lbfgsb, 1),
                )
                diag.records.append(rec)
            else:
                diag.de_timeout += 1

            # L-BFGS-B
            if lbfgsb_result is not None:
                diag.lbfgsb_success += 1
                m_val = lbfgsb_result.get("m", 0)
                w_val = lbfgsb_result.get("w", 0)
                diag.m_values.append(m_val)
                diag.w_values.append(w_val)
            diag.lbfgsb_total += 1
            diag.de_total += 1

        # H3: R² comparison (engine.py vs calculator.py) on last window
        if len(close) >= max(windows):
            subset = close[-max(windows):]
            # calculator fit
            try:
                calc_result = calculator.fit_single_window(subset)
                if calc_result:
                    calc_r2 = _calc_r2_from_calculator(subset, calc_result)
                    # engine fit
                    de_r2 = 0
                    eng_result = de_fit(close, max(windows), config)
                    if eng_result:
                        de_r2 = eng_result.get("r_squared", 0)
                    diag.r2_engine.append(de_r2)
                    diag.r2_calculator.append(calc_r2)
            except Exception:
                pass

        # H4: confidence formula via calculator
        if len(close) >= max(windows):
            # Use calculator's own confidence output
            try:
                bubble_result = LPPLEngine().detect_bubble(sample.df)
                diag.confidence_values.append(bubble_result.get("confidence", 0))
            except Exception:
                pass

    # H6 final
    for rw_start, rw_end in ranging_windows:
        diag.fp_total_ranging_windows += 1

    # cache collision test (H1b)
    try:
        raw64 = np.random.randn(60).astype(np.float64)
        raw32 = raw64.astype(np.float32)
        res64 = calculator.fit_single_window(raw64)
        res32 = calculator.fit_single_window(raw32)
        if res64 and res32:
            diag.cache_hit_64 = 1 if res64 else 0
            diag.cache_hit_32 = 1 if res32 else 0
    except Exception:
        pass

    return diag


def _detect_ranging_periods(
    close: np.ndarray, dates: np.ndarray, window: int = 60
) -> List[Tuple[int, int]]:
    """Detect range-bound (sideways) market periods"""
    periods = []
    for i in range(0, len(close) - window, window // 2):
        segment = close[i:i + window]
        ret = (segment[-1] - segment[0]) / segment[0]
        if abs(ret) < 0.10:
            periods.append((i, i + window))
    return periods


def _calc_r2_from_calculator(close: np.ndarray, result: Dict) -> float:
    """Compute R² from calculator fit result (which doesn't output R² directly)"""
    from uniquant.brain.lppl.calculator import lppl_func
    params = result.get("params")
    if not params or len(params) < 7:
        return 0.0
    t = np.arange(len(close))
    log_p = np.log(close)
    fitted = lppl_func(t, *params)
    ss_res = np.sum((log_p - fitted) ** 2)
    ss_tot = np.sum((log_p - np.mean(log_p)) ** 2)
    return 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0


# ────────────────────────────────────────────────────────
#  Wyckoff 诊断
# ────────────────────────────────────────────────────────


@dataclass
class WyckoffDiagRecord:
    symbol: str
    date: str
    phase: str
    sub_phase: str
    confidence_level: str  # A/B/C/D
    position_size: str
    direction: str
    spring_detected: bool
    spring_quality: str
    lps_confirmed: bool
    t1_verdict: str
    t1_pct: float
    rr_ratio: float
    rr_verdict: str
    pro_score: float
    con_score: float
    cf_overturned: bool
    bc_found: bool
    contradictions: int
    signal_type: str
    limit_down_near_stop: bool


@dataclass
class WyckoffDiagnostics:
    records: List[WyckoffDiagRecord] = field(default_factory=list)

    # H7: threshold sensitivity
    base_phase: List[str] = field(default_factory=list)
    perturbed_phase: List[str] = field(default_factory=list)

    # H8: confidence distribution
    conf_a: int = 0
    conf_b: int = 0
    conf_c: int = 0
    conf_d: int = 0
    conf_bypass_count: int = 0

    # H9: counterfactual
    pro_scores: List[float] = field(default_factory=list)
    con_scores: List[float] = field(default_factory=list)
    overturned_count: int = 0
    degraded_count: int = 0

    # H10: T+1 by board (新ATR阈值)
    t1_by_board: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    # H10: T+1 by board (旧固定阈值 3%/5%)
    t1_by_board_old: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    # H10: per-stock diff records (old vs new verdict differ)
    h10_diff_records: List[Dict[str, Any]] = field(default_factory=list)

    # Phase distribution
    phase_dist: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Spring → Markup delay
    spring_to_markup_delays: List[int] = field(default_factory=list)

    # Second bypass path: RR≥2.5 but no BC
    conf_bypass_path2_count: int = 0

    # P6.6: Bypass vs full R8 comparison
    conf_bypass_vs_full_r8: List[Dict[str, Any]] = field(default_factory=list)


def run_wyckoff_diagnostics(
    samples: List[StockSample],
    max_stocks: int = 100,
    run_threshold_sensitivity: bool = True,
) -> WyckoffDiagnostics:
    """Run Wyckoff diagnostic tests across all stocks"""
    from uniquant.brain.wyckoff.engine import WyckoffEngine
    from uniquant.brain.wyckoff.models import (
        WyckoffPhase, ConfidenceLevel
    )

    diag = WyckoffDiagnostics()
    total = min(len(samples), max_stocks)

    for si, sample in enumerate(samples):
        if si >= max_stocks:
            break
        sym = sample.symbol
        df = sample.df
        board = sample.board

        print(f"[{si+1}/{total}] Wyckoff diagnostics: {sym}  ({board})")

        try:
            engine = WyckoffEngine(lookback_days=120)
            engine._debug_r8_compare = True
            result = engine.analyze(df.copy(), symbol=sym, period="日线")
        except Exception as e:
            print(f"  Wyckoff engine failed for {sym}: {e}")
            continue

        phase = result.structure.phase.value if result.structure else "unknown"
        signal = result.signal
        plan = result.trading_plan
        rr_rr = result.risk_reward.reward_risk_ratio if result.risk_reward else 0
        t1_desc = signal.t1_risk评估 if signal else ""

        conf_level = signal.confidence.value if signal and signal.confidence else "D"
        direction = plan.direction if plan else "空仓观望"

        # Spring detection from signal
        spring_detected = (signal.signal_type or "").lower() == "spring" if signal else False
        spring_quality = signal.description if spring_detected else ""
        lps_confirmed = "LPS已确认" in (signal.description if signal else "")

        # T+1
        t1_verdict = "未知"
        t1_pct = 0.0
        if step3 := getattr(engine, "_last_step3", None):
            t1_verdict = getattr(step3, "t1_verdict", "未知")
            t1_pct = getattr(step3, "t1_max_drawdown_pct", 0.0)
        # Try from engine internal state
        try:
            frame = engine._normalize_input_frame(df).tail(120).reset_index(drop=True)
            rule0 = engine._step0_bc_tr_scan(frame)
            step1 = engine._step1_phase_determine(frame, rule0)
            step3 = engine._step3_phase_c_t1(frame, step1, rule0)
            t1_verdict = step3.t1_verdict
            t1_pct = step3.t1_max_drawdown_pct
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            print(f"  ⚠ Wyckoff step3 re-run failed for {sym}: {e}")

        # Counterfactual info
        pro_score = 0.0
        con_score = 0.0
        cf_overturned = False
        try:
            step2 = engine._step2_effort_result(frame, step1)
            step35 = engine._step35_counterfactual(frame, step1, step2, step3, rule0)
            pro_score = step35.total_pro_score
            con_score = step35.total_con_score
            cf_overturned = step35.conclusion_overturned
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            print(f"  ⚠ Wyckoff counterfactual failed for {sym}: {e}")

        # Phase distribution
        diag.phase_dist[phase] += 1

        # H8: confidence
        if conf_level == "A":
            diag.conf_a += 1
        elif conf_level == "B":
            diag.conf_b += 1
        elif conf_level == "C":
            diag.conf_c += 1
        else:
            diag.conf_d += 1

        # Check for bypass: spring but no LPS → C direct
        if spring_detected and not lps_confirmed:
            diag.conf_bypass_count += 1

        # H9: counterfactual
        diag.pro_scores.append(pro_score)
        diag.con_scores.append(con_score)
        if cf_overturned:
            diag.overturned_count += 1

        # H10: T+1 by board (新ATR阈值)
        diag.t1_by_board[board][t1_verdict] += 1

        # H10: T+1 by board (旧固定阈值 3%/5% 对比)
        if t1_pct < 3.0:
            old_verdict = "安全"
        elif t1_pct < 5.0:
            old_verdict = "偏薄"
        else:
            old_verdict = "超限"
        diag.t1_by_board_old[board][old_verdict] += 1

        # H10: per-stock diff record when old vs new verdict differs
        if t1_verdict != old_verdict:
            diag.h10_diff_records.append({
                "symbol": sym, "board": board,
                "new_verdict": t1_verdict, "old_verdict": old_verdict,
                "t1_pct": round(t1_pct, 2),
            })

        # Path2 bypass: RR≥2.5 but no BC
        if rr_rr >= 2.5 and not rule0.bc_found:
            diag.conf_bypass_path2_count += 1

        # P6.6: Bypass vs full R8 comparison
        if engine._debug_r8_bypass_result is not None and engine._debug_r8_full_result is not None:
            diag.conf_bypass_vs_full_r8.append({
                "symbol": sym,
                "bypass_level": engine._debug_r8_bypass_result.level,
                "bypass_reason": engine._debug_r8_bypass_result.reason,
                "full_r8_level": engine._debug_r8_full_result.level,
                "full_r8_reason": engine._debug_r8_full_result.reason,
                "diverges": engine._debug_r8_bypass_result.level != engine._debug_r8_full_result.level,
            })
        # Reset debug results for next stock
        engine._debug_r8_bypass_result = None
        engine._debug_r8_full_result = None

        # Record
        rec = WyckoffDiagRecord(
            symbol=sym,
            date=str(df["date"].iloc[-1].date()),
            phase=phase,
            sub_phase="",
            confidence_level=conf_level,
            position_size=plan.position_size if hasattr(plan, "position_size") else "",
            direction=direction,
            spring_detected=spring_detected,
            spring_quality=spring_quality,
            lps_confirmed=lps_confirmed,
            t1_verdict=t1_verdict,
            t1_pct=t1_pct,
            rr_ratio=rr_rr,
            rr_verdict=getattr(result.risk_reward, "rr_verdict", "") if result.risk_reward else "",
            pro_score=pro_score,
            con_score=con_score,
            cf_overturned=cf_overturned,
            bc_found=rule0.bc_found if hasattr(rule0, "bc_found") else False,
            contradictions=0,
            signal_type=signal.signal_type if signal else "no_signal",
            limit_down_near_stop=False,
        )
        diag.records.append(rec)

    return diag


# ────────────────────────────────────────────────────────
#  交叉验证
# ────────────────────────────────────────────────────────


@dataclass
class CrossDiagRecord:
    symbol: str
    date: str
    lppl_risk: str
    lppl_confidence: float
    wyckoff_phase: str
    wyckoff_signal: str
    wyckoff_direction: str
    wyckoff_confidence: str
    conflict: bool  # LPPL Danger & Wyckoff BUY


@dataclass
class CrossDiagnostics:
    records: List[CrossDiagRecord] = field(default_factory=list)
    conflict_count: int = 0
    total_aligned: int = 0
    # H12: Spring → Markup timeline
    spring_dates: Dict[str, str] = field(default_factory=dict)
    markup_dates: Dict[str, str] = field(default_factory=dict)
    spring_markup_delays: List[int] = field(default_factory=list)


def run_cross_diagnostics(
    samples: List[StockSample],
    lppl_diag: LpplDiagnostics,
    wyckoff_diag: WyckoffDiagnostics,
    max_stocks: int = 100,
) -> CrossDiagnostics:
    """Cross-engine validation"""
    from uniquant.brain.lppl.engine import LPPLEngine
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    xdiag = CrossDiagnostics()
    total = min(len(samples), max_stocks)

    # Build a lookup of Wyckoff records by symbol
    wyc_by_sym = defaultdict(list)
    for rec in wyckoff_diag.records:
        wyc_by_sym[rec.symbol].append(rec)

    for si, sample in enumerate(samples):
        if si >= max_stocks:
            break
        sym = sample.symbol
        df = sample.df
        print(f"[{si+1}/{total}] Cross-validation: {sym}")

        # Run LPPL on recent 200 days
        recent = df.tail(200).copy()
        if len(recent) < 100:
            continue

        try:
            engine = LPPLEngine()
            lppl_result = engine.detect_bubble(recent)
            lppl_risk = lppl_result.get("risk_level", "Safe")
            lppl_conf = lppl_result.get("confidence", 0.0)
        except Exception:
            lppl_risk = "Safe"
            lppl_conf = 0.0

        # Latest Wyckoff record
        wyc_records = wyc_by_sym.get(sym, [])
        latest_wyc = wyc_records[-1] if wyc_records else None

        if latest_wyc is None:
            continue

        wyc_phase = latest_wyc.phase
        wyc_signal = latest_wyc.signal_type
        wyc_dir = latest_wyc.direction
        wyc_conf = latest_wyc.confidence_level

        # H11: Conflict detection
        conflict = (lppl_risk == "Danger" and "做多" in wyc_dir)
        if conflict:
            xdiag.conflict_count += 1
        xdiag.total_aligned += 1

        rec = CrossDiagRecord(
            symbol=sym,
            date=str(df["date"].iloc[-1].date()),
            lppl_risk=lppl_risk,
            lppl_confidence=lppl_conf,
            wyckoff_phase=wyc_phase,
            wyckoff_signal=wyc_signal,
            wyckoff_direction=wyc_dir,
            wyckoff_confidence=wyc_conf,
            conflict=conflict,
        )
        xdiag.records.append(rec)

        # H12: Spring → Markup timeline
        # Scan historical records for spring events followed by markup
        for i in range(len(wyc_records) - 1):
            if wyc_records[i].spring_detected:
                spring_date = wyc_records[i].date
                # Look ahead for markup
                for j in range(i + 1, min(i + 60, len(wyc_records))):
                    if wyc_records[j].phase == "markup":
                        delay = (pd.Timestamp(wyc_records[j].date) -
                                 pd.Timestamp(spring_date)).days
                        if 0 < delay <= 120:
                            xdiag.spring_markup_delays.append(delay)
                        break

    return xdiag


# ────────────────────────────────────────────────────────
#  报告生成
# ────────────────────────────────────────────────────────


def make_lppl_report(diag: LpplDiagnostics) -> Dict[str, Any]:
    de_success_rate = diag.de_success / max(diag.de_total, 1)
    sornette_pass_rate = diag.sornette_valid_count / max(
        diag.sornette_valid_count + diag.sornette_invalid_count, 1
    )
    fp_rate = diag.fp_danger_in_ranging / max(diag.fp_total_ranging_windows, 1)

    m_arr = np.array(diag.m_values)
    w_arr = np.array(diag.w_values)

    r2_diff = []
    for e, c in zip(diag.r2_engine, diag.r2_calculator):
        r2_diff.append(abs(e - c))
    mean_r2_diff = np.mean(r2_diff) if r2_diff else 0

    # Confidence vs days_to_tc correlation (only if same length)
    conf_days_corr = 0.0
    min_len = min(len(diag.days_to_tc_values), len(diag.confidence_values))
    if min_len >= 5:
        d = diag.days_to_tc_values[:min_len]
        c = diag.confidence_values[:min_len]
        if np.std(d) > 0 and np.std(c) > 0:
            corr = np.corrcoef(d, c)
            conf_days_corr = corr[0, 1] if len(corr) > 1 else 0

    # AIC/BIC stats
    aic_arr = np.array(diag.aic_values)
    bic_arr = np.array(diag.bic_values)
    param_ratio = np.array(diag.n_data_values) / 7.0 if diag.n_data_values else np.array([])
    overfit_count = int(np.sum(param_ratio < 10)) if len(param_ratio) > 0 else 0
    overfit_rate = overfit_count / max(len(param_ratio), 1)

    return {
        "h1_de_timeout": {
            "hypothesis": "DE超时无降级导致分析空白",
            "de_total": diag.de_total,
            "de_success": diag.de_success,
            "de_success_rate": round(de_success_rate, 4),
            "lbfgsb_total": diag.lbfgsb_total,
            "lbfgsb_success": diag.lbfgsb_success,
            "lbfgsb_success_rate": round(
                diag.lbfgsb_success / max(diag.lbfgsb_total, 1), 4
            ),
            "verdict": "CONFIRMED" if (1 - de_success_rate) > 0.15 else "NOT_CONFIRMED",
        },
        "h2_sornette_constraints": {
            "hypothesis": "Sornette约束(0.1<m<0.9,6<w<13)过于宽松",
            "valid_count": diag.sornette_valid_count,
            "invalid_count": diag.sornette_invalid_count,
            "pass_rate": round(sornette_pass_rate, 4),
            "m_mean": round(float(np.mean(m_arr)), 4) if len(m_arr) > 0 else 0,
            "m_std": round(float(np.std(m_arr)), 4) if len(m_arr) > 0 else 0,
            "m_p5": round(float(np.percentile(m_arr, 5)), 4) if len(m_arr) > 0 else 0,
            "m_p95": round(float(np.percentile(m_arr, 95)), 4) if len(m_arr) > 0 else 0,
            "w_mean": round(float(np.mean(w_arr)), 4) if len(w_arr) > 0 else 0,
            "w_std": round(float(np.std(w_arr)), 4) if len(w_arr) > 0 else 0,
            "verdict": "CONFIRMED" if sornette_pass_rate > 0.95 else "NOT_CONFIRMED",
        },
        "h3_r2_inconsistency": {
            "hypothesis": "engine.py与calculator.py的R²计算口径不一致",
            "n_comparisons": len(r2_diff),
            "mean_r2_diff": round(mean_r2_diff, 4),
            "max_r2_diff": round(float(np.max(r2_diff)), 4) if r2_diff else 0,
            "verdict": "CONFIRMED" if mean_r2_diff > 0.05 else "NOT_CONFIRMED",
        },
        "h4_confidence_circular": {
            "hypothesis": "置信度公式中days_to_tc自引用导致循环论证",
            "n_samples": min(len(diag.confidence_values), len(diag.days_to_tc_values)),
            "conf_days_corr": round(float(conf_days_corr), 4),
            "verdict": "CONFIRMED" if abs(conf_days_corr) > 0.5 else "NOT_CONFIRMED",
        },
        "h5_no_overfitting_check": {
            "hypothesis": "无过拟合检测(AIC/BIC),参数/数据比过低",
            "n_fits": len(diag.aic_values),
            "aic_mean": round(float(np.mean(aic_arr)), 2) if len(aic_arr) > 0 else 0,
            "bic_mean": round(float(np.mean(bic_arr)), 2) if len(bic_arr) > 0 else 0,
            "overfit_count": overfit_count,
            "overfit_rate": round(float(overfit_rate), 4),
            "verdict": "CONFIRMED" if overfit_rate > 0.30 else "NOT_CONFIRMED",
        },
        "h6_false_positive": {
            "hypothesis": "假阳性率偏高(震荡市误报)",
            "fp_danger_in_ranging": diag.fp_danger_in_ranging,
            "fp_total_ranging_windows": diag.fp_total_ranging_windows,
            "fp_rate": round(fp_rate, 4),
            "verdict": "CONFIRMED" if fp_rate > 0.20 else "NOT_CONFIRMED",
        },
        "cache_collision": {
            "cache_hit_64": diag.cache_hit_64,
            "cache_hit_32": diag.cache_hit_32,
        },
        "m_distribution": {
            "p5": round(float(np.percentile(m_arr, 5)), 4) if len(m_arr) > 0 else 0,
            "p25": round(float(np.percentile(m_arr, 25)), 4) if len(m_arr) > 0 else 0,
            "p50": round(float(np.percentile(m_arr, 50)), 4) if len(m_arr) > 0 else 0,
            "p75": round(float(np.percentile(m_arr, 75)), 4) if len(m_arr) > 0 else 0,
            "p95": round(float(np.percentile(m_arr, 95)), 4) if len(m_arr) > 0 else 0,
        },
        "w_distribution": {
            "p5": round(float(np.percentile(w_arr, 5)), 4) if len(w_arr) > 0 else 0,
            "p25": round(float(np.percentile(w_arr, 25)), 4) if len(w_arr) > 0 else 0,
            "p50": round(float(np.percentile(w_arr, 50)), 4) if len(w_arr) > 0 else 0,
            "p75": round(float(np.percentile(w_arr, 75)), 4) if len(w_arr) > 0 else 0,
            "p95": round(float(np.percentile(w_arr, 95)), 4) if len(w_arr) > 0 else 0,
        },
    }


def make_wyckoff_report(diag: WyckoffDiagnostics) -> Dict[str, Any]:
    n = len(diag.records)
    overturned_rate = diag.overturned_count / max(n, 1)
    bypass_rate = diag.conf_bypass_count / max(diag.conf_c + diag.conf_bypass_count, 1)

    pro_arr = np.array(diag.pro_scores)
    con_arr = np.array(diag.con_scores)
    pro_con_ratio = np.mean(pro_arr / (con_arr + 1e-6))

    return {
        "h7_threshold_sensitivity": {
            "hypothesis": "Step1阈值过度工程化(15+分支,精度到小数点后4位)",
            "note": "需要运行perturbation analysis确认翻转率",
            "n_phases": len(set(diag.phase_dist.keys())),
            "phase_distribution": dict(diag.phase_dist),
            "verdict": "NEEDS_INVESTIGATION",
        },
        "h8_confidence_matrix": {
            "hypothesis": "置信度矩阵R8实际有效条件不足",
            "n_total": n,
            "conf_A": diag.conf_a,
            "conf_B": diag.conf_b,
            "conf_C": diag.conf_c,
            "conf_D": diag.conf_d,
            "conf_A_pct": round(diag.conf_a / max(n, 1), 4),
            "conf_B_pct": round(diag.conf_b / max(n, 1), 4),
            "conf_C_pct": round(diag.conf_c / max(n, 1), 4),
            "conf_D_pct": round(diag.conf_d / max(n, 1), 4),
            "bypass_count": diag.conf_bypass_count,
            "bypass_path1_count": diag.conf_bypass_count,
            "bypass_path2_count": diag.conf_bypass_path2_count,
            "bypass_rate": round(bypass_rate, 4),
            "verdict": "CONFIRMED" if (diag.conf_a + diag.conf_b) / max(n, 1) < 0.05 or bypass_rate > 0.20 else "NOT_CONFIRMED",
        },
        "h9_counterfactual_weight": {
            "hypothesis": "反事实评分权重随意(固定2.0/项)",
            "n_observations": n,
            "pro_mean": round(float(np.mean(pro_arr)), 2) if len(pro_arr) > 0 else 0,
            "con_mean": round(float(np.mean(con_arr)), 2) if len(con_arr) > 0 else 0,
            "pro_con_ratio": round(float(pro_con_ratio), 2),
            "overturned_count": diag.overturned_count,
            "degraded_count": diag.degraded_count,
            "overturned_rate": round(float(overturned_rate), 4),
            "verdict": "CONFIRMED" if overturned_rate < 0.05 else "NOT_CONFIRMED",
        },
        "r8_bypass_verification": {
            "hypothesis": "Bypass路径的 C 级与 full R8 矩阵结果一致",
            "n_bypass_triggers": len(diag.conf_bypass_vs_full_r8),
            "n_diverges": sum(1 for r in diag.conf_bypass_vs_full_r8 if r.get("diverges")),
            "divergence_rate": round(
                sum(1 for r in diag.conf_bypass_vs_full_r8 if r.get("diverges"))
                / max(len(diag.conf_bypass_vs_full_r8), 1), 4
            ),
            "detail_records": diag.conf_bypass_vs_full_r8[:30],
            "verdict": "CONFIRMED"
            if sum(1 for r in diag.conf_bypass_vs_full_r8 if r.get("diverges")) == 0
            else "NOT_CONFIRMED",
        },
        "h10_t1_aggressive": {
            "hypothesis": "T+1 3%止损宽度对高波动股票过于激进",
            "t1_by_board": {k: dict(v) for k, v in diag.t1_by_board.items()},
            "t1_by_board_old_3pct": {k: dict(v) for k, v in diag.t1_by_board_old.items()},
            "diff_count": len(diag.h10_diff_records),
            "diff_records": diag.h10_diff_records[:20],
            "verdict": "NEEDS_INVESTIGATION",
        },
    }


def make_cross_report(xdiag: CrossDiagnostics) -> Dict[str, Any]:
    conflict_rate = xdiag.conflict_count / max(xdiag.total_aligned, 1)
    delay_arr = np.array(xdiag.spring_markup_delays)

    return {
        "h11_lppl_wyckoff_conflict": {
            "hypothesis": "LPPL Danger信号与Wyckoff BUY信号高冲突",
            "total_aligned": xdiag.total_aligned,
            "conflict_count": xdiag.conflict_count,
            "conflict_rate": round(conflict_rate, 4),
            "verdict": "CONFIRMED" if conflict_rate > 0.15 else "NOT_CONFIRMED",
        },
        "h12_spring_markup_delay": {
            "hypothesis": "Wyckoff Spring→Markup信号转换延迟错过最佳买点",
            "n_events": len(xdiag.spring_markup_delays),
            "delay_mean": round(float(np.mean(delay_arr)), 1) if len(delay_arr) > 0 else 0,
            "delay_median": round(float(np.median(delay_arr)), 1) if len(delay_arr) > 0 else 0,
            "delay_p25": round(float(np.percentile(delay_arr, 25)), 1) if len(delay_arr) > 0 else 0,
            "delay_p75": round(float(np.percentile(delay_arr, 75)), 1) if len(delay_arr) > 0 else 0,
            "verdict": "CONFIRMED" if (len(delay_arr) > 0 and np.median(delay_arr) > 5) else ("NOT_TESTED" if len(delay_arr) == 0 else "NOT_CONFIRMED"),
        },
    }


def generate_report(
    lppl_diag: LpplDiagnostics,
    wyckoff_diag: WyckoffDiagnostics,
    xdiag: CrossDiagnostics,
    elapsed: float,
    n_stocks: int,
) -> str:
    lppl_report = make_lppl_report(lppl_diag)
    wyckoff_report = make_wyckoff_report(wyckoff_diag)
    cross_report = make_cross_report(xdiag)

    lines = []
    lines.append("# LPPL × Wyckoff 交叉验证报告")
    lines.append(f"\n运行时间: {datetime.now().isoformat()}")
    lines.append(f"样本数: {n_stocks} 只股票")
    lines.append(f"耗时: {elapsed:.1f} 秒")
    lines.append(f"\n## 总体结论")
    lines.append("")

    verdict_map = {"CONFIRMED": "✅ 确认", "NOT_CONFIRMED": "❌ 未确认", "NEEDS_INVESTIGATION": "⚠️ 待深入"}
    confirmed = 0
    total = 0
    all_reports = [
        ("H1", lppl_report["h1_de_timeout"]),
        ("H2", lppl_report["h2_sornette_constraints"]),
        ("H3", lppl_report["h3_r2_inconsistency"]),
        ("H4", lppl_report["h4_confidence_circular"]),
        ("H5", lppl_report["h5_no_overfitting_check"]),
        ("H6", lppl_report["h6_false_positive"]),
        ("H7", wyckoff_report["h7_threshold_sensitivity"]),
        ("H8", wyckoff_report["h8_confidence_matrix"]),
        ("H9", wyckoff_report["h9_counterfactual_weight"]),
        ("H10", wyckoff_report["h10_t1_aggressive"]),
        ("H11", cross_report["h11_lppl_wyckoff_conflict"]),
        ("H12", cross_report["h12_spring_markup_delay"]),
        ("R8", wyckoff_report["r8_bypass_verification"]),
    ]

    for hid, rep in all_reports:
        v = rep.get("verdict", "UNKNOWN")
        lines.append(f"| {hid} | {rep.get('hypothesis', '')[:50]}... | {verdict_map.get(v, v)} |")
        if v == "CONFIRMED":
            confirmed += 1
        total += 1
    lines.append(f"\n确认率: {confirmed}/{total}")

    # ─── LPPL 细节 ───
    lines.append(f"\n---\n## LPPL 引擎诊断")
    for hid, rep in all_reports[:6]:
        lines.append(f"\n### {hid}: {rep.get('hypothesis', '')}")
        for k, v in rep.items():
            if k not in ("hypothesis", "verdict"):
                lines.append(f"- {k}: {v}")
        lines.append(f"- **判定**: {verdict_map.get(rep.get('verdict', ''), rep.get('verdict', ''))}")

    # ─── Wyckoff 细节 ───
    lines.append(f"\n---\n## Wyckoff 引擎诊断")
    for hid, rep in all_reports[6:10]:
        lines.append(f"\n### {hid}: {rep.get('hypothesis', '')}")
        for k, v in rep.items():
            if k not in ("hypothesis", "verdict"):
                lines.append(f"- {k}: {v}")
        lines.append(f"- **判定**: {verdict_map.get(rep.get('verdict', ''), rep.get('verdict', ''))}")

    # H10 diff table
    h10r = wyckoff_report["h10_t1_aggressive"]
    diff_count = h10r.get("diff_count", 0)
    if diff_count > 0:
        lines.append(f"\n### H10 分歧明细 (ATR新阈值 vs 固定3%/5%旧阈值, 共{diff_count}条)")
        lines.append("| 股票 | 板块 | ATR新判定 | 旧判定(3%/5%) | T+1回撤% |")
        lines.append("|------|------|----------|---------------|---------|")
        for rec in h10r.get("diff_records", []):
            lines.append(f"| {rec['symbol']} | {rec['board']} | {rec['new_verdict']} | {rec['old_verdict']} | {rec['t1_pct']}% |")

    # ─── Cross 细节 ───
    lines.append(f"\n---\n## 交叉验证")
    for hid, rep in all_reports[10:]:
        lines.append(f"\n### {hid}: {rep.get('hypothesis', '')}")
        for k, v in rep.items():
            if k not in ("hypothesis", "verdict"):
                lines.append(f"- {k}: {v}")
        lines.append(f"- **判定**: {verdict_map.get(rep.get('verdict', ''), rep.get('verdict', ''))}")

    # ─── 参数分布图表 ───
    lines.append(f"\n---\n## LPPL 参数分布")
    lines.append(f"\n### m 参数五分位")
    md = lppl_report["m_distribution"]
    for k, v in md.items():
        lines.append(f"- {k}: {v}")
    lines.append(f"\n### w 参数五分位")
    wd = lppl_report["w_distribution"]
    for k, v in wd.items():
        lines.append(f"- {k}: {v}")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────
#  JSON 输出
# ────────────────────────────────────────────────────────


def dump_json(
    lppl_diag: LpplDiagnostics,
    wyckoff_diag: WyckoffDiagnostics,
    xdiag: CrossDiagnostics,
    elapsed: float,
    n_stocks: int,
    output_path: Path,
):
    lppl_report = make_lppl_report(lppl_diag)
    wyckoff_report = make_wyckoff_report(wyckoff_diag)
    cross_report = make_cross_report(xdiag)

    data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "n_stocks": n_stocks,
            "elapsed_seconds": round(elapsed, 1),
        },
        "lppl": lppl_report,
        "wyckoff": wyckoff_report,
        "cross": cross_report,
        "raw": {
            "lppl_records": len(lppl_diag.records),
            "wyckoff_records": len(wyckoff_diag.records),
            "cross_records": len(xdiag.records),
        },
    }
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON 结果已写入: {output_path}")


# ────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="LPPL × Wyckoff 交叉验证诊断")
    parser.add_argument("--stocks", type=str, default="golden_100",
                        help="股票列表: golden_100, golden_20, 或自定义文件路径")
    parser.add_argument("--max", type=int, default=100, help="最大股票数")
    parser.add_argument("--start", type=str, default="2022-01-01", help="数据起始日期")
    parser.add_argument("--output", type=str, default="scripts/output/cross_validation_report",
                        help="输出路径前缀")
    parser.add_argument("--skip-lppl", action="store_true", help="跳过LPPL诊断")
    parser.add_argument("--skip-wyckoff", action="store_true", help="跳过Wyckoff诊断")
    parser.add_argument("--skip-cross", action="store_true", help="跳过交叉验证")
    args = parser.parse_args()

    # Load stock list
    if args.stocks == "golden_100":
        symbols = load_golden_100()
    elif args.stocks == "golden_20":
        symbols = load_golden_20()
    elif Path(args.stocks).exists():
        symbols = load_golden_list(Path(args.stocks))
    else:
        print(f"Unknown stock list: {args.stocks}")
        sys.exit(1)

    print(f"加载 {len(symbols)} 只股票...")
    samples = prepare_samples(symbols, start=args.start)
    n_stocks = min(len(samples), args.max)
    samples = samples[:n_stocks]
    print(f"可用: {n_stocks} 只股票 (数据量>=120根K线)")

    t_start = time.time()
    lppl_diag = LpplDiagnostics()
    wyckoff_diag = WyckoffDiagnostics()
    xdiag = CrossDiagnostics()

    if not args.skip_lppl:
        print("\n=== LPPL 诊断 ===")
        lppl_diag = run_lppl_diagnostics(samples, max_stocks=args.max)

    if not args.skip_wyckoff:
        print("\n=== Wyckoff 诊断 ===")
        wyckoff_diag = run_wyckoff_diagnostics(samples, max_stocks=args.max)

    if not args.skip_cross:
        print("\n=== 交叉验证 ===")
        xdiag = run_cross_diagnostics(samples, lppl_diag, wyckoff_diag, max_stocks=args.max)

    elapsed = time.time() - t_start
    print(f"\n=== 总计耗时: {elapsed:.1f} 秒 ===")

    # Output
    output_dir = Path(args.output).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = Path(str(args.output) + ".md")
    md_content = generate_report(lppl_diag, wyckoff_diag, xdiag, elapsed, n_stocks)
    md_path.write_text(md_content, encoding="utf-8")
    print(f"Markdown 报告已写入: {md_path}")

    json_path = Path(str(args.output) + ".json")
    dump_json(lppl_diag, wyckoff_diag, xdiag, elapsed, n_stocks, json_path)

    print("\n" + md_content)


if __name__ == "__main__":
    main()
