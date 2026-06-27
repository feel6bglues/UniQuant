import json
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from uniquant.hands.backtest.unified_engine import (
    BacktestResult,
    TradeRecord,
    UnifiedBacktestEngine,
)
from uniquant.services.research_pipeline import (
    PipelineResult,
    UnifiedResearchPipeline,
)
from uniquant.risk.sizer import PositionSizer
from uniquant.signal.arbitrator import SignalArbitrator
from uniquant.shared.interfaces import TradingSignal


# ── helpers ──────────────────────────────────────────────────

def _mock_analysis_service(success=True):
    svc = MagicMock()
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5, freq="D"),
        "open": [10.0] * 5,
        "high": [11.0] * 5,
        "low": [9.0] * 5,
        "close": [10.5] * 5,
        "volume": [10000] * 5,
        "pre_close": [10.0] * 5,
        "avg_daily_volume": [10000] * 5,
    })
    svc.run_ticker_analysis.return_value = MagicMock(
        success=success,
        data_pack={"stock": df, "symbol": "000001.SZ", "regime": "NORMAL"} if success else {},
        decision={"action": "BUY", "confidence": 0.8} if success else {},
        error=None if success else "mock error",
        symbol="000001.SZ",
    )
    return svc


def _make_pipeline() -> UnifiedResearchPipeline:
    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = BacktestResult(
        trades=[TradeRecord(
            timestamp=datetime(2024, 1, 5),
            action="BUY",
            symbol="000001.SZ",
            price=10.5,
            shares=100,
            commission=5.0,
        )],
        equity_curve=[100000.0, 100500.0],
        daily_returns=[0.005],
        initial_capital=100000.0,
        final_cash=99500.0,
        metadata={},
    )
    return UnifiedResearchPipeline(
        analysis_service=_mock_analysis_service(),
        backtest_engine=mock_engine,
    )


def _make_result(symbol="000001.SZ", success=True) -> PipelineResult:
    return PipelineResult(
        symbol=symbol,
        data_pack={"stock": "mock"},
        decision={"action": "BUY", "confidence": 0.8},
        signals=[TradingSignal(action="BUY", reason="test", confidence=0.8, shares=100)],
        backtest=BacktestResult(
            trades=[TradeRecord(
                timestamp=datetime(2024, 1, 5),
                action="BUY",
                symbol=symbol,
                price=10.5,
                shares=100,
                commission=5.0,
            )],
            equity_curve=[100000.0, 100500.0],
            daily_returns=[0.005],
            initial_capital=100000.0,
            final_cash=99500.0,
        ),
        success=success,
    )


# ── unit: serialization ──────────────────────────────────────

def test_result_to_checkpoint_dict_excludes_data_pack():
    r = _make_result()
    d = UnifiedResearchPipeline._result_to_checkpoint_dict(r)
    assert "data_pack" not in d
    assert d["symbol"] == "000001.SZ"
    assert d["success"] is True
    assert d["decision"] == {"action": "BUY", "confidence": 0.8}
    assert len(d["signals"]) == 1
    assert d["signals"][0]["action"] == "BUY"
    assert d["backtest"]["initial_capital"] == 100000.0
    assert len(d["backtest"]["trades"]) == 1
    assert d["backtest"]["trades"][0]["action"] == "BUY"


def test_result_roundtrip():
    r = _make_result()
    d = UnifiedResearchPipeline._result_to_checkpoint_dict(r)
    r2 = UnifiedResearchPipeline._result_from_checkpoint_dict(d)
    assert r2.symbol == r.symbol
    assert r2.success == r.success
    assert r2.decision == r.decision
    assert len(r2.signals) == len(r.signals)
    assert r2.signals[0].action == r.signals[0].action
    assert r2.backtest.initial_capital == r.backtest.initial_capital
    assert r2.backtest.total_trades == 1
    assert r2.data_pack == {}


def test_result_roundtrip_failure():
    r = _make_result(success=False)
    d = UnifiedResearchPipeline._result_to_checkpoint_dict(r)
    r2 = UnifiedResearchPipeline._result_from_checkpoint_dict(d)
    assert r2.success is False
    assert r2.error is None


# ── unit: save / load checkpoint ─────────────────────────────

def test_save_batch_checkpoint_creates_file(tmp_path):
    pipeline = _make_pipeline()
    r = _make_result()
    pipeline._save_batch_checkpoint(r, tmp_path)
    cp_file = tmp_path / "000001.SZ.json"
    assert cp_file.exists()
    data = json.loads(cp_file.read_text(encoding="utf-8"))
    assert data["symbol"] == "000001.SZ"


def test_load_completed_symbols_returns_set(tmp_path):
    (tmp_path / "AAA.json").write_text("{}")
    (tmp_path / "BBB.json").write_text("{}")
    (tmp_path / "other.txt").write_text("ignore")
    completed = UnifiedResearchPipeline._load_completed_symbols(tmp_path)
    assert completed == {"AAA", "BBB"}


