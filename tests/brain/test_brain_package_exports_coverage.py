"""第九轮（2026-10-17）覆盖率补测：``brain/__init__.py``。

``brain`` 包对 6 个可选子包采用 ``try/except ImportError`` 回退
（``Indicators`` / ``NTFEngine`` / ``RegimeDetector`` / ``AlphaDecoupler`` /
``StockScreener`` / 4 个 factors 符号）。在当前依赖集下这些子包**均可导入**，
故回退分支在常规测试中永不触发。

本文件通过把相关子模块在 ``sys.modules`` 中置为 ``None``（CPython 语义：导入
命中 ``None`` ⇒ 抛 ``ImportError``）来**真实触发**这 6 条回退分支（模拟缺失
可选依赖），断言：

* 每个回退符号被置为 ``None``；
* 无保护的 ``from .fsm.fsm import ...``（FSM/FSMState/DecisionBrain）**不受影响**；
* ``__all__`` 完整；
* 测试结束**原样恢复** ``sys.modules`` 与模块对象，不影响后续用例。

不触网、不读数据湖、不依赖 czsc/backtrader。

未覆盖项（**不可达防御**）：无——6 条回退分支全部可达并被本文件命中。
"""

from __future__ import annotations

import importlib
import sys

#: 触发回退的子包前缀
_FALLBACK_PREFIXES = (
    "uniquant.brain.indicators",
    "uniquant.brain.ntf",
    "uniquant.brain.regime",
    "uniquant.brain.alpha_decoupler",
    "uniquant.brain.screener",
    "uniquant.brain.factors",
)

_FALLBACK_SYMBOLS = (
    "Indicators",
    "NTFEngine",
    "RegimeDetector",
    "AlphaDecoupler",
    "StockScreener",
    "FactorRegistry",
    "FactorAnalyzer",
    "FactorComposer",
    "FinancialFactorBridge",
)

_PROTECTED_SYMBOLS = ("FSM", "FSMState", "DecisionBrain")


def _matching_keys() -> list:
    return [
        name
        for name in sys.modules
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in _FALLBACK_PREFIXES
        )
    ]


def test_import_error_fallbacks_set_none_and_restore() -> None:
    import uniquant.brain as brain_mod

    saved = {name: sys.modules[name] for name in _matching_keys()}
    assert saved, "expected the optional subpackages to be imported already"

    for name in saved:
        sys.modules[name] = None  # CPython: None entry ⇒ ImportError on import
    try:
        reloaded = importlib.reload(brain_mod)

        # 6 条回退分支全部执行 ⇒ 相关符号为 None
        for sym in _FALLBACK_SYMBOLS:
            assert getattr(reloaded, sym) is None, f"{sym} should be None on fallback"

        # 无保护导入不受影响（正对照，证明只有目标子包被人为破坏）
        for sym in _PROTECTED_SYMBOLS:
            assert getattr(reloaded, sym) is not None

        # __all__ 无损
        assert set(reloaded.__all__) >= set(_FALLBACK_SYMBOLS) | set(_PROTECTED_SYMBOLS)
    finally:
        for name, mod in saved.items():
            sys.modules[name] = mod
        restored = importlib.reload(brain_mod)

    # 复原后符号必须全部可用，且 sys.modules 仍是同一模块对象
    assert sys.modules["uniquant.brain"] is brain_mod
    for sym in _FALLBACK_SYMBOLS:
        assert getattr(restored, sym) is not None, f"{sym} failed to restore"


def test_normal_import_exposes_all_symbols() -> None:
    """正对照：常规导入下 6 个子包符号均可用（回退分支未触发）。"""
    import uniquant.brain as brain_mod

    for sym in _FALLBACK_SYMBOLS + _PROTECTED_SYMBOLS:
        assert hasattr(brain_mod, sym)
        assert getattr(brain_mod, sym) is not None
