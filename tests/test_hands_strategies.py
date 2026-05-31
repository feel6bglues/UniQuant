from types import SimpleNamespace

import pandas as pd
import pytest

from uniquant.hands.strategies.base import HAS_BACKTRADER, BaseStrategy, logger as strategy_logger

bt = None
FSMStrategy = None
if HAS_BACKTRADER:
    import backtrader as bt
    from uniquant.hands.strategies.fsm_strategy import FSMStrategy


@pytest.mark.skipif(not HAS_BACKTRADER, reason="backtrader is not installed")
class TestHandsStrategiesWithBacktrader:
    def test_base_strategy_uses_named_params_for_logging(self, monkeypatch):
        logged = []

        def fake_info(message):
            logged.append(message)

        strategy = SimpleNamespace(
            params=SimpleNamespace(verbose=True),
            datas=[SimpleNamespace(datetime=SimpleNamespace(date=lambda _: pd.Timestamp("2024-01-02").date()))],
        )
        monkeypatch.setattr(strategy_logger, "info", fake_info)

        BaseStrategy.log(strategy, "test message")

        assert logged == ["[2024-01-02] test message"]

    def test_fsm_strategy_initializes_with_backtrader_named_params(self):
        df = pd.DataFrame(
            {
                "open": list(range(1, 80)),
                "high": list(range(2, 81)),
                "low": list(range(1, 80)),
                "close": list(range(1, 80)),
                "volume": [1000] * 79,
            },
            index=pd.date_range("2024-01-01", periods=79, freq="D"),
        )

        cerebro = bt.Cerebro(stdstats=False)
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        cerebro.addstrategy(FSMStrategy, verbose=False, ma_short=5, ma_long=10)

        result = cerebro.run()
        strategy = result[0]

        assert len(result) == 1
        assert strategy.params.ma_short == 5
        assert strategy.params.ma_long == 10
        assert strategy.ma20 is not None
        assert strategy.ma60 is not None
