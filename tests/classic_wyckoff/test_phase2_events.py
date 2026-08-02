"""Phase 2 事件序列 — ES-C3 UTAD 检测 TDD 验收测试。

对应 TDD 标准 docs/analysis/CLASSIC_WYCKOFF_TDD_STANDARD_VERIFICATION_v1.md
Phase 2 (ES-C3 → ES-C1 → PH-C1 → PH-C2)：
- ES-C3: _detect_utad 实现 —— X 列突破 TR 上沿 2%+ 后 1-2 列内收回 + 放量确认
"""

from scripts.wyckoff_fixtures import synthetic_utad
from scripts.wyckoff_fixtures import (
    synthetic_spring,
    synthetic_spring_late_recovery,
    synthetic_spring_aligned,
    synthetic_accumulation_event_sequence,
    synthetic_distribution_event_sequence,
    synthetic_false_breakout,
)
from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.events import detect_all_events, event_sequence_key
from uniquant.brain.wyckoff.models import Step1Result, Rule0Result
from uniquant.brain.wyckoff.models import WyckoffPhase


# ───────────────────────── ES-C3: UTAD 检测 ─────────────────────────

def test_utad_detection():
    """构造已知 UTAD 数据（X 列突破 TR 上沿后立即收回 + 放量），
    验证 engine 通过 _detect_utad 检测出 DISTRIBUTION 相位。"""
    df = synthetic_utad(seed=42)
    engine = WyckoffEngine()

    report = engine.analyze(df, symbol="TEST.SH")
    assert report.signal.signal_type == "utad", (
        f"应输出 utad 信号, got {report.signal.signal_type}"
    )


def test_utad_detects_distribution_phase():
    """UTAD 事件应驱动相位判定为 DISTRIBUTION（假突破上方＝派发）。"""
    df = synthetic_utad(seed=42)
    engine = WyckoffEngine()

    report = engine.analyze(df, symbol="TEST.SH")
    assert report.structure.phase == WyckoffPhase.DISTRIBUTION, (
        f"UTAD 应判定为 DISTRIBUTION, got {report.structure.phase}"
    )


def test_utad_step3_direct():
    """直接调用 _step3_phase_c_t1：UTAD 数据应置 step3.utad_detected=True。"""
    df = synthetic_utad(seed=42)
    engine = WyckoffEngine()
    engine._code_prefix = "TES"

    step1 = Step1Result(
        phase=WyckoffPhase.DISTRIBUTION,
        boundary_upper=12.0,
        boundary_lower=10.0,
        prior_trend_pct=0.1,
        is_in_tr=True,
    )
    rule0 = Rule0Result(
        bc_found=False, tr_upper=12.0, tr_lower=10.0,
        validity="full", confidence_base="C",
    )
    step3 = engine._step3_phase_c_t1(df, step1, rule0)
    assert step3.utad_detected is True, "UTAD 数据应触发 step3.utad_detected"


def test_utad_no_false_positive_on_sine():
    """无 Wyckoff 结构的正弦数据不应误报 UTAD。"""
    from scripts.wyckoff_fixtures import synthetic_sine_wave

    df = synthetic_sine_wave(seed=42)
    engine = WyckoffEngine()

    report = engine.analyze(df, symbol="TEST.SH")
    assert report.signal.signal_type != "utad", (
        f"正弦数据不应误报 UTAD, got {report.signal.signal_type}"
    )


# ───────────────────────── ES-C1: Spring 1-2 列收回规则 ─────────────────────────

def test_spring_classic_definition():
    """构造已知 Spring 数据（跌破 TR 下沿 1% 后次日收回 + 缩量），
    验证 engine 正确检测。"""
    df = synthetic_spring(seed=42)
    engine = WyckoffEngine()
    engine._code_prefix = "TES"

    step1 = Step1Result(
        phase=WyckoffPhase.ACCUMULATION,
        boundary_upper=12.0,
        boundary_lower=10.0,
        prior_trend_pct=0.1,
        is_in_tr=True,
    )
    rule0 = Rule0Result(
        bc_found=False, tr_upper=12.0, tr_lower=10.0,
        validity="full", confidence_base="C",
    )
    step3 = engine._step3_phase_c_t1(df, step1, rule0)
    assert step3.spring_detected is True, (
        f"跌破 1% 后 1 列收回应检测为 Spring, got {step3.spring_detected}"
    )
    assert step3.spring_date is not None, "Spring 应记录日期"