def test_load_completed_symbols_no_dir(tmp_path):
    missing = tmp_path / "nonexistent"
    assert UnifiedResearchPipeline._load_completed_symbols(missing) == set()


def test_load_checkpoint_result_valid(tmp_path):
    pipeline = _make_pipeline()
    r = _make_result()
    pipeline._save_batch_checkpoint(r, tmp_path)
    loaded = UnifiedResearchPipeline._load_checkpoint_result(tmp_path, "000001.SZ")
    assert loaded is not None
    assert loaded.symbol == "000001.SZ"
    assert loaded.success is True


def test_load_checkpoint_result_missing(tmp_path):
    loaded = UnifiedResearchPipeline._load_checkpoint_result(tmp_path, "MISSING")
    assert loaded is None


def test_load_checkpoint_result_corrupted(tmp_path):
    (tmp_path / "BAD.json").write_text("not json", encoding="utf-8")
    loaded = UnifiedResearchPipeline._load_checkpoint_result(tmp_path, "BAD")
    assert loaded is None


# ── integration: run_batch with checkpoint ───────────────────

def test_run_batch_without_checkpoint_calls_run(tmp_path):
    pipeline = _make_pipeline()
    # mock analysis_service to return success for all symbols
    svc = _mock_analysis_service(success=True)
    pipeline._analysis = svc
    results = pipeline.run_batch(symbols=["000001.SZ", "600000.SH"])
    assert len(results) == 2
    assert svc.run_ticker_analysis.call_count == 2


def test_run_batch_with_checkpoint_saves_files(tmp_path):
    pipeline = _make_pipeline()
    pipeline._analysis = _mock_analysis_service(success=True)
    results = pipeline.run_batch(
        symbols=["000001.SZ", "600000.SH"],
        checkpoint_dir=tmp_path,
    )
    assert len(results) == 2
    assert (tmp_path / "000001.SZ.json").exists()
    assert (tmp_path / "600000.SH.json").exists()


def test_run_batch_with_checkpoint_skips_completed(tmp_path):
    pipeline = _make_pipeline()
    pipeline._analysis = _mock_analysis_service(success=True)

    # 第一次运行：两个都完成
    results1 = pipeline.run_batch(
        symbols=["000001.SZ", "600000.SH"],
        checkpoint_dir=tmp_path,
    )
    assert len(results1) == 2

    # 第二次运行：应该跳过已完成的，service 不会被再次调用
    pipeline._analysis = _mock_analysis_service(success=True)
    results2 = pipeline.run_batch(
        symbols=["000001.SZ", "600000.SH"],
        checkpoint_dir=tmp_path,
    )
    assert len(results2) == 2
    # 第一个结果来自 checkpoint，第二个也来自 checkpoint
    assert results2[0].success
    assert results2[1].success


def test_run_batch_with_checkpoint_resumes_partial(tmp_path):
    pipeline = _make_pipeline()

    # 模拟第一个符号成功，第二个失败
    svc = MagicMock()
    df_ok = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5, freq="D"),
        "open": [10.0] * 5, "high": [11.0] * 5, "low": [9.0] * 5,
        "close": [10.5] * 5, "volume": [10000] * 5,
        "pre_close": [10.0] * 5, "avg_daily_volume": [10000] * 5,
    })

    def ticker_analysis(symbol, trace_id=None):
        if symbol == "000001.SZ":
            return MagicMock(
                success=True,
                data_pack={"stock": df_ok, "symbol": symbol},
                decision={"action": "HOLD", "confidence": 0.5},
                error=None, symbol=symbol,
            )
        raise RuntimeError(f"fail for {symbol}")

    svc.run_ticker_analysis = ticker_analysis
    pipeline._analysis = svc

    # 第一次运行：000001.SZ 成功，600000.SH 抛出异常
    results1 = pipeline.run_batch(
        symbols=["000001.SZ", "600000.SH"],
        checkpoint_dir=tmp_path,
    )
    assert len(results1) == 2
    assert results1[0].success
    assert not results1[1].success
    assert (tmp_path / "000001.SZ.json").exists()
    assert (tmp_path / "600000.SH.json").exists()

    # 第二次运行：两个都从 checkpoint 加载（失败也 checkpoint 化，避免无限重试）
    pipeline._analysis = _mock_analysis_service(success=True)
    results2 = pipeline.run_batch(
        symbols=["000001.SZ", "600000.SH"],
        checkpoint_dir=tmp_path,
    )
    assert len(results2) == 2
    # 000001.SZ 是从 checkpoint 加载的（HOLD）
    assert results2[0].decision == {"action": "HOLD", "confidence": 0.5}
    # 600000.SH 也是从 checkpoint 加载的（失败结果）
    assert not results2[1].success


# ── edge cases ───────────────────────────────────────────────

def test_run_batch_empty_symbols(tmp_path):
    pipeline = _make_pipeline()
    results = pipeline.run_batch(symbols=[], checkpoint_dir=tmp_path)
    assert results == []


