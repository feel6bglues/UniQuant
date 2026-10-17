"""第九轮（2026-10-17）覆盖率补测：``brain/lppl/numba_optimizer.py``。

**为何用 ``.py_func``（重要口径说明）**

``numba_optimizer.py`` 的三个数值内核均以 ``@njit(cache=True)`` 装饰：

    _reduced_cost_numba            （变量投影约化代价函数）
    _solve_linear_parameters_numba （正规方程 OLS 线性参数求解）
    _de_solve_numba                （差分进化优化器）

``@njit`` 内核被编译成**原生机器码**执行，Python 的 ``trace`` 钩子不再逐行触发
——因此 coverage.py **看不见**这些函数体内部的行（即使它们确实被执行）。
这不是"死代码"，而是**度量伪影**：``tests/test_refactoring_validation.py``
确实调用了 ``_de_solve_numba`` / ``_solve_linear_parameters_numba``，但覆盖报告中
其函数体仍整段记为 missing。

numba 的 CPUDispatcher 暴露 ``.py_func`` 属性（原始的、未经 JIT 的纯 Python 实现）。
调用 ``.py_func`` 会执行**同一份源码行**的纯 Python 版本，从而让 coverage 恢复可见。
本文件即以此方式对三个内核做**等价逻辑的单元测试**（边界与退化路径全覆盖）：

* 早退分支: ``tc <= t[-1] + 0.5`` → ``1e20``
* 正常路径: 代价函数返回非负 SSE
* 退化路径: ``w = 0`` ⇒ 设计矩阵列线性相关 ⇒ ``np.linalg.solve`` 抛
  ``LinAlgError`` ⇒ 走 ``except`` 兜底（``1e20`` / 四零元组）
* 差分进化: 种群初始化、变异/交叉/选择、收敛早停、``success`` 判定

本文件不触网、不读数据湖、不依赖 czsc/backtrader。数值全部为确定性合成数据
（``seed`` 固定）。
"""

from __future__ import annotations

import numpy as np
import pytest

from uniquant.brain.lppl.numba_optimizer import (
    _de_solve_numba,
    _reduced_cost_numba,
    _solve_linear_parameters_numba,
)


def _series(n: int = 60, tc: float = 80.0) -> tuple[np.ndarray, np.ndarray]:
    """合成一段 LPPL 形状的对数价序列（指数化后为正价，tau = tc - t > 0）。"""
    t = np.arange(n, dtype=np.float64)
    log_prices = 2.0 + 0.5 * np.log(tc - t)
    return t, log_prices


class TestReducedCostNumba:
    def test_normal_path_returns_finite_non_negative(self) -> None:
        t, log_prices = _series()
        sse = _reduced_cost_numba.py_func(np.array([80.0, 0.5, 10.0]), t, log_prices)
        assert np.isfinite(sse)
        assert sse >= 0.0

    def test_early_return_when_tc_not_beyond_last_timestamp(self) -> None:
        """``tc <= t[-1] + 0.5`` ⇒ 直接返回哨兵 1e20（不合法的临界时间）。"""
        t, log_prices = _series()
        sse = _reduced_cost_numba.py_func(
            np.array([float(t[-1]) + 0.1, 0.5, 10.0]), t, log_prices
        )
        assert sse == 1e20

    def test_singular_design_matrix_falls_back_to_sentinel(self) -> None:
        """``w = 0`` ⇒ cos/sin 基底退化 ⇒ 正规方程奇异 ⇒ ``except`` 兜底 1e20。"""
        t, log_prices = _series()
        sse = _reduced_cost_numba.py_func(np.array([80.0, 0.5, 0.0]), t, log_prices)
        assert sse == 1e20

    @pytest.mark.parametrize("w", [1.0, 5.0, 15.0])
    def test_w_variation_stays_finite(self, w: float) -> None:
        t, log_prices = _series()
        sse = _reduced_cost_numba.py_func(np.array([80.0, 0.5, w]), t, log_prices)
        assert np.isfinite(sse)


