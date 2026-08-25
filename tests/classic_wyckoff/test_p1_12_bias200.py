"""P1-12 bias200 修复回归验证 (2026-08-14 数据核验发现)。

修复前: _build_report 收到 frame.tail(lookback=120)，len(df)>=200 恒 False
        → bias200 恒 0.0 (标注字段失效)。
修复后: _analyze_single 在截断前保存 full_frame，bias200 基于全量 frame 的 MA200 计算。
本测试验证 ≥200 根 K 线输入下 bias200 非零且等于手工 MA200 偏离。
"""

import pandas as pd
import pytest

from scripts.wyckoff_fixtures import synthetic_accumulation
from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.shared.interfaces import WyckoffOutput


def _extend_to_n_rows(df: pd.DataFrame, n: int = 220) -> pd.DataFrame:
    """向前延伸序列到 n 根 K 线（保持趋势一致，日期单调递增）。"""
    base = df.copy()
    if len(base) >= n:
        return base.tail(n).reset_index(drop=True)
    extra = n - len(base)
    head = base.head(extra).copy()
    rng = pd.bdate_range(end=head["date"].iloc[0] - pd.Timedelta(days=1), periods=extra)
    head["date"] = rng
    return pd.concat([head, base], ignore_index=True).tail(n).reset_index(drop=True)


@pytest.fixture(autouse=True)
def _bias_deterministic(monkeypatch):
    def fake_get_config():
        class _C:
            def get(self, k, d=None):
                return {
                    "wyckoff.wss_enabled": False,
                    "wyckoff.wss_lookup_path": "",
                    "wyckoff.structural_adjust_enabled": False,
                }.get(k, d)
        return _C()
    monkeypatch.setattr("uniquant.brain.wyckoff.engine.get_config", fake_get_config)


class TestBias200Annotation:
    def test_bias200_nonzero_with_long_history(self):
        df = _extend_to_n_rows(synthetic_accumulation(seed=42), n=220)
        assert len(df) >= 200
        report = WyckoffEngine().analyze(df, symbol="T")
        ma200 = float(df["close"].tail(200).mean())
        expected = round((float(df["close"].iloc[-1]) - ma200) / ma200, 4)
        assert report.bias200 != 0.0
        assert report.bias200 == expected

    def test_bias200_zero_with_short_history(self):
        df = synthetic_accumulation(seed=42)
        assert len(df) < 200
        report = WyckoffEngine().analyze(df, symbol="T")
        assert report.bias200 == 0.0

    def test_bias200_in_output_dict(self):
        from unittest.mock import MagicMock
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine
        df = _extend_to_n_rows(synthetic_accumulation(seed=42), n=220)
        report = WyckoffEngine().analyze(df, symbol="T")
        svc = WyckoffAnalysisEngine(orchestrator=MagicMock())
        out = svc._extract_from_report(report, price=float(df["close"].iloc[-1]))
        d = out.to_dict()
        assert "bias200" in d
        assert d["bias200"] == report.bias200
        assert WyckoffOutput.from_dict(d).bias200 == report.bias200