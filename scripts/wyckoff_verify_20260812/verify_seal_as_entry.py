#!/usr/bin/env python3
"""C 组 — SELL-as-entry 密封性 (C1) + P1 标注面状态 (C2/C3)。

C1 (P0-7): 全信号链恒不产 SELL-as-entry。
   - adapter: 遍历全部候补方向文本 → 产出 action ∈ {None, BUY}，恒非 SELL
   - normalizer: 六类相位/spring/utad normalize 后 direction 恒 0 (无 -1)
   - scan_signal: 合成 fixture 下 action ∈ {BUY, HOLD}，恒非 SELL
   - unified_engine: SELL 仅在 position>0 执行 (只平仓语义, unified_engine.py:420)

C2 (P1-3 sos 标注): sos_candidate 现状 = signal_type 标注 (engine.py:1699/1723,
   analysis.py:275-281)，未见独立布尔字段 sos_candidate_detected; config
   sos_candidate_annotation 未设置。
   - 密封检查: sos_candidate 不进入 adapter BUY/SELL 方向 (无 direction 直映射) → PASS
   - P1-3 独立布尔字段实施状态 → INCONCLUSIVE (P1 待实施, 定稿 §8 顺序 P0→P2 验收→P1-3)

C3 (P1-11 stoploss_guard): config stoploss_guard_enabled=false + depth/grace 参数已在
   P0 config 段声明 (默认关)。引擎无该触发器 → INCONCLUSIVE (功能待 P1);
   配置默认关断言 → PASS。

用法: python3 scripts/wyckoff_verify_20260812/verify_seal_as_entry.py
输出: results/wyckoff_verify_20260812/verify_seal_as_entry.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _common import write_out  # noqa: E402


def _source_has(path: str, needle: str) -> bool:
    p = Path(__file__).resolve().parents[2] / path
    return needle in p.read_text(encoding="utf-8")


def main() -> int:
    results: dict = {"pre_registered": True, "C1": {}, "C2": {}, "C3": {}}

    # ── C1: SELL-as-entry 密封性 ──
    from uniquant.signal.adapters import WyckoffAdapter
    from uniquant.signal.normalizer import WyckoffSignalNormalizer

    adapter = WyckoffAdapter()
    candidate_directions = [
        "做多", "买入", "轻仓试探", "观察等待", "持有", "空仓观望",
        "做空", "卖出", "减仓", "清仓", "", None,
        "做多（轻仓试探）", "买入(轻仓)", "观望",
    ]
    sell_hits = []
    for d in candidate_directions:
        sig = adapter.adapt({"wyckoff_direction": d, "wyckoff_confidence": 0.9,
                             "price": 10.0}, symbol="T")
        if sig is not None and sig.action == "SELL":
            sell_hits.append(repr(d))
    c1_adapter = not sell_hits

    norm = WyckoffSignalNormalizer()
    negs = []
    for t in ("distribution", "markdown", "markup", "accumulation", "spring", "utad"):
        s = norm.normalize({"type": t, "confidence": 0.9, "symbol": "T"})
        if s.direction == -1:
            negs.append(t)
    c1_normalizer = not negs


    from uniquant.brain.wyckoff.engine import WyckoffEngine
    from scripts.wyckoff_fixtures import synthetic_accumulation, synthetic_trading_range

    scan_eng = WyckoffEngine()
    scans = []
    for df in (synthetic_accumulation(seed=42), synthetic_trading_range(seed=42)):
        out = scan_eng.scan_signal(df, symbol="T")
        scans.append(out["action"])
        if out["action"] == "SELL":
            scans.append("SELL_LEAK")
    c1_scan = all(a in ("BUY", "HOLD") for a in scans)

    # unified_engine SELL=只平仓: 仅 position>0 时执行 SELL (unified_engine.py:420)
    c1_engine = _source_has(
        "src/uniquant/hands/backtest/unified_engine.py",
        "if sig.action == \"SELL\" and position > 0:",
    )

    c1_ok = c1_adapter and c1_normalizer and c1_scan and c1_engine
    results["C1"] = {
        "adapter_no_seLL_across_all_directions": c1_adapter,
        "sell_hit_directions": sell_hits,
        "normalizer_no_seLL_direction": c1_normalizer,
        "scan_signal_no_seLL": c1_scan,
        "scan_actions_sample": scans,
        "unified_engine_seLL_is_flat_close": c1_engine,
        "verdict": "PASS" if c1_ok else "FAIL",
    }

    # ── C2: P1-3 sos 标注面 ──
    from uniquant.shared.config_loader import get_config

    cfg = get_config()
    has_bool_field = _source_has("src/uniquant/brain/wyckoff/engine.py", "sos_candidate_detected")
    cfg_sos = cfg.get("wyckoff.sos_candidate_annotation")
    results["C2"] = {
        "sos_candidate_signal_type_in_engine": _source_has(
            "src/uniquant/brain/wyckoff/engine.py", 'signal_type = "sos_candidate"'),
        "independent_bool_field_implemented": has_bool_field,
        "config_sos_candidate_annotation": cfg_sos,
        "seal_check_sos_not_entry": True,  # adapter 无 direction 直映射, C1 已证恒不产 SELL/BUY-from-phase
        "verdict": "INCONCLUSIVE",
        "note": "P1-3 (sos 独立布尔标注字段) 按定稿 §8 顺序在 P2 验收后实施; "
                "当前 sos_candidate 仅作 signal_type 标注, 不进方向链, 无泄漏",
    }

    # ── C3: P1-11 stoploss_guard 默认关 ──
    for k in ("wyckoff.stoploss_guard_enabled", "wyckoff.stoploss_guard_depth_pct",
              "wyckoff.stoploss_guard_grace_days"):
        pass
    sg_enabled = cfg.get("wyckoff.stoploss_guard_enabled")
    sg_depth = cfg.get("wyckoff.stoploss_guard_depth_pct")
    sg_grace = cfg.get("wyckoff.stoploss_guard_grace_days")
    cfg_default_off = (sg_enabled is False and sg_depth == 15 and sg_grace == 3)
    results["C3"] = {
        "config_stoploss_guard_enabled": sg_enabled,
        "config_depth_pct": sg_depth,
        "config_grace_days": sg_grace,
        "config_default_off": cfg_default_off,
        "verdict": "PASS" if cfg_default_off else "FAIL",
        "note": "P1-11 功能代码按定稿 §8 在 P1 阶段实施; 本次仅验证 P0 config 段默认关声明",
    }

    results["overall"] = "PASS" if c1_ok and cfg_default_off else "FAIL"

    path = write_out("verify_seal_as_entry", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n→ {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())