def test_spring_rejects_late_recovery():
    """跌破 TR 下沿但 3+ 列后才收回的数据，不应标记为 Spring（1-2 列收回规则）。"""
    df = synthetic_spring_late_recovery(seed=42)
    engine = WyckoffEngine()
    engine._code_prefix = "TES"

    step1 = Step1Result(
        phase=WyckoffPhase.ACCUMULATION,
        boundary_upper=12.0,
        boundary_lower=10.0,
        prior_trend_pct=0.1,
        is_in_tr=True,
    )
    rule0 = Rule0Result(
        bc_found=False, tr_upper=12.0, tr_lower=10.0,
        validity="full", confidence_base="C",
    )
    step3 = engine._step3_phase_c_t1(df, step1, rule0)
    assert step3.spring_detected is False, (
        f"3+ 列后才收回不应标记为 Spring, got {step3.spring_detected}"
    )


def test_spring_engine_end_to_end():
    """端到端：经典 Spring fixture 经 analyze() 应产生 spring 信号。"""
    df = synthetic_spring_aligned(seed=3)
    engine = WyckoffEngine()

    report = engine.analyze(df, symbol="TEST.SH")
    assert report.signal.signal_type == "spring", (
        f"经典 Spring 应输出 spring 信号, got {report.signal.signal_type}"
    )


# ───────────────────────── PH-C1: ACCUMULATION 由事件序列驱动 ─────────────────────────

def test_accumulation_event_sequence_fixture_fires():
    """fixture 前提校验：事件序列 PS/SC/AR/ST 应全部触发且价格位置位于中位。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    events = detect_all_events(df)
    types = {e.event_type for e in events}
    assert {"PS", "SC", "AR", "ST"} <= types, (
        f"事件序列应包含 PS/SC/AR/ST, got {types}"
    )
    assert types == {"PS", "SC", "AR", "ST"}, (
        f"不应有多余事件类型干扰, got {types}"
    )
    last = df.iloc[-1]
    hi = df["high"].iloc[-60:].max()
    lo = df["low"].iloc[-60:].min()
    rel_pos = (last["close"] - lo) / (hi - lo)
    assert 0.4 <= rel_pos <= 0.6, (
        f"价格位置应位于中位 0.4-0.6, got {rel_pos:.2f}"
    )


def test_accumulation_from_event_sequence():
    """PH-C1: 仅含完整事件序列（无 price_position 信号）的数据应输出 ACCUMULATION。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    engine = WyckoffEngine()

    report = engine.analyze(df, symbol="TEST.SH")
    assert report.structure.phase == WyckoffPhase.ACCUMULATION, (
        f"事件序列应驱动 ACCUMULATION, got {report.structure.phase}"
    )


def test_accumulation_event_sequence_key_has_ps_sc_st():
    """事件序列 key 应含 PS、SC、ST 且 ST 出现两次（积累序列核心特征）。"""
    df = synthetic_accumulation_event_sequence(seed=42)
    events = detect_all_events(df)
    key = event_sequence_key(events)
    assert "PS" in key and "SC" in key and "ST" in key, (
        f"事件序列应含 PS/SC/ST, got key={key}"
    )
    assert key.count("ST") >= 2, (
        f"ST 应出现两次（ST1/ST2）, got key={key}"
    )


# ───────────────────────── PH-C2: DISTRIBUTION 由事件序列驱动 ─────────────────────────

def test_distribution_event_sequence_fixture_fires():
    """fixture 前提校验：UTAD 事件应被 _scan_utad 捕获且 P&F hint=unknown。"""
    from uniquant.brain.wyckoff.pnf import PointAndFigure

    df = synthetic_distribution_event_sequence(seed=42)
    engine = WyckoffEngine()
    engine._code_prefix = "TES"
    frame = df.tail(engine.lookback_days).reset_index(drop=True)
    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(frame)
    assert pnf.wyckoff_phase_hint() != "distribution", (
        "fixture 不应由 P&F hint 短路，否则测不到 _detect_distribution 事件序列逻辑"
    )
    rule0 = engine._step0_bc_tr_scan(frame, pnf_zone=pnf.congestion_zone())
    utad = engine._scan_utad(frame, rule0.tr_upper)
    assert utad is not None, "UTAD 事件应被 _scan_utad 捕获"
    assert utad["vol_ratio"] >= 1.5, (
        f"UTAD 应有放量确认（量比≥1.5）, got {utad['vol_ratio']}"
    )


def test_distribution_from_event_sequence():
    """PH-C2: 仅含完整派发事件序列（上涨→PSY→UTAD→LPSY→跌破）应输出 DISTRIBUTION。"""
    df = synthetic_distribution_event_sequence(seed=42)
    engine = WyckoffEngine()

    report = engine.analyze(df, symbol="TEST.SH")
    assert report.structure.phase == WyckoffPhase.DISTRIBUTION, (
        f"UTAD 事件序列应驱动 DISTRIBUTION, got {report.structure.phase}"
    )


