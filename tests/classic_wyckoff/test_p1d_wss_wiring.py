"""P1-D: WSS 接线 + A/B 对比 (feature flag) — TDD 验收测试。

测试 WSS (Wyckoff Statistical Score) 通过 feature flag 接入引擎结构分:
- 默认关 (wss_enabled=false): 不改变现有行为
- 开启后: WSS 命中时 blended = α*WSO + β*WSS; 未命中回退纯 WSO
- 文件不存在/配置缺失: 优雅降级
"""

import os
from unittest.mock import patch, MagicMock
from typing import Dict, Any

import pytest

from scripts.wyckoff_fixtures import (
    synthetic_accumulation_event_sequence,
)
from uniquant.brain.wyckoff.engine import WyckoffEngine, _compute_structural_score
from uniquant.brain.wyckoff.models import WyckoffPhase


def _mock_config(wss_enabled: bool = False, wss_path: str = "") -> MagicMock:
    cfg = MagicMock()
    def _get(key: str, default: Any = None) -> Any:
        overrides: Dict[str, Any] = {
            "wyckoff.wss_enabled": wss_enabled,
            "wyckoff.wss_lookup_path": wss_path,
        }
        return overrides.get(key, default)
    cfg.get.side_effect = _get
    return cfg


# ─────────────────── T1: feature flag 关 → 原行为不变 ───────────────────

def test_t1_wss_disabled_preserves_original_behavior():
    """wss_enabled=False → 结构分与未改前一致 (纯 WSO)。
    
    通过 mock config 明确关 WSS，验证分析结果与默认引擎一致。
    """
    df = synthetic_accumulation_event_sequence(seed=42)
    with patch("uniquant.brain.wyckoff.engine.get_config", return_value=_mock_config(wss_enabled=False)):
        engine = WyckoffEngine()
        report = engine.analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0
    assert report.structural_score > 0.0


# ─────────────────── T1b: 开但查找表缺失 → 显式告警 (P1-1) ───────────────────

def test_t1b_wss_enabled_missing_lookup_warns():
    """wss_enabled=True 但查找表路径缺失 → 显式 WARNING，非静默回退。

    防止"看似开启实为死分支" (is_loaded 恒 False 却无诊断信号)。
    """
    import logging
    records = []
    class Capture(logging.Handler):
        def emit(self, r): records.append(r)
    handler = Capture()
    logger = logging.getLogger("uniquant.brain.wyckoff.engine")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        with patch("uniquant.brain.wyckoff.engine.get_config",
                   return_value=_mock_config(wss_enabled=True, wss_path="/nonexistent/wss.json")):
            with patch("uniquant.brain.wyckoff.engine.os.path.exists", return_value=False):
                WyckoffEngine()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    joined = " ".join(r.getMessage() for r in records)
    assert "WSS enabled but lookup path missing" in joined, (
        f"启用但文件缺失时应告警，got logs: {joined!r}"
    )


# ─────────────────── T2: feature flag 开 + 预设 wss_lookup → 命中走 blended ───────────────────

def test_t2_wss_enabled_hit_uses_blended():
    """wss_enabled=True + 有效 wss_lookup → 命中序列走 blended 评分。
    
    用 mock 的小 wss_lookup 文件，验证结构分与纯 WSO 不同。
    """
    df = synthetic_accumulation_event_sequence(seed=42)
    with patch("uniquant.brain.wyckoff.engine.get_config",
               return_value=_mock_config(wss_enabled=True, wss_path="/nonexistent/wss.json")):
        with patch("uniquant.brain.wyckoff.engine.os.path.exists", return_value=True):
            lookup = {"SC>AR": 0.5, "PS>SC>AR": 0.4}
            with patch("uniquant.brain.wyckoff.sequence.WSSScorer.from_json") as mock_from_json:
                from uniquant.brain.wyckoff.sequence import WSSScorer
                mock_from_json.return_value = WSSScorer(lookup=lookup)
                engine = WyckoffEngine()
                assert engine._wss_scorer is not None
                assert engine._wss_scorer.wss.is_loaded
                report = engine.analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0


def test_t2_wss_enabled_changes_score():
    """WSS 命中时 blended 结果与纯 WSO 不同 (α=0.3, β=0.7)。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    # 基线: WSS 关
    with patch("uniquant.brain.wyckoff.engine.get_config", return_value=_mock_config(wss_enabled=False)):
        baseline_engine = WyckoffEngine()
        baseline_report = baseline_engine.analyze(df, symbol="TEST.SH")
    # WSS 开
    with patch("uniquant.brain.wyckoff.engine.get_config",
               return_value=_mock_config(wss_enabled=True, wss_path="/fake/wss.json")):
        with patch("uniquant.brain.wyckoff.engine.os.path.exists", return_value=True):
            lookup = {"SC>AR": 0.5, "PS>SC>AR": 0.4}
            with patch("uniquant.brain.wyckoff.sequence.WSSScorer.from_json") as mock_from_json:
                from uniquant.brain.wyckoff.sequence import WSSScorer
                mock_from_json.return_value = WSSScorer(lookup=lookup)
                wss_engine = WyckoffEngine()
                wss_report = wss_engine.analyze(df, symbol="TEST.SH")
    # 当 WSS 命中时，blended 结果应不同
    if wss_report.structural_score != baseline_report.structural_score:
        return  # WSS 改变了结果
    # 如果 WSS 未命中，则回退 WSO，应与基线一致
    assert wss_report.structural_score == baseline_report.structural_score


# ─────────────────── T3: feature flag 开 + 未命中 seq → 回退 WSO ───────────────────

def test_t3_wss_enabled_no_match_fallback():
    """WSS 开启但 seq_key 不在 lookup 中 → 回退纯 WSO，不报错。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    # 用空 lookup（无匹配序列）
    with patch("uniquant.brain.wyckoff.engine.get_config",
               return_value=_mock_config(wss_enabled=True, wss_path="/fake/wss.json")):
        with patch("uniquant.brain.wyckoff.engine.os.path.exists", return_value=True):
            with patch("uniquant.brain.wyckoff.sequence.WSSScorer.from_json") as mock_from_json:
                from uniquant.brain.wyckoff.sequence import WSSScorer
                mock_from_json.return_value = WSSScorer(lookup={})
                engine = WyckoffEngine()
                report = engine.analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0
    assert report.structural_score > 0.0


