"""第十七轮（2026-10-26）死代码与冗余模块剪除守卫。

第十七轮物理清理与归档：
(A) ``shared/`` 层死代码与过时垫片物理删除::
    - ``shared/risk_constants.py``: 仅 2 行且与系统 2.50% 无风险利率冲突（原 0.03），
      已收敛至 ``portfolio_optimizer.py`` 本地 ``DEFAULT_RISK_FREE_RATE = 0.025``。
    - ``shared/di_container.py``: 42 行已废弃垫片，已完全由在线 ``services/service_container.py``
      的 ``ServiceContainer`` 接管。
    - ``shared/error_handling.py`` 中的 5 个废弃包装器：
      ``retry_on_exception``、``handle_network_errors``、``handle_file_errors``、
      ``handle_data_errors``、``handle_api_errors``，全仓零业务调用，已物理移除。

(B) 历史实验脚本归档与研究模块迁移::
    - ``ashare_constraints.py`` 与 ``v_shape_detector.py`` 正式迁移至 ``src/uniquant/brain/wyckoff/``，
      并导出为核心领域组件。
    - ``scripts/wyckoff_multitf/`` 中 260 MB 废弃输出文件完全清理。
    - 历史验证脚本目录归档至 ``docs/archive/experiments/``。

本守卫以"文件不存在 + 模块不可导入 + 存活包无悬空符号 + 正对照可运行"多重断言锁死删除结果。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "src" / "uniquant" / "shared"

# --- 被删除的物理文件 -------------------------------------------------------
PRUNED_PATHS = (
    "risk_constants.py",
    "di_container.py",
)

# --- 应不可导入的模块 -------------------------------------------------------
PRUNED_MODULES = (
    "uniquant.shared.risk_constants",
    "uniquant.shared.di_container",
)

# --- error_handling 中已物理移除的已废弃符号 --------------------------------
PRUNED_ERROR_HANDLING_SYMBOLS = (
    "retry_on_exception",
    "handle_network_errors",
    "handle_file_errors",
    "handle_data_errors",
    "handle_api_errors",
)

# --- 幸存模块与接管组件（正对照：必须存在且可导入） -------------------------
SURVIVING_MODULES = (
    "uniquant.shared",
    "uniquant.shared.error_handling",
    "uniquant.shared.retry_decorator",
    "uniquant.shared.cost_model",
    "uniquant.services.service_container",
    "uniquant.risk.portfolio_optimizer",
    "uniquant.brain.wyckoff.ashare_constraints",
    "uniquant.brain.wyckoff.v_shape_detector",
)


@pytest.mark.parametrize("rel_path", PRUNED_PATHS)
def test_round17_pruned_paths_do_not_exist(rel_path: str) -> None:
    """第十七轮被删除的文件不得重新出现在磁盘上。"""
    assert not (SHARED_DIR / rel_path).exists(), (
        f"第十七轮已删除 {rel_path}，不应重新出现（见 AGENTS.md 第十七轮）"
    )


@pytest.mark.parametrize("module", PRUNED_MODULES)
def test_round17_pruned_modules_are_not_importable(module: str) -> None:
    """第十七轮被删除的模块不得可导入（ImportError 家族）。"""
    with pytest.raises(ImportError):
        importlib.import_module(module)


@pytest.mark.parametrize("symbol", PRUNED_ERROR_HANDLING_SYMBOLS)
def test_round17_error_handling_has_no_dangling_deprecated_symbols(symbol: str) -> None:
    """``shared.error_handling`` 模块不得再导出已删除的废弃包装器。"""
    import uniquant.shared.error_handling as eh

    assert not hasattr(eh, symbol), f"shared.error_handling 仍导出已删除符号 {symbol}"


@pytest.mark.parametrize("module", SURVIVING_MODULES)
def test_round17_surviving_modules_still_importable(module: str) -> None:
    """正对照：幸存模块必须仍可导入——防止守卫因整体损坏而空转。"""
    assert importlib.import_module(module) is not None


def test_round17_service_container_active() -> None:
    """正对照：接管 di_container 的 ServiceContainer 必须正常工作。"""
    from uniquant.services.service_container import ServiceContainer

    container = ServiceContainer()
    container.register("sample_key", {"active": True})
    assert container.get("sample_key") == {"active": True}


def test_round17_portfolio_optimizer_risk_free_rate_aligned() -> None:
    """正对照：组合优化器无风险利率基准已统一为 0.025 (2.50%)。"""
    from uniquant.risk.portfolio_optimizer import DEFAULT_RISK_FREE_RATE, OptimizerConfig

    assert DEFAULT_RISK_FREE_RATE == 0.025
    cfg = OptimizerConfig()
    assert cfg.risk_free_rate == 0.025


def test_round17_wyckoff_migrated_components_available() -> None:
    """正对照：迁移至 brain/wyckoff 的 AShareConstraints 与 VShapedReversalDetector 可正常访问。"""
    from uniquant.brain.wyckoff import AShareConstraints, VShapedReversalDetector, VShapeResult

    assert AShareConstraints.get_limit_pct("600001.SH") == 0.10
    assert AShareConstraints.get_limit_pct("688001.SH") == 0.20
    detector = VShapedReversalDetector()
    assert detector.decline_threshold == 0.15
    res = VShapeResult(
        date="2024-01-01",
        v_type="v_bottom",
        severity="high",
        decline_pct=20.0,
        recovery_pct=50.0,
        decline_days=5,
        recovery_days=5,
    )
    assert res.v_type == "v_bottom"
