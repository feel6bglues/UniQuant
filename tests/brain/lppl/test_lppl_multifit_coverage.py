"""第九轮（2026-10-17）覆盖率补测：``brain/lppl/multifit.py``。

``multifit`` 是三层 LPPL 系统的 Layer 1（多窗口独立拟合 + 综合打分），
此前 CI 口径仅 51.9% 覆盖——缺口集中在 ``_classify_phase`` 的负天数分支、
``fit_single_layer`` 的“无候选”分支，以及整个 ``calculate_multifit_score``
（0 覆盖）。

本文件以**合成数据**覆盖全部分支：

* ``_classify_phase``：none / danger / warning / watch 四级判定；
* ``fit_single_layer``：窗口跳过、常量价 → 无候选、真实单层拟合取最优；
* ``fit_multi_window``：默认配置与自定义配置两条路径；
* ``calculate_multifit_score``：缺层补零、m/w 边界有效性、四档时间衰减、
  danger/warning 加成、一致性加分（0 / 2 / 3 层）、四档 level、上限截断。

约束：不触网、不读 ``data/``、不依赖 requests/czsc/backtrader/mootdx。
只使用短合成序列与最小 ``WindowConfig``，RNG 全部固定种子。
"""

from __future__ import annotations

import numpy as np
import pytest

from uniquant.brain.lppl.calculator import lppl_func
from uniquant.brain.lppl.multifit import (
    MULTI_WINDOW_CONFIGS,
    WindowConfig,
    _classify_phase,
    calculate_multifit_score,
    fit_multi_window,
    fit_single_layer,
)

# 短窗口配置：让真实拟合只跑 30/40 两个窗口，控制运行时长
_SHORT_CFG = WindowConfig(
    name="short",
    windows=[30, 40],
    m_bounds=(0.10, 0.90),
    w_bounds=(5.0, 13.0),
    r2_threshold=0.5,
    danger_days=5,
    warning_days=12,
    watch_days=25,
    weight=1.0,
)


def _synthetic_lppl(window: int, seed: int = 42, noise: float = 0.002) -> np.ndarray:
    """构造已知参数的 LPPL 合成价格序列（对数域叠加小幅高斯噪声）。"""
    rng = np.random.default_rng(seed)
    t = np.arange(window, dtype=np.float64)
    log_price = lppl_func(t, 110.0, 0.5, 9.0, 6.0, -1.0, 0.3, 0.0)
    return np.exp(log_price + rng.normal(0.0, noise, size=window))


def _layer_result(
    *,
    m: float = 0.2,
    w: float = 8.0,
    r2: float = 0.8,
    days_to_crash: float = 3.0,
    is_danger: bool = False,
    phase: str = "none",
    rmse: float = 0.05,
    window_size: int = 60,
    include_optional: bool = True,
) -> dict:
    """构造 ``calculate_multifit_score`` 可消费的单层结果字典。"""
    result = {
        "m": m,
        "w": w,
        "r_squared": r2,
        "days_to_crash": days_to_crash,
        "is_danger": is_danger,
        "phase": phase,
        "rmse": rmse,
        "window_size": window_size,
    }
    if include_optional:
        result["is_warning"] = is_danger or phase == "warning"
    return result


# =========================================================================
# 1. _classify_phase —— 四级判定与负天数早退
# =========================================================================