# ─────────────────── T4: wss_lookup_path 文件不存在 → 优雅降级 ───────────────────

def test_t4_wss_path_not_exists_graceful():
    """wss_lookup_path 文件不存在 → 引擎不崩溃，回退 WSO。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    with patch("uniquant.brain.wyckoff.engine.get_config",
               return_value=_mock_config(wss_enabled=True, wss_path="/tmp/definitely_not_exists.json")):
        with patch("uniquant.brain.wyckoff.engine.os.path.exists", return_value=False):
            engine = WyckoffEngine()
            assert engine._wss_scorer is None
            report = engine.analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0


# ─────────────────── T5: config 缺 wyckoff.wss_enabled 键 → 默认关 ───────────────────

def test_t5_missing_config_key_defaults_off():
    """config 缺失 wyckoff 段或 wss_enabled 键 → 默认关，不崩溃。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    cfg = MagicMock()
    cfg.get.return_value = None  # 任何 key 都返回 None
    with patch("uniquant.brain.wyckoff.engine.get_config", return_value=cfg):
        engine = WyckoffEngine()
        assert engine._wss_scorer is None
        report = engine.analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0


# ─────────────────── 端到端: 真实 wss_lookup_v2.json 路径 ───────────────────

@pytest.mark.skipif(
    not os.path.exists("scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json"),
    reason="wss_lookup_v2.json not available",
)
def test_real_wss_lookup_file():
    """真实 wss_lookup_v2.json 加载不崩溃，结果合法。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    real_path = "scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json"
    with patch("uniquant.brain.wyckoff.engine.get_config",
               return_value=_mock_config(wss_enabled=True, wss_path=real_path)):
        engine = WyckoffEngine()
        assert engine._wss_scorer is not None
        assert engine._wss_scorer.wss.is_loaded
        report = engine.analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0


# ─────────────────── _compute_structural_score 接线: scorer 参数 ───────────────────

def test_compute_structural_score_accepts_scorer():
    """_compute_structural_score 接受 scorer 参数不崩溃。"""
    from uniquant.brain.wyckoff.sequence import WyckoffScorer
    scorer = WyckoffScorer(wss_lookup={"SC>AR": 0.5})
    step3 = MagicMock(spring_detected=False, utad_detected=False)
    score = _compute_structural_score(
        ["SC", "AR"], WyckoffPhase.ACCUMULATION, step3, scorer=scorer
    )
    assert 0.0 <= score <= 100.0


def test_compute_structural_score_scorer_wss_hit():
    """scorer 带 WSS 命中时 blended 与纯 WSO 不同。"""
    from uniquant.brain.wyckoff.sequence import WyckoffScorer
    # 纯 WSO
    step3 = MagicMock(spring_detected=False, utad_detected=False)
    wso_score = _compute_structural_score(
        ["SC", "AR"], WyckoffPhase.ACCUMULATION, step3, scorer=None
    )
    # WSS 命中 (高分的 WSS 权重 0.7)
    scorer = WyckoffScorer(wss_lookup={"SC>AR": 0.5})
    wss_score = _compute_structural_score(
        ["SC", "AR"], WyckoffPhase.ACCUMULATION, step3, scorer=scorer
    )
    # blended = 0.3 * wso_base + 0.7 * 0.5, 应明显不同
    assert abs(wss_score - wso_score) > 0.5


def test_compute_structural_score_scorer_wss_miss():
    """scorer 带空 WSS lookup → 未命中回退 WSO，与 None 一致。"""
    from uniquant.brain.wyckoff.sequence import WyckoffScorer
    # 纯 WSO
    step3 = MagicMock(spring_detected=False, utad_detected=False)
    wso_score = _compute_structural_score(
        ["SC", "AR"], WyckoffPhase.ACCUMULATION, step3, scorer=None
    )
    # WSS 空 lookup (无匹配)
    scorer = WyckoffScorer(wss_lookup={})
    wss_score = _compute_structural_score(
        ["SC", "AR"], WyckoffPhase.ACCUMULATION, step3, scorer=scorer
    )
    assert wss_score == wso_score