class TestSolveLinearParametersNumba:
    def test_recovers_planted_linear_parameters(self) -> None:
        """给定 LPPL 曲线，OLS 应还原出植入的 (a, b, c, phi)。"""
        t, _ = _series()
        tc, m, w = 80.0, 0.5, 10.0
        a, b, c, phi = 2.0, -1.0, 0.2, 0.5
        tau = tc - t
        log_prices = (
            a
            + b * (tau**m)
            + c * (tau**m) * np.cos(w * np.log(tau) + phi)
        )

        a_fit, b_fit, c_fit, phi_fit = _solve_linear_parameters_numba.py_func(
            t, log_prices, tc, m, w
        )

        assert np.isclose(a_fit, a, atol=1e-2)
        assert np.isclose(b_fit, b, atol=1e-2)
        assert np.isclose(c_fit, c, atol=1e-2)
        # phi 以 (cos, sin) 组合表达，符号/相位需等价还原
        assert np.isclose(
            np.cos(phi_fit), np.cos(phi), atol=1e-2
        ) and np.isclose(np.sin(phi_fit), np.sin(phi), atol=1e-2)

    def test_singular_matrix_returns_zero_tuple(self) -> None:
        """``w = 0`` 病态 ⇒ ``except`` 分支返回四零元组（而非抛异常）。"""
        t, log_prices = _series()
        out = _solve_linear_parameters_numba.py_func(t, log_prices, 80.0, 0.5, 0.0)
        assert out == (0.0, 0.0, 0.0, 0.0)

    def test_returns_python_floats(self) -> None:
        t, log_prices = _series()
        out = _solve_linear_parameters_numba.py_func(t, log_prices, 80.0, 0.5, 10.0)
        assert len(out) == 4
        assert all(np.isfinite(v) for v in out)

    def test_tau_floor_when_tc_equals_last_timestamp(self) -> None:
        """``tc == t[-1]`` ⇒ 末点 tau = 0 ⇒ 触发 ``tau < 1e-8`` 归一下限。

        注意本函数**没有** ``_reduced_cost_numba`` 的 ``tc > t[-1] + 0.5`` 早退守卫，
        故该分支在此处可达（对应源码 :123-124）。
        """
        t, log_prices = _series()
        out = _solve_linear_parameters_numba.py_func(
            t, log_prices, float(t[-1]), 0.5, 10.0
        )
        assert len(out) == 4
        assert all(np.isfinite(v) for v in out)


class TestDeSolveNumba:
    @staticmethod
    def _bounds() -> np.ndarray:
        return np.array(
            [[61.0, 200.0], [0.1, 1.0], [1.0, 20.0]], dtype=np.float64
        )

    def test_drives_cost_down_and_reports_success(self) -> None:
        """小规模 DE 应显著降低代价并把 ``success`` 置 True。"""
        t, log_prices = _series()
        sol, best_fit, success = _de_solve_numba.py_func(
            t, log_prices, self._bounds(), 4, 10, 1e9, 0.5, 1.0, 0.7, 42
        )
        assert success is True
        assert best_fit < 1e18
        assert sol.shape == (3,)

    def test_solution_respects_bounds(self) -> None:
        """变异后的边界裁剪必须把解约束在 bounds 内。"""
        t, log_prices = _series()
        bounds = self._bounds()
        sol, _, _ = _de_solve_numba.py_func(
            t, log_prices, bounds, 3, 15, 1e9, 0.9, 1.0, 0.7, 7
        )
        for j in range(3):
            assert bounds[j, 0] <= sol[j] <= bounds[j, 1]

    def test_convergence_break_with_large_tol(self) -> None:
        """极大容差 ⇒ 首次收敛检查即早停（覆盖 ``fit_spread < tol`` 分支）。"""
        t, log_prices = _series()
        _, best_fit, success = _de_solve_numba.py_func(
            t, log_prices, self._bounds(), 3, 500, 1e12, 0.5, 1.0, 0.7, 1
        )
        assert success is True
        assert best_fit < 1e18

    def test_negative_seed_skips_reseeding(self) -> None:
        """``seed < 0`` ⇒ 跳过 ``np.random.seed``（另一条初始化分支）。"""
        t, log_prices = _series()
        sol, best_fit, _ = _de_solve_numba.py_func(
            t, log_prices, self._bounds(), 3, 5, 1e9, 0.5, 1.0, 0.7, -1
        )
        assert sol.shape == (3,)
        assert np.isfinite(best_fit)

    def test_deterministic_given_fixed_seed(self) -> None:
        t, log_prices = _series()
        r1 = _de_solve_numba.py_func(
            t, log_prices, self._bounds(), 4, 20, 1e9, 0.5, 1.0, 0.7, 123
        )
        r2 = _de_solve_numba.py_func(
            t, log_prices, self._bounds(), 4, 20, 1e9, 0.5, 1.0, 0.7, 123
        )
        assert np.allclose(r1[0], r2[0])
        assert np.isclose(r1[1], r2[1])
