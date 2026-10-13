"""
撮合执行层含真实成交基线回归测试 (Execution Benchmark Guard)
=========================================================

防止基线因 total_trades == 0 陷入空转。
基于 tests/benchmark/baseline_execution_v0.parquet 与 golden_execution.txt，
对 UnifiedBacktestEngine 的撮合、执行、费率（印花税/佣金/过户费/滑点）、
PnL 核算及资金曲线更新实施零回归数值锁定。
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from uniquant.hands.backtest.unified_engine import (
    UnifiedBacktestEngine,
    TradingSignal,
)

BASELINE_FILE = Path("tests/benchmark/baseline_execution_v0.parquet")
GOLDEN_LIST_FILE = Path("tests/benchmark/golden_execution.txt")


def load_golden_execution_symbols() -> list[str]:
    if not GOLDEN_LIST_FILE.exists():
        return ["000001.SZ", "600519.SH", "601318.SH", "000858.SZ", "300750.SZ"]
    symbols = []
    with open(GOLDEN_LIST_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                symbols.append(line.split("#")[0].strip())
    return symbols


class TestExecutionBenchmark:
    """撮合与执行基准测试套件"""

    def test_execution_baseline_file_integrity(self):
        """基线文件完整性：存在、5 只股票、每只成交笔数 > 0"""
        assert BASELINE_FILE.exists(), f"执行基线文件缺失: {BASELINE_FILE}"
        df = pd.read_parquet(BASELINE_FILE)

        assert len(df) == 5
        assert set(df["symbol"]) == set(load_golden_execution_symbols())
        assert (df["total_trades"] > 0).all(), "基线必须全量包含真实成交记录，严禁 0 成交"
        assert df["total_trades"].sum() >= 50, "基线总成交样本数应 >= 50"

        for _, row in df.iterrows():
            assert len(row["trades"]) == row["total_trades"]
            # 抽检首笔交易字段完整
            trade = row["trades"][0]
            assert "action" in trade and trade["action"] in ("BUY", "SELL")
            assert "price" in trade and trade["price"] > 0
            assert "shares" in trade and trade["shares"] > 0
            assert "commission" in trade and trade["commission"] >= 5.0
            assert "stamp_duty" in trade
            assert "pnl" in trade

    def test_execution_replay_zero_regression(self):
        """
        确定性回放回归：在 2023 冻结历史区间重跑 UnifiedBacktestEngine，
        断言成交数、收益率、最终现金、逐笔 TradeRecord 与资金曲线 100% 零回归。
        """
        assert BASELINE_FILE.exists()
        baseline_df = pd.read_parquet(BASELINE_FILE).set_index("symbol")

        engine = UnifiedBacktestEngine(initial_capital=500_000.0)

        for symbol in load_golden_execution_symbols():
            quote_path = Path(f"data/lake/quotes/daily/{symbol}.parquet")
            if not quote_path.exists():
                pytest.skip(f"缺少日线数据: {quote_path}")

            df = pd.read_parquet(quote_path)
            df["date_dt"] = pd.to_datetime(df["date"])
            sub_df = df[(df["date_dt"] >= "2023-01-01") & (df["date_dt"] <= "2023-12-31")].reset_index(drop=True)
            sub_df["ma5"] = sub_df["close"].rolling(5).mean()
            sub_df["ma20"] = sub_df["close"].rolling(20).mean()

            signals = []
            holding = False
            shares = 100 if symbol == "600519.SH" else 500
            for idx in range(20, len(sub_df) - 1):
                row = sub_df.iloc[idx]
                date = row["date"]
                if row["ma5"] > row["ma20"] and not holding:
                    signals.append(TradingSignal(action="BUY", symbol=symbol, shares=shares, timestamp=date, reason="MA_CROSS_BUY"))
                    holding = True
                elif row["ma5"] < row["ma20"] and holding:
                    signals.append(TradingSignal(action="SELL", symbol=symbol, shares=shares, timestamp=date, reason="MA_CROSS_SELL"))
                    holding = False

            current_res = engine.run(df=sub_df, signals=signals, symbol=symbol)
            base_row = baseline_df.loc[symbol]

            # 1. 标量完全一致
            assert current_res.total_trades == base_row["total_trades"], f"{symbol} 成交笔数不一致"
            assert current_res.total_trades > 0, f"{symbol} 成交数必须 > 0"
            assert np.isclose(current_res.total_return, base_row["total_return"], rtol=1e-7)
            assert np.isclose(current_res.final_cash, base_row["final_cash"], rtol=1e-7)

            # 2. 资金曲线与日收益逐点一致
            assert len(current_res.equity_curve) == base_row["equity_curve_len"]
            np.testing.assert_allclose(current_res.equity_curve, base_row["equity_curve"], rtol=1e-7)

            # 3. 逐笔成交明细逐点一致
            assert len(current_res.trades) == len(base_row["trades"])
            for t_cur, t_base in zip(current_res.trades, base_row["trades"]):
                assert t_cur.action == t_base["action"]
                assert t_cur.shares == t_base["shares"]
                assert np.isclose(t_cur.price, t_base["price"], rtol=1e-7)
                assert np.isclose(t_cur.commission, t_base["commission"], rtol=1e-7)
                base_stamp = t_base.get("stamp_duty", t_base.get("stamp_tax", 0.0))
                assert np.isclose(getattr(t_cur, "stamp_duty", 0.0), base_stamp, rtol=1e-7)
                assert np.isclose(getattr(t_cur, "pnl", 0.0), t_base.get("pnl", 0.0), rtol=1e-7)