def test_distribution_event_sequence_ignores_price_position():
    """PH-C2: 事件序列匹配时忽略 price_position——尾部跌破后相对位置低位仍应 DISTRIBUTION。"""
    df = synthetic_distribution_event_sequence(seed=42)
    engine = WyckoffEngine()
    engine._code_prefix = "TES"

    frame = df.tail(engine.lookback_days).reset_index(drop=True)
    from uniquant.brain.wyckoff.pnf import PointAndFigure

    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(frame)
    rule0 = engine._step0_bc_tr_scan(frame, pnf_zone=pnf.congestion_zone())
    ctx = engine._compute_step1_context(frame, rule0)
    assert ctx["relative_position"] < 0.40, (
        f"前提：跌破后相对位置应低位以证明非 position 驱动, got {ctx['relative_position']:.2f}"
    )
    result = engine._detect_distribution(frame, ctx, rule0)
    assert result is not None and result["phase"] == WyckoffPhase.DISTRIBUTION, (
        "事件序列应忽略低位 price_position 直接驱动 DISTRIBUTION"
    )


# ───────────────────────── CF-C4: 假突破惩罚 ─────────────────────────

def test_false_breakout_fixture_premise():
    """fixture 前提校验：假突破数据应被 _scan_false_breakout 捕获，且无结构数据不误报。"""
    from scripts.wyckoff_fixtures import synthetic_trading_range
    from uniquant.brain.wyckoff.pnf import PointAndFigure

    engine = WyckoffEngine()
    engine._code_prefix = "TES"

    df = synthetic_false_breakout(seed=42)
    frame = df.tail(engine.lookback_days).reset_index(drop=True)
    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(frame)
    rule0 = engine._step0_bc_tr_scan(frame, pnf_zone=pnf.congestion_zone())
    assert rule0.tr_upper is not None and rule0.tr_upper > 0, "TR 上沿应有效"
    fb = engine._scan_false_breakout(frame, rule0.tr_upper)
    assert fb is not None, "假突破数据应被 _scan_false_breakout 捕获"
    assert fb["close_high"] > rule0.tr_upper, "突破高点应高于 TR 上沿"

    df_plain = synthetic_trading_range(
        length=100, low_bound=10.0, high_bound=12.0, seed=126
    )
    frame_plain = df_plain.tail(engine.lookback_days).reset_index(drop=True)
    pnf_plain = PointAndFigure(box_size=0.02, reversal=2)
    pnf_plain.build(frame_plain)
    rule0_plain = engine._step0_bc_tr_scan(frame_plain, pnf_zone=pnf_plain.congestion_zone())
    assert rule0_plain.tr_upper is not None and rule0_plain.tr_upper > 0, "TR 上沿应有效"
    fb_plain = engine._scan_false_breakout(frame_plain, rule0_plain.tr_upper)
    assert fb_plain is None, (
        f"普通 TR 无显著突破不应误报假突破, got {fb_plain}"
    )


def test_false_breakout_penalty():
    """CF-C4: 假突破数据应标记 V3TradingPlan.false_breakout=True 且信号置信度降级。"""
    df = synthetic_false_breakout(seed=42)
    engine = WyckoffEngine()
    engine._code_prefix = "TES"

    frame = df.tail(engine.lookback_days).reset_index(drop=True)
    from uniquant.brain.wyckoff.pnf import PointAndFigure

    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(frame)
    rule0 = engine._step0_bc_tr_scan(frame, pnf_zone=pnf.congestion_zone())
    step1 = engine._step1_phase_determine(frame, rule0, pnf_hint=pnf.wyckoff_phase_hint())
    step2 = engine._step2_effort_result(frame, step1)
    step3 = engine._step3_phase_c_t1(frame, step1, rule0)
    step35 = engine._step35_counterfactual(frame, step1, step2, step3, rule0)
    rr = engine._step4_risk_reward(
        frame, step1, step3, rule0, pnf_count_target=pnf.count_target()
    )
    conf = engine._calc_confidence(rule0, step1, step3, step35, rr, False)
    v3 = engine._step5_trading_plan(step1, step3, step35, rr, conf, df=frame)
    assert v3.false_breakout_detected is True, (
        "假突破数据应标记 false_breakout_detected=True"
    )
    assert v3.direction == "空仓观望", (
        f"假突破应空仓观望, got {v3.direction}"
    )


def test_false_breakout_signal_confidence_downgrade():
    """CF-C4: 端到端——假突破信号置信度应低于交易计划基础置信度 1 级。"""
    df = synthetic_false_breakout(seed=42)
    engine = WyckoffEngine()
    engine._code_prefix = "TES"

    report = engine.analyze(df, symbol="TEST.SH")
    plan_confidence = report.trading_plan.confidence.value
    signal_confidence = report.signal.confidence.value
    order = ["A", "B", "C", "D"]
    assert order.index(signal_confidence) > order.index(plan_confidence), (
        f"假突破信号置信度应降级, signal={signal_confidence} plan={plan_confidence}"
    )