class TestClassifyPhase:
    """``_classify_phase`` 的边界判决（``short``: danger<5 / warning<12 / watch<25）。"""

    cfg = MULTI_WINDOW_CONFIGS["short"]

    def test_negative_days_returns_none(self) -> None:
        # 崩盘时点已过 → 直接 none（负天数早退分支）
        assert _classify_phase(-1.0, 0.99, self.cfg) == "none"

    def test_danger_when_close_and_high_r2(self) -> None:
        assert _classify_phase(3.0, 0.9, self.cfg) == "danger"

    def test_danger_requires_r2_threshold(self) -> None:
        # days 很近但 R² 不达标 → 落到后续判定（此处仍为 none）
        assert _classify_phase(3.0, 0.1, self.cfg) == "none"

    def test_warning_branch(self) -> None:
        # danger<=days<warning 且 R² ≥ threshold-0.05
        assert _classify_phase(8.0, 0.6, self.cfg) == "warning"

    def test_watch_branch(self) -> None:
        # warning<=days<watch 且 R² ≥ threshold-0.15
        assert _classify_phase(20.0, 0.5, self.cfg) == "watch"

    def test_beyond_watch_returns_none(self) -> None:
        assert _classify_phase(200.0, 0.99, self.cfg) == "none"


# =========================================================================
# 2. fit_single_layer —— 窗口跳过 / 无候选 / 真实拟合取最优
# =========================================================================


class TestFitSingleLayer:
    """``fit_single_layer`` 的候选筛选与最优（RMSE 最小）选择。"""

    def test_no_candidates_when_index_too_small(self) -> None:
        # idx 小于所有窗口 → 全部 continue → 无候选 → None
        prices = np.linspace(10.0, 12.0, 20)
        assert fit_single_layer(prices, 10, _SHORT_CFG) is None

    def test_constant_prices_give_no_candidates(self) -> None:
        # 窗口够大但价格恒定 → 每个拟合都返回 None → 无候选 → None
        prices = np.full(45, 100.0)
        assert fit_single_layer(prices, 40, _SHORT_CFG) is None

    def test_skips_window_larger_than_index(self) -> None:
        # idx=35: 窗口 40 被跳过、窗口 30 尝试拟合（常量价失败）→ None
        prices = np.full(45, 100.0)
        assert fit_single_layer(prices, 35, _SHORT_CFG) is None

    def test_real_fit_returns_best_candidate(self) -> None:
        prices = _synthetic_lppl(40)
        result = fit_single_layer(prices, len(prices), _SHORT_CFG)
        assert result is not None
        # 候选被回填的元数据
        assert result["layer"] == "short"
        assert result["layer_config"] == "short"
        assert result["idx"] == 40
        assert result["phase"] in {"none", "danger", "warning", "watch"}
        assert result["is_danger"] == (result["phase"] == "danger")
        assert result["is_warning"] == (result["phase"] in ("danger", "warning"))
        assert result["is_watch"] == (result["phase"] in ("danger", "warning", "watch"))
        assert np.isfinite(result["rmse"])
        assert np.isfinite(result["r_squared"])


# =========================================================================
# 3. fit_multi_window —— 默认配置 / 自定义配置
# =========================================================================


class TestFitMultiWindow:
    """``fit_multi_window`` 的层级遍历与默认配置回退。"""

    def test_default_configs_with_tiny_series(self) -> None:
        # 序列极短 → 所有层级窗口都跳过，全部 None（同时覆盖 configs=None 回退）
        prices = np.linspace(10.0, 11.0, 5)
        results = fit_multi_window(prices, 5)
        assert isinstance(results, dict)
        assert set(results) == set(MULTI_WINDOW_CONFIGS)
        assert all(value is None for value in results.values())

    def test_custom_configs_path(self) -> None:
        custom = {"only": _SHORT_CFG}
        prices = np.linspace(10.0, 11.0, 5)
        results = fit_multi_window(prices, 5, configs=custom)
        assert set(results) == {"only"}
        assert results["only"] is None

    def test_custom_configs_with_real_fit(self) -> None:
        custom = {"only": _SHORT_CFG}
        prices = _synthetic_lppl(40)
        results = fit_multi_window(prices, len(prices), configs=custom)
        assert results["only"] is not None
        assert results["only"]["layer"] == "short"


# =========================================================================
# 4. calculate_multifit_score —— 综合打分全分支
# =========================================================================


