"""第八轮（2026-10-17）死代码剪除守卫。

第八轮从 ``hands/`` 层物理删除了两组**已被 AST 核验为无消费者**的模块：

(A) 零引用孤岛（在 ``src/`` + ``tests/`` + ``scripts/`` 中均无导入方）::

    hands/backtest/report_generator.py     （117 stmts，0% 覆盖）
    hands/backtest/benchmark.py            （ 47 stmts，0% 覆盖）
    hands/backtest/trade_analysis/         （整包 173 stmts，0% 覆盖）

    职责已由**在线的** ``services/analysis/report_generator_engine.py`` +
    ``hands/results_manager.py`` + ``hands/reporter.py`` 承接。

(B) 类式（backtrader）策略子集——**真实分支永久不可达**::

    hands/strategies/base.py
    hands/strategies/fsm_strategy.py
    hands/strategies/ma_atr_strategy.py
    hands/strategies/regime_strategy.py
    hands/strategies/reversal_strategy.py
    hands/strategies/wyckoff_strategy.py

    ``backtrader`` 既未声明于 ``pyproject.toml`` 任何依赖集、也从未安装，
    ``HAS_BACKTRADER`` 在 CI 与开发机上恒为 ``False``（长期只跑 Mock 回退）；
    生产/研究链路无消费者，唯一暴露点是 ``hands.strategies.__getattr__`` 兼容垫片。

本守卫以"**文件不存在 + 模块不可导入 + 兼容垫片已移除**"三重断言锁死删除结果，
并附**正对照**（幸存模块必须存在且可导入）以防守卫空转。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDS_DIR = REPO_ROOT / "src" / "uniquant" / "hands"

# --- 被删除的物理文件/目录 -------------------------------------------------
PRUNED_PATHS = (
    "backtest/report_generator.py",
    "backtest/benchmark.py",
    "backtest/trade_analysis",
    "backtest/trade_analysis/__init__.py",
    "backtest/trade_analysis/analyzer.py",
    "backtest/trade_analysis/statistics.py",
    "strategies/base.py",
    "strategies/fsm_strategy.py",
    "strategies/ma_atr_strategy.py",
    "strategies/regime_strategy.py",
    "strategies/reversal_strategy.py",
    "strategies/wyckoff_strategy.py",
)

# --- 应不可导入的模块 -------------------------------------------------------
PRUNED_MODULES = (
    "uniquant.hands.backtest.report_generator",
    "uniquant.hands.backtest.benchmark",
    "uniquant.hands.backtest.trade_analysis",
    "uniquant.hands.backtest.trade_analysis.analyzer",
    "uniquant.hands.backtest.trade_analysis.statistics",
    "uniquant.hands.strategies.base",
    "uniquant.hands.strategies.fsm_strategy",
    "uniquant.hands.strategies.ma_atr_strategy",
    "uniquant.hands.strategies.regime_strategy",
    "uniquant.hands.strategies.reversal_strategy",
    "uniquant.hands.strategies.wyckoff_strategy",
)

# --- 幸存模块（正对照：必须存在且可导入） -----------------------------------
SURVIVING_MODULES = (
    "uniquant.hands",
    "uniquant.hands.backtest",
    "uniquant.hands.backtest.unified_engine",
    "uniquant.hands.backtest.unified_matching_engine",
    "uniquant.hands.backtest.result",
    "uniquant.hands.backtest.monte_carlo",
    "uniquant.hands.backtest.overfitting_detector",
    "uniquant.hands.backtest.robustness_checker",
    "uniquant.hands.backtest.sensitivity_analyzer",
    "uniquant.hands.strategies",
    "uniquant.hands.strategies.registry",
    "uniquant.hands.strategies.wyckoff",
    "uniquant.hands.strategies.ma_cross",
    "uniquant.hands.strategies.regime",
    "uniquant.hands.strategies.str_reversal",
)


@pytest.mark.parametrize("rel_path", PRUNED_PATHS)
def test_round8_pruned_paths_do_not_exist(rel_path: str) -> None:
    """被删除的文件/目录不得重新出现在磁盘上。"""
    assert not (HANDS_DIR / rel_path).exists(), (
        f"第八轮已删除 {rel_path}，不应重新出现（见 AGENTS.md 第八轮）"
    )


@pytest.mark.parametrize("module", PRUNED_MODULES)
def test_round8_pruned_modules_are_not_importable(module: str) -> None:
    """被删除的模块不得可导入（ImportError 家族）。"""
    with pytest.raises(ImportError):
        importlib.import_module(module)


@pytest.mark.parametrize("module", SURVIVING_MODULES)
def test_round8_surviving_modules_still_importable(module: str) -> None:
    """正对照：幸存模块必须仍可导入——防止守卫因整体损坏而空转。"""
    assert importlib.import_module(module) is not None


def test_round8_strategy_map_still_exposed_and_populated() -> None:
    """函数式策略注册表必须仍然可用（类式策略的替代物）。"""
    from uniquant.hands.strategies import STRATEGY_MAP

    assert isinstance(STRATEGY_MAP, dict)
    assert STRATEGY_MAP, "STRATEGY_MAP 不应为空"
    for name, fn in STRATEGY_MAP.items():
        assert callable(fn), f"STRATEGY_MAP[{name!r}] 必须是可调用策略函数"


@pytest.mark.parametrize(
    "obsolete_attr",
    ["BaseStrategy", "FSMStrategy", "WyckoffStrategy", "RegimeStrategy", "ReversalStrategy", "MaAtrStrategy"],
)
def test_round8_strategies_shim_no_longer_exposes_classes(obsolete_attr: str) -> None:
    """``hands.strategies`` 惰性垫片不得再暴露已删除的类式策略。"""
    import uniquant.hands.strategies as strategies_pkg

    with pytest.raises(AttributeError):
        getattr(strategies_pkg, obsolete_attr)


def test_round8_backtest_package_has_no_dangling_symbols() -> None:
    """``hands.backtest`` 不得再导出已删除模块的符号。"""
    import uniquant.hands.backtest as backtest_pkg

    for obsolete in ("BacktestReportGenerator", "BenchmarkComparator", "TradeAnalyzer", "TradeStatistics"):
        assert not hasattr(backtest_pkg, obsolete), f"hands.backtest 仍导出已删除符号 {obsolete}"