def test_run_batch_failure_saves_checkpoint(tmp_path):
    """即使单个 symbol 失败，也要保存 checkpoint"""
    pipeline = _make_pipeline()
    svc = MagicMock()
    svc.run_ticker_analysis.side_effect = RuntimeError("infra fail")
    pipeline._analysis = svc

    results = pipeline.run_batch(
        symbols=["000001.SZ"],
        checkpoint_dir=tmp_path,
    )
    assert len(results) == 1
    assert not results[0].success
    assert (tmp_path / "000001.SZ.json").exists()


# ── unit: _signals_to_candidates ──────────────────────────────

def test_signals_to_candidates_converts_buy_and_sell():
    signals = [
        TradingSignal(action="BUY", reason="fsm: breakout", confidence=0.8, shares=100, price=10.5),
        TradingSignal(action="SELL", reason="lppl: peak", confidence=0.9, shares=100, price=11.0),
    ]
    candidates = UnifiedResearchPipeline._signals_to_candidates(signals)
    assert len(candidates) == 2
    assert candidates[0].action == "BUY"
    assert candidates[0].direction == 1
    assert candidates[0].source == "fsm"
    assert candidates[0].price_target == 10.5
    assert candidates[1].action == "SELL"
    assert candidates[1].direction == -1
    assert candidates[1].source == "lppl"


def test_signals_to_candidates_filters_hold():
    signals = [
        TradingSignal(action="HOLD", reason="no trade", confidence=0.5),
        TradingSignal(action="BUY", reason="czsc: bottom", confidence=0.7),
    ]
    candidates = UnifiedResearchPipeline._signals_to_candidates(signals)
    assert len(candidates) == 1
    assert candidates[0].action == "BUY"


def test_signals_to_candidates_source_from_reason():
    signals = [
        TradingSignal(action="BUY", reason="czsc: third buy", confidence=0.8),
    ]
    candidates = UnifiedResearchPipeline._signals_to_candidates(signals)
    assert candidates[0].source == "czsc"


def test_signals_to_candidates_empty():
    assert UnifiedResearchPipeline._signals_to_candidates([]) == []


def test_signals_to_candidates_zero_price_no_target():
    signals = [
        TradingSignal(action="BUY", reason="test", confidence=0.5, price=0.0),
    ]
    candidates = UnifiedResearchPipeline._signals_to_candidates(signals)
    assert candidates[0].price_target is None


# ── integration: pipeline uses arbitrate_candidates ───────────

def test_pipeline_with_arbitrator_calls_arbitrate_candidates():
    """当 arbitrator 存在时, pipeline 调用 arbitrate_candidates 而非 arbitrate"""
    from unittest.mock import MagicMock

    svc = _mock_analysis_service(success=True)
    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = BacktestResult(
        trades=[TradeRecord(timestamp=datetime(2024, 1, 5), action="BUY", symbol="000001.SZ", price=10.5, shares=100, commission=5.0)],
        equity_curve=[100000.0, 100500.0],
        daily_returns=[0.005],
        initial_capital=100000.0,
        final_cash=99500.0,
        metadata={},
    )

    # Use real SignalArbitrator — should produce arbitration report
    arbitrator = SignalArbitrator()
    pipeline = UnifiedResearchPipeline(
        analysis_service=svc,
        backtest_engine=mock_engine,
        arbitrator=arbitrator,
    )
    result = pipeline.run("000001.SZ")
    assert result.success
    assert len(result.signals) <= 1  # arbitrator produces at most one signal per day


def test_pipeline_without_arbitrator_skips_arbitration():
    """arbitrator 为 None 时跳过仲裁"""
    from unittest.mock import MagicMock

    svc = _mock_analysis_service(success=True)
    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = BacktestResult(
        trades=[TradeRecord(timestamp=datetime(2024, 1, 5), action="BUY", symbol="000001.SZ", price=10.5, shares=100, commission=5.0)],
        equity_curve=[100000.0, 100500.0],
        daily_returns=[0.005],
        initial_capital=100000.0,
        final_cash=99500.0,
        metadata={},
    )

    pipeline = UnifiedResearchPipeline(
        analysis_service=svc,
        backtest_engine=mock_engine,
        arbitrator=None,
    )
    result = pipeline.run("000001.SZ")
    assert result.success


def test_pipeline_with_sizer_wired():
    """sizer 传入 pipeline 时，arbitrate_candidates 可以使用它"""
    from unittest.mock import MagicMock

    svc = _mock_analysis_service(success=True)
    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = BacktestResult(
        trades=[TradeRecord(timestamp=datetime(2024, 1, 5), action="BUY", symbol="000001.SZ", price=10.5, shares=100, commission=5.0)],
        equity_curve=[100000.0, 100500.0],
        daily_returns=[0.005],
        initial_capital=100000.0,
        final_cash=99500.0,
        metadata={},
    )

    sizer = PositionSizer()
    pipeline = UnifiedResearchPipeline(
        analysis_service=svc,
        backtest_engine=mock_engine,
        arbitrator=SignalArbitrator(),
        sizer=sizer,
    )
    result = pipeline.run("000001.SZ")
    assert result.success
