"""策略模块（函数式策略注册表）。

本包只保留**函数式**策略及其注册表 ``registry.STRATEGY_MAP``：

- ``ma_cross.trade_ma``                 （注册名 ``ma_cross`` / ``ma_atr``）
- ``wyckoff.trade_wyckoff``             （注册名 ``wyckoff``）
- ``regime.trade_regime``               （注册名 ``regime``）
- ``str_reversal.trade_str_reversal``   （注册名 ``reversal`` / ``str_reversal``）

**第八轮（2026-10-17）剪除**: 类式（backtrader）策略 ``base`` / ``fsm_strategy`` /
``ma_atr_strategy`` / ``regime_strategy`` / ``reversal_strategy`` /
``wyckoff_strategy`` 已物理删除。理由——``backtrader`` 既未声明于
``pyproject.toml`` 任何依赖集、也从未安装，``HAS_BACKTRADER`` 恒为 ``False``，
其 ``if HAS_BACKTRADER:`` 分支在 CI 与开发机上**永久不可达**；生产/研究链路均无
消费者（唯一暴露点是本包此前的 ``__getattr__`` 兼容垫片）。详见 ``AGENTS.md``
第八轮与
``docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md``
§7.11。
"""

__all__: list[str] = ["STRATEGY_MAP"]


def __getattr__(name: str):
    """惰性导入，避免导入本包即触发 pandas / 指标计算的副作用。"""
    if name == "STRATEGY_MAP":
        from uniquant.hands.strategies.registry import STRATEGY_MAP

        return STRATEGY_MAP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