class TestCalculateMultifitScore:
    """``calculate_multifit_score`` 的加权、时间衰减、加成与 level 判定。"""

    def test_all_layers_missing_returns_none_level(self) -> None:
        # 三层皆缺 → 补零结构 + 最终 none（同时覆盖 configs=None 回退）
        out = calculate_multifit_score(
            {"short": None, "medium": None, "long": None}
        )
        assert out["final_score"] == 0.0
        assert out["level"] == "none"
        assert out["weighted_score"] == 0.0
        assert out["consistency_bonus"] == 0.0
        assert out["danger_layers"] == []
        assert out["n_danger"] == 0
        # 缺层结构包含配置权重与占位值
        blank = out["layers"]["short"]
        assert blank["raw"] == 0.0
        assert blank["adjusted"] == 0.0
        assert blank["is_danger"] is False
        assert blank["phase"] == "none"
        assert blank["days_to_crash"] == 999
        assert blank["rmse"] == 999
        assert blank["weight"] == MULTI_WINDOW_CONFIGS["short"].weight

    def test_three_danger_layers_capped_at_one(self) -> None:
        # 三层 danger（时间衰减=1.0, ×1.3）→ 一致性加分 0.3 → 上限截断到 1.0
        out = calculate_multifit_score(
            {
                "short": _layer_result(m=0.2, w=8.0, r2=0.9, days_to_crash=3.0,
                                       is_danger=True, phase="danger"),
                "medium": _layer_result(m=0.5, w=9.0, r2=0.9, days_to_crash=5.0,
                                        is_danger=True, phase="danger"),
                "long": _layer_result(m=0.3, w=9.0, r2=0.9, days_to_crash=10.0,
                                      is_danger=True, phase="danger"),
            }
        )
        assert out["n_danger"] == 3
        assert out["danger_layers"] == ["short", "medium", "long"]
        assert out["consistency_bonus"] == pytest.approx(0.3)
        assert out["weighted_score"] == pytest.approx(1.17)
        assert out["final_score"] == 1.0
        assert out["level"] == "danger"

    def test_two_danger_layers_get_smaller_bonus(self) -> None:
        out = calculate_multifit_score(
            {
                "short": _layer_result(m=0.2, w=8.0, r2=0.6, days_to_crash=3.0,
                                       is_danger=True, phase="danger"),
                "medium": _layer_result(m=0.5, w=9.0, r2=0.6, days_to_crash=5.0,
                                        is_danger=True, phase="danger"),
                "long": None,
            }
        )
        assert out["n_danger"] == 2
        assert out["consistency_bonus"] == pytest.approx(0.15)
        assert out["final_score"] == pytest.approx(0.774)
        assert out["level"] == "danger"

    def test_warning_time_factor_and_phase_boost(self) -> None:
        # 三层 days 落在 warning 区间（衰减 0.6）+ phase=="warning"（×1.1）
        out = calculate_multifit_score(
            {
                "short": _layer_result(m=0.2, w=8.0, r2=0.8, days_to_crash=8.0,
                                       phase="warning"),
                "medium": _layer_result(m=0.5, w=9.0, r2=0.8, days_to_crash=15.0,
                                        phase="warning"),
                "long": _layer_result(m=0.3, w=9.0, r2=0.8, days_to_crash=30.0,
                                      phase="warning"),
            }
        )
        assert out["n_danger"] == 0
        assert out["consistency_bonus"] == 0.0
        assert out["weighted_score"] == pytest.approx(0.528)
        assert out["final_score"] == pytest.approx(0.528)
        assert out["level"] == "warning"
        assert out["layers"]["short"]["is_warning"] is True

    def test_watch_time_factor_and_level(self) -> None:
        # 仅 short 达标（danger, days<=danger）→ weighted 0.351 → watch
        out = calculate_multifit_score(
            {
                "short": _layer_result(m=0.2, w=8.0, r2=0.9, days_to_crash=3.0,
                                       is_danger=True, phase="danger"),
                "medium": None,
                "long": None,
            }
        )
        assert out["final_score"] == pytest.approx(0.351)
        assert out["level"] == "watch"

    def test_watch_range_time_factor(self) -> None:
        # short: warning_days=12 < days=20 <= watch_days=25 → 时间衰减 0.3
        out = calculate_multifit_score(
            {
                "short": _layer_result(m=0.2, w=8.0, r2=0.9, days_to_crash=20.0),
                "medium": None,
                "long": None,
            }
        )
        assert out["layers"]["short"]["raw"] == pytest.approx(0.27)
        assert out["final_score"] == pytest.approx(0.081)
        assert out["level"] == "none"

    def test_beyond_watch_uses_floor_time_factor(self) -> None:
        # days 远超 watch_days → 时间衰减落到 0.1 下限
        out = calculate_multifit_score(
            {
                "short": _layer_result(m=0.2, w=8.0, r2=0.9, days_to_crash=100.0),
                "medium": None,
                "long": None,
            }
        )
        assert out["layers"]["short"]["raw"] == pytest.approx(0.09)
        assert out["final_score"] == pytest.approx(0.027)
        assert out["level"] == "none"

    def test_invalid_m_and_w_halve_base(self) -> None:
        # m 越界（short m_bounds 上界 0.25）→ base = r2*0.5
        invalid_m = _layer_result(m=0.9, w=8.0, r2=0.8, days_to_crash=3.0)
        # w 越界（short w_bounds 上界 13）→ base = r2*0.5
        invalid_w = _layer_result(m=0.2, w=20.0, r2=0.8, days_to_crash=3.0)
        out_m = calculate_multifit_score({"short": invalid_m, "medium": None, "long": None})
        out_w = calculate_multifit_score({"short": invalid_w, "medium": None, "long": None})
        assert out_m["layers"]["short"]["m_valid"] is False
        assert out_m["layers"]["short"]["w_valid"] is True
        assert out_m["layers"]["short"]["raw"] == pytest.approx(0.4)
        assert out_w["layers"]["short"]["w_valid"] is False
        assert out_w["layers"]["short"]["raw"] == pytest.approx(0.4)

    def test_missing_optional_keys_use_defaults(self) -> None:
        # 结果只带 m/w → 其余字段走 .get 默认（r2=0 / days=999 / phase=none / rmse=999）
        out = calculate_multifit_score(
            {"short": {"m": 0.2, "w": 8.0}, "medium": None, "long": None}
        )
        short = out["layers"]["short"]
        assert short["r_squared"] == 0.0
        assert short["days_to_crash"] == 999
        assert short["phase"] == "none"
        assert short["is_danger"] is False
        assert short["is_warning"] is False
        assert short["window_size"] == 0
        assert short["rmse"] == 999
        assert short["raw"] == 0.0

    def test_custom_configs_and_weight(self) -> None:
        # 显式传入自定义配置：覆盖 configs 非 None 分支与自定义 weight
        custom = {
            "solo": WindowConfig(
                name="solo",
                windows=[30],
                m_bounds=(0.10, 0.90),
                w_bounds=(5.0, 13.0),
                r2_threshold=0.5,
                danger_days=5,
                warning_days=12,
                watch_days=25,
                weight=0.75,
            )
        }
        out = calculate_multifit_score(
            {"solo": _layer_result(m=0.5, w=9.0, r2=1.0, days_to_crash=2.0,
                                   is_danger=True, phase="danger")},
            configs=custom,
        )
        solo = out["layers"]["solo"]
        assert solo["weight"] == 0.75
        # raw = 1.0 * 1.0 * 1.3 = 1.3；adjusted = 1.3 * 0.75 = 0.975
        assert solo["raw"] == pytest.approx(1.3)
        assert solo["adjusted"] == pytest.approx(0.975)
        assert out["final_score"] == pytest.approx(0.975)
        assert out["level"] == "danger"
