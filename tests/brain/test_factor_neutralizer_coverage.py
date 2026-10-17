"""第九轮（2026-10-17）覆盖率补测：``brain/factors/neutralizer.py``。

``FactorNeutralizer`` 在 ``composer.py`` 的正交化链路中在线使用
（``composer.py:15`` 导入），此前仅 19.2% 覆盖（CI 口径）。
本文件以**合成数据**覆盖其全部分支：MAD 缩尾、小样本早退、
有效样本早退、OLS 残差化、NaN 掩码与索引/名称保真。
不触网、不读数据湖、不依赖 czsc/backtrader。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from uniquant.brain.factors.neutralizer import FactorNeutralizer, mad_winsorize


class TestMadWinsorize:
    def test_clips_extreme_values(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0])
        out = mad_winsorize(s, n=5)
        # 极端值必须被夹到上界以内，中位数保持不变
        assert out.max() < 100.0
        assert out.median() == s.median()
        assert isinstance(out, pd.Series)

    def test_zero_mad_returns_series_unchanged(self) -> None:
        # 所有值相同 → mad == 0 → 原样返回（不做无量纲化）
        s = pd.Series([7.0, 7.0, 7.0, 7.0])
        out = mad_winsorize(s, n=5)
        pd.testing.assert_series_equal(out, s)

    def test_larger_n_widens_bounds(self) -> None:
        s = pd.Series(np.linspace(0.0, 10.0, 21))
        tight = mad_winsorize(s, n=1)
        loose = mad_winsorize(s, n=50)
        # n 越大边界越宽 → 被夹的元素不应更多
        assert (loose != s).sum() <= (tight != s).sum()

    def test_preserves_index_and_name(self) -> None:
        idx = pd.Index(["a", "b", "c", "d", "e"])
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 50.0], index=idx, name="f")
        out = mad_winsorize(s)
        assert list(out.index) == list(idx)
        assert out.name == "f"


class TestFactorNeutralizer:
    @staticmethod
    def _frames(n: int, seed: int = 0):
        rng = np.random.default_rng(seed)
        factor = pd.Series(rng.normal(size=n), name="fac")
        log_mcap = pd.Series(rng.normal(10.0, 1.0, size=n), name="mcap")
        # 两个行业哑变量列
        ind = pd.DataFrame(
            {
                "ind_a": rng.integers(0, 2, size=n).astype(float),
                "ind_b": rng.integers(0, 2, size=n).astype(float),
            }
        )
        return factor, ind, log_mcap

    def test_small_sample_returns_factor_unchanged(self) -> None:
        factor, ind, mcap = self._frames(9)
        out = FactorNeutralizer().neutralize(factor, ind, mcap)
        pd.testing.assert_series_equal(out, factor)

    def test_valid_sample_below_threshold_returns_factor(self) -> None:
        # 长度 >= 10 但（因 NaN）有效样本 < 10 → 原样返回
        factor, ind, mcap = self._frames(12)
        mcap = mcap.copy()
        mcap.iloc[:5] = np.nan
        out = FactorNeutralizer().neutralize(factor, ind, mcap)
        pd.testing.assert_series_equal(out, factor)

    def test_normal_path_returns_residuals(self) -> None:
        factor, ind, mcap = self._frames(200, seed=1)
        out = FactorNeutralizer().neutralize(factor, ind, mcap)
        assert isinstance(out, pd.Series)
        assert out.name == "fac"
        assert out.notna().all()
        # 残差应已去除与市值/行业的线性成分 → 与市值近似正交
        assert abs(np.corrcoef(out.values, mcap.values)[0, 1]) < 0.2

    def test_nan_factor_rows_are_masked_to_nan(self) -> None:
        factor, ind, mcap = self._frames(60, seed=2)
        factor = factor.copy()
        factor.iloc[[0, 1, 2]] = np.nan
        out = FactorNeutralizer().neutralize(factor, ind, mcap)
        assert out.iloc[[0, 1, 2]].isna().all()
        assert out.iloc[3:].notna().all()

    def test_winsorize_n_is_respected(self) -> None:
        factor, ind, mcap = self._frames(120, seed=3)
        factor = factor.copy()
        factor.iloc[0] = 1e6  # 极端离群点
        out = FactorNeutralizer().neutralize(factor, ind, mcap, winsorize_n=1)
        # 缩尾后残差量级应被压制（不会出现 1e6 量级）
        assert out.abs().max() < 1e5
