"""第九轮（2026-10-17）死代码剪除守卫。

第九轮从 ``brain/`` 层物理删除了两个**经 AST 核验为全仓零消费者**的模块
（扫描范围 ``src/`` + ``tests/`` + ``scripts/`` + 已入库的 ``scratch/``）::

    brain/lppl/computation.py    （242 stmts，0% 覆盖）
    brain/wyckoff/trading.py     （ 49 stmts，0% 覆盖）

删除依据（与第八轮同纪律）:

(A) ``brain/lppl/computation.py`` —— 旧版 LPPL 全市场批量扫描器
    （joblib / ProcessPoolExecutor 并行拟合 + markdown 报告），
    其能力已由**在线的** ``lppl/engine.py``（``LPPLEngine`` /
    ``fit_single_window`` / ``calculate_risk_level``）与
    ``lppl/calculator.py``（``LPPLCalculator``）承接；
    唯一的消费者脚本 ``scripts/lppl_wyckoff_cross_validation.py``
    实际导入的是 ``LPPLEngine`` / ``LPPLCalculator``，**不**导入本模块。
    全仓检索 ``LPPLComputation`` / ``fit_single_window_task`` /
    ``get_optimal_workers`` / ``performance_monitor`` 无任何引用方。

(B) ``brain/wyckoff/trading.py`` —— 供"测试脚本"模拟 Wyckoff 交易执行的
    工具函数（``calculate_wyckoff_return``），但**没有任何测试或脚本导入它**
    （全仓检索 ``calculate_wyckoff_return`` 零命中）。回测/成交模拟职责由
    ``hands/backtest/unified_engine.py`` + ``unified_matching_engine.py`` 承接。

本守卫以"**文件不存在 + 模块不可导入 + 存活包无悬空符号**"三重断言锁死删除结果，
并附**正对照**（幸存模块必须存在且可导入）以防守卫空转。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN_DIR = REPO_ROOT / "src" / "uniquant" / "brain"

# --- 被删除的物理文件 -------------------------------------------------------
PRUNED_PATHS = (
    "lppl/computation.py",
    "wyckoff/trading.py",
)

# --- 应不可导入的模块 -------------------------------------------------------
PRUNED_MODULES = (
    "uniquant.brain.lppl.computation",
    "uniquant.brain.wyckoff.trading",
)

# --- 幸存模块（正对照：必须存在且可导入） -----------------------------------
SURVIVING_MODULES = (
    "uniquant.brain",
    "uniquant.brain.lppl",
    "uniquant.brain.lppl.engine",
    "uniquant.brain.lppl.calculator",
    "uniquant.brain.lppl.core",
    "uniquant.brain.lppl.multifit",
    "uniquant.brain.lppl.data_manager",
    "uniquant.brain.wyckoff",
    "uniquant.brain.wyckoff.engine",
    "uniquant.brain.wyckoff.analysis",
    "uniquant.brain.wyckoff.events",
    "uniquant.brain.wyckoff.models",
    "uniquant.brain.wyckoff.rules",
    "uniquant.brain.wyckoff.pnf",
)


@pytest.mark.parametrize("rel_path", PRUNED_PATHS)
def test_round9_pruned_paths_do_not_exist(rel_path: str) -> None:
    """被删除的文件不得重新出现在磁盘上。"""
    assert not (BRAIN_DIR / rel_path).exists(), (
        f"第九轮已删除 {rel_path}，不应重新出现（见 AGENTS.md 第九轮）"
    )


@pytest.mark.parametrize("module", PRUNED_MODULES)
def test_round9_pruned_modules_are_not_importable(module: str) -> None:
    """被删除的模块不得可导入（ImportError 家族）。"""
    with pytest.raises(ImportError):
        importlib.import_module(module)


@pytest.mark.parametrize("module", SURVIVING_MODULES)
def test_round9_surviving_modules_still_importable(module: str) -> None:
    """正对照：幸存模块必须仍可导入——防止守卫因整体损坏而空转。"""
    assert importlib.import_module(module) is not None


def test_round9_lppl_package_has_no_dangling_symbols() -> None:
    """``brain.lppl`` 包不得再导出已删除模块的符号。"""
    import uniquant.brain.lppl as lppl_pkg

    for obsolete in ("LPPLComputation",):
        assert not hasattr(lppl_pkg, obsolete), f"brain.lppl 仍导出已删除符号 {obsolete}"


def test_round9_wyckoff_package_has_no_dangling_symbols() -> None:
    """``brain.wyckoff`` 包不得再导出已删除模块的符号。"""
    import uniquant.brain.wyckoff as wyckoff_pkg

    for obsolete in ("calculate_wyckoff_return",):
        assert not hasattr(wyckoff_pkg, obsolete), (
            f"brain.wyckoff 仍导出已删除符号 {obsolete}"
        )


def test_round9_lppl_live_entrypoints_still_present() -> None:
    """正对照：承接 computation.py 职责的**在线** LPPL 入口必须仍在。"""
    from uniquant.brain.lppl.calculator import LPPLCalculator
    from uniquant.brain.lppl.engine import LPPLEngine

    assert LPPLCalculator is not None
    assert LPPLEngine is not None
