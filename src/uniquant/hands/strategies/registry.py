from uniquant.hands.strategies.ma_cross import trade_ma
from uniquant.hands.strategies.regime import trade_regime
from uniquant.hands.strategies.str_reversal import trade_str_reversal
from uniquant.hands.strategies.wyckoff import trade_wyckoff

STRATEGY_MAP = {
    "wyckoff": trade_wyckoff,
    "ma_atr": trade_ma,
    "ma_cross": trade_ma,
    "reversal": trade_str_reversal,
    "str_reversal": trade_str_reversal,
    "regime": trade_regime,
}
