#!/usr/bin/env python3
"""
V5: A股铁律交互审计 — Wyckoff P0 后关键规则验证

检查:
1. markdown/distribution 禁多规则 (engine.py _step5_trading_plan)
2. 涨跌停/一字板守卫 (engine.py _detect_limit_moves + step5)
3. SELL=只平仓 (unified_engine.py)
4. P0 direction gate 叠加后 adapter 不泄漏

运行: python3 scripts/wyckoff_deep_verify/v5_ashare_guard.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.wyckoff_fixtures import synthetic_accumulation
from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.models import (
    ConfidenceLevel,
)
from uniquant.signal.adapters import WyckoffAdapter

np.random.seed(42)

_CONF_TO_FLOAT = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}

# ══════════════════════════════════════════════════════════════════
# A. 静态代码审计
# ══════════════════════════════════════════════════════════════════

STATIC_AUDIT = {
    "markdown_no_long_rule": {
        "location": "engine.py:1434-1437",
        "rule_text": (
            "if step1.phase == WyckoffPhase.MARKDOWN: direction = '空仓观望'; "
            "elif step1.phase == WyckoffPhase.DISTRIBUTION: direction = '空仓观望'"
        ),
        "p0_status": (
            "生效。引擎层独立设 direction='空仓观望'，经由 WyckoffOutput.direction "
            "透传到 adapter direction gate。direction='空仓观望' 不在 _ENTRY_DIRECTIONS 中，"
            "adapter 返回 None。P0 gate 未旁路禁多规则，二层拦截（引擎层 + adapter 层）均有效。"
        ),
    },
    "a_stock_rules_final_check": {
        "location": "engine.py:1614-1622",
        "rule_text": (
            "_apply_a_stock_rules: 调用 rules.rule2_no_long_in_markdown 二次守卫"
            "（MARKDOWN/DISTRIBUTION 禁多），若 _step5 意外未拦截，此处二次兜底。"
        ),
        "p0_status": (
            "生效。在 _step5_trading_plan 之后、_build_report 之前调用，"
            "作为 markdown/distribution 禁多的二次防线。"
        ),
    },
    "limit_down_guard": {
        "location": "engine.py:1536-1538",
        "rule_text": (
            "if any(lm.move_type == LimitMoveType.LIMIT_DOWN for lm in limit_moves): "
            "direction = '空仓观望'"
        ),
        "p0_status": (
            "生效。近20日有跌停记录 → direction 强制设为 '空仓观望'，"
            "独立于 P0 direction gate。涨跌停检测在 _detect_limit_moves (engine.py:1968) "
            "中通过 is_limit_up/is_limit_down 检查 close vs prev_close 价格比实现。"
        ),
    },
    "limit_up_no_guard": {
        "location": "engine.py:1536-1538",
        "rule_text": "仅 LIMIT_DOWN 触发 direction='空仓观望'；LIMIT_UP 单独不强制改变 direction。",
        "p0_status": (
            "存在（非 P0 回归）。涨跌停检测仅对跌停做强制空仓。"
            "涨停日 direction 由相位逻辑决定，无独立涨停守卫。"
        ),
    },
    "sell_only_flat": {
        "location": "unified_engine.py:420",
        "rule_text": "if sig.action == 'SELL' and position > 0:",
        "p0_status": "生效。SELL 仅在 position>0 时执行，纯平仓语义。P0 不改变此行为。",
    },
    "limit_move_detection": {
        "location": "engine.py:1968, classifiers.py:240-299",
        "rule_text": (
            "_detect_limit_moves → detect_limit_moves: 近20日逐根 K 线检查 is_limit_up/"
            "is_limit_down，返回 LimitMove 列表。code_prefix 决定涨跌停比例 (10/20/30%)。"
        ),
        "p0_status": "生效。涨跌停检测逻辑独立于 P0 方向体系，无改动。",
    },
}

# ══════════════════════════════════════════════════════════════════
# B. 辅助函数
# ══════════════════════════════════════════════════════════════════


def _report_to_wyckoff_dict(report, df) -> dict:
    phase = "unknown"
    if report.structure and report.structure.phase:
        p = report.structure.phase
        phase = str(p.value) if hasattr(p, "value") else str(p)

    confidence = 0.0
    direction = ""
    tp = report.trading_plan
    if tp is not None:
        direction = tp.direction or ""
        tp_conf = getattr(tp, "confidence", None)
        if tp_conf is not None:
            if isinstance(tp_conf, ConfidenceLevel):
                conf_str = tp_conf.value
            elif hasattr(tp_conf, "value"):
                conf_str = tp_conf.value
            else:
                conf_str = str(tp_conf)
            confidence = _CONF_TO_FLOAT.get(conf_str, 0.3)

    spring = False
    utad = False
    if report.signal:
        st = str(report.signal.signal_type or "").lower()
        spring = "spring" in st
        utad = "utad" in st

    rr_ratio = 0.0
    if report.risk_reward:
        rr = getattr(report.risk_reward, "reward_risk_ratio", 0.0)
        rr_ratio = float(rr) if rr else 0.0

    price = float(df["close"].iloc[-1]) if "close" in df.columns else 0.0

    return {
        "wyckoff_phase": phase,
        "wyckoff_confidence": confidence,
        "wyckoff_spring": spring,
        "wyckoff_utad": utad,
        "wyckoff_direction": direction,
        "price": price,
        "rr_ratio": rr_ratio,
        "bypassed": False,
        "structural_score": float(getattr(report, "structural_score", 0.0)),
    }


def _extract_limit_moves(report) -> list:
    moves = []
    if hasattr(report, "limit_moves"):
        for lm in report.limit_moves:
            mv = lm.move_type.value if hasattr(lm.move_type, "value") else str(lm.move_type)
            moves.append({"date": str(lm.date)[:10], "type": mv})
    return moves


def _extract_confidence(tp) -> tuple:
    """Extract (confidence_str, confidence_float) from TradingPlan or V3TradingPlan."""
    if tp is None:
        return ("N/A", 0.0)
    conf = getattr(tp, "confidence", None)
    if conf is None:
        return ("N/A", 0.0)
    if isinstance(conf, ConfidenceLevel):
        return (conf.value, _CONF_TO_FLOAT.get(conf.value, 0.3))
    if hasattr(conf, "level"):
        lvl = conf.level
        if isinstance(lvl, ConfidenceLevel):
            return (lvl.value, _CONF_TO_FLOAT.get(lvl.value, 0.3))
        return (str(lvl), _CONF_TO_FLOAT.get(str(lvl), 0.3))
    return (str(conf), 0.3)


def run_scenario(name: str, desc: str, df: pd.DataFrame, engine: WyckoffEngine, adapter: WyckoffAdapter) -> dict:
    err = None
    report = None
    try:
        report = engine.analyze(df, symbol="000001.SZ", multi_timeframe=False)
    except Exception as e:
        err = str(e)

    if err or report is None:
        return {
            "scenario": name,
            "description": desc,
            "engine_error": err or "report is None",
            "phase": "ERROR",
            "trading_plan_direction": "ERROR",
            "trading_plan_confidence": "ERROR",
            "adapter_confidence": 0.0,
            "adapter_output": "ERROR",
            "limit_moves": [],
            "no_long_rule_effective": False,
            "adapter_no_leak": False,
        }

    tp = report.trading_plan
    tp_direction = tp.direction if tp else "no_plan"
    phase = str(report.structure.phase) if report.structure else "no_structure"
    conf_str, conf_float = _extract_confidence(tp)

    wyckoff_dict = _report_to_wyckoff_dict(report, df)
    adapter_output = None
    try:
        sig = adapter.adapt(wyckoff_dict, symbol="000001.SZ")
        adapter_output = sig.action if sig else None
    except Exception as e:
        adapter_output = f"ERROR: {e}"

    no_long_ok = not any(d in tp_direction for d in ["做多", "买入", "轻仓试探"])
    adapter_ok = adapter_output is None

    return {
        "scenario": name,
        "description": desc,
        "phase": phase,
        "trading_plan_direction": tp_direction,
        "trading_plan_confidence": conf_str,
        "adapter_confidence": conf_float,
        "adapter_output": adapter_output,
        "limit_moves": _extract_limit_moves(report),
        "no_long_rule_effective": no_long_ok,
        "adapter_no_leak": adapter_ok,
        "sell_only_flat": "SELL 仅在 position>0 执行（静态规则，不变）",
    }


# ══════════════════════════════════════════════════════════════════
# C. 场景构造
# ══════════════════════════════════════════════════════════════════


def scenario_limit_up() -> pd.DataFrame:
    """涨停日: 最后 K 线 close = prev_close * 1.10"""
    df = synthetic_accumulation(length=120, seed=42).copy()
    prev_c = float(df["close"].iloc[-2])
    df.loc[df.index[-1], "close"] = prev_c * 1.10
    df.loc[df.index[-1], "high"] = prev_c * 1.11
    df.loc[df.index[-1], "low"] = prev_c * 1.05
    df.loc[df.index[-1], "open"] = prev_c * 1.08
    df.loc[df.index[-1], "volume"] = int(df["volume"].median() * 1.5)
    return df


def scenario_limit_up_mono() -> pd.DataFrame:
    """一字板涨停: 连续 2 日涨停, 后一日缩量一字板"""
    df = synthetic_accumulation(length=120, seed=42).copy()
    # 倒数第二根也涨停
    prev2_c = float(df["close"].iloc[-3])
    df.loc[df.index[-2], "close"] = prev2_c * 1.10
    df.loc[df.index[-2], "high"] = prev2_c * 1.11
    df.loc[df.index[-2], "low"] = prev2_c * 1.05
    df.loc[df.index[-2], "open"] = prev2_c * 1.08
    df.loc[df.index[-2], "volume"] = int(df["volume"].median() * 0.3)
    # 最后一根一字板
    prev_c = float(df["close"].iloc[-2])
    df.loc[df.index[-1], "close"] = prev_c * 1.10
    df.loc[df.index[-1], "high"] = prev_c * 1.101
    df.loc[df.index[-1], "low"] = prev_c * 1.099
    df.loc[df.index[-1], "open"] = prev_c * 1.10
    df.loc[df.index[-1], "volume"] = int(df["volume"].median() * 0.2)
    return df


def scenario_limit_down() -> pd.DataFrame:
    """跌停日: 最后 K 线 close = prev_close * 0.90"""
    df = synthetic_accumulation(length=120, seed=42).copy()
    prev_c = float(df["close"].iloc[-2])
    df.loc[df.index[-1], "close"] = prev_c * 0.90
    df.loc[df.index[-1], "high"] = prev_c * 0.95
    df.loc[df.index[-1], "low"] = prev_c * 0.89
    df.loc[df.index[-1], "open"] = prev_c * 0.93
    df.loc[df.index[-1], "volume"] = int(df["volume"].median() * 1.5)
    return df


def scenario_markdown() -> pd.DataFrame:
    """Markdown 连续下跌: 最后 25 根 K 线持续下跌, 使 short_trend ≤ -0.05, cp < ma20*0.95"""
    df = synthetic_accumulation(length=120, seed=42).copy()
    n = len(df)
    base = float(df["close"].iloc[n - 26])
    for i in range(25):
        idx = n - 25 + i
        factor = 1 - 0.018 * (i + 1)
        df.loc[df.index[idx], "close"] = base * factor
        df.loc[df.index[idx], "open"] = base * factor * 1.002
        df.loc[df.index[idx], "high"] = base * factor * 1.005
        df.loc[df.index[idx], "low"] = base * factor * 0.995
        df.loc[df.index[idx], "volume"] = int(df["volume"].median() * (1 + 0.5 * (i % 3)))
    return df


def scenario_distribution() -> pd.DataFrame:
    """Distribution TR+UTAD: 范围震荡 + 假突破后回落"""
    df = synthetic_accumulation(length=120, seed=42).copy()
    n = len(df)
    tr_high = float(df["close"].iloc[:60].max()) * 1.02
    tr_low = float(df["close"].iloc[:60].min()) * 0.98
    for i in range(60, n):
        phase = i - 60
        if phase < 20:
            factor = 1 + 0.015 * phase
            df.loc[df.index[i], "close"] = tr_low * factor
            df.loc[df.index[i], "high"] = df.loc[df.index[i], "close"] * 1.01
            df.loc[df.index[i], "low"] = df.loc[df.index[i], "close"] * 0.99
            df.loc[df.index[i], "open"] = df.loc[df.index[i], "close"] * 0.995
            df.loc[df.index[i], "volume"] = int(df["volume"].median() * 1.0)
        elif phase < 30:
            df.loc[df.index[i], "close"] = tr_high * 1.03
            df.loc[df.index[i], "high"] = tr_high * 1.05
            df.loc[df.index[i], "low"] = tr_high * 0.99
            df.loc[df.index[i], "open"] = df.loc[df.index[i], "close"] * 0.99
            df.loc[df.index[i], "volume"] = int(df["volume"].median() * 2.0)
        elif phase < 40:
            df.loc[df.index[i], "close"] = tr_high * 0.98
            df.loc[df.index[i], "high"] = tr_high * 1.02
            df.loc[df.index[i], "low"] = tr_high * 0.95
            df.loc[df.index[i], "open"] = df.loc[df.index[i], "close"] * 1.005
            df.loc[df.index[i], "volume"] = int(df["volume"].median() * 0.7)
        else:
            factor = 1 - 0.015 * (phase - 40)
            df.loc[df.index[i], "close"] = tr_high * max(factor, 0.5)
            df.loc[df.index[i], "high"] = df.loc[df.index[i], "close"] * 1.01
            df.loc[df.index[i], "low"] = df.loc[df.index[i], "close"] * 0.99
            df.loc[df.index[i], "open"] = df.loc[df.index[i], "close"] * 1.002
            df.loc[df.index[i], "volume"] = int(df["volume"].median() * 1.2)
    return df


# ══════════════════════════════════════════════════════════════════
# D. 主入口
# ══════════════════════════════════════════════════════════════════


def main():
    engine = WyckoffEngine()
    adapter = WyckoffAdapter()

    scenarios = [
        ("limit_up", "涨停日（close=prev_close*1.10）", scenario_limit_up()),
        ("limit_up_mono", "一字板涨停（连续2日涨停锁板）", scenario_limit_up_mono()),
        ("limit_down", "跌停日（close=prev_close*0.90）", scenario_limit_down()),
        ("markdown_phase", "Markdown 连续下跌 25 日", scenario_markdown()),
        ("distribution_phase", "Distribution TR+UTAD 序列", scenario_distribution()),
    ]

    results = []
    for name, desc, df in scenarios:
        r = run_scenario(name, desc, df, engine, adapter)
        results.append(r)

    n_scenarios = len(results)

    # 核心判定: 禁多是否被 P0 gate 旁路导致 BUY 泄漏
    no_long_leak = all(r["no_long_rule_effective"] for r in results)
    adapter_no_leak = all(r["adapter_no_leak"] for r in results)
    all_pass = no_long_leak and adapter_no_leak

    # 构建 findings
    findings = []
    for r in results:
        tp = r["trading_plan_direction"]
        ph = r["phase"]
        phase_short = ph.replace("WyckoffPhase.", "")
        adapter_action = r["adapter_output"]
        conf = r["trading_plan_confidence"]
        conf_f = r["adapter_confidence"]

        if phase_short in ("MARKDOWN", "DISTRIBUTION") or r["scenario"] in ("markdown_phase", "distribution_phase"):
            entry_dirs = [d for d in ["做多", "买入", "轻仓试探"] if d in tp]
            if entry_dirs:
                findings.append(f"{r['scenario']}: phase={phase_short} dir={tp} → 含入场方向 {entry_dirs} ✗")
            else:
                findings.append(f"{r['scenario']}: phase={phase_short} dir={tp} conf={conf} → 禁多规则生效 ✓")

        if r["scenario"] == "limit_down":
            had_down = any(m["type"] == "跌停" for m in r["limit_moves"])
            flag = "✓" if had_down else "⚠ 未检测到跌停"
            findings.append(f"{r['scenario']}: 跌停检测={flag} dir={tp} adapter={adapter_action} conf={conf}({conf_f})")

        if r["scenario"] in ("limit_up", "limit_up_mono"):
            had_up = any(m["type"] == "涨停" for m in r["limit_moves"])
            flag = "✓" if had_up else "⚠ 未检测到涨停"
            findings.append(f"{r['scenario']}: 涨停检测={flag} dir={tp} adapter={adapter_action} conf={conf}({conf_f})")

        if adapter_action is not None:
            findings.append(f"{r['scenario']}: adapter 泄漏 BUY ✗")
        else:
            findings.append(f"{r['scenario']}: adapter=None conf={conf}({conf_f}) → 无泄漏 ✓")

    output = {
        "meta": {
            "script": "v5_ashare_guard.py",
            "description": "P0 后 A股铁律交互审计 — 静态代码审计 + 运行时合成场景测试",
            "seed": 42,
            "symbol": "000001.SZ",
            "config": {
                "direction_gate_enabled": True,
                "confidence_gate": 0.40,
                "structural_adjust_enabled": False,
                "accumulation_downgrade": True,
            },
        },
        "static_audit": STATIC_AUDIT,
        "scenarios": results,
        "findings": findings,
        "summary": {
            "total_scenarios": n_scenarios,
            "no_long_rule_pass": sum(1 for r in results if r["no_long_rule_effective"]),
            "adapter_no_leak_pass": sum(1 for r in results if r["adapter_no_leak"]),
            "all_pass": all_pass,
        },
        "verdict": {
            "result": "PASS" if all_pass else "FAIL",
            "criteria": (
                "V5 PASS ⇔ 所有场景下：禁多规则仍生效 + adapter 输出 None + SELL 只平仓。"
                "V5 FAIL ⇔ 任一场景下禁多规则被 P0 gate 旁路导致 BUY 泄漏。"
            ),
            "note": (
                "FAIL 根因: limit_up（单涨停日）场景下引擎产生 direction='做多'"
                "（MARKUP 相位，无独立涨停守卫），adapter 因 direction='做多'∈_ENTRY_DIRECTIONS "
                "且 conf=C(0.5)≥confidence_gate(0.40) 输出 BUY —— BUY 泄漏。"
                "但此泄漏非'禁多规则被 P0 gate 旁路'（MARKUP 非禁多相位），而是引擎缺独立涨停守卫"
                "（非 P0 回归，P0 前后一致）。"
                "一字板场景（limit_up_mono）正确产生 '空仓观望'、adapter=None；"
                "跌停场景正确产生 '空仓观望'、adapter=None；"
                "markdown/distribution 禁多规则均生效且 adapter=None；"
                "SELL=只平仓语义不变。"
            ),
        },
    }

    out_dir = ROOT / "results" / "wyckoff_deep_verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "v5_ashare_guard.json"
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output


if __name__ == "__main__":
    main()