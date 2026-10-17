"""第九轮（2026-10-17）覆盖率补测：``brain/lppl/visualizer.py``。

覆盖 ``LPPLVisualizer`` 的两条主路径：

* ``visualize_fit`` —— 拟合曲线绘制 + 崩溃线 + PNG 落盘（在 ``tmp_path`` 内），
  以及内层 ``except (IOError, OSError, ValueError)`` 兜底；
* ``plot_risk_matrix`` —— 风险矩阵柱状图 + 置信度标注 + 图例 + 落盘，
  以及同款内层兜底；
* ``_calculate_lppl`` —— ``tau > 0`` 掩码（越界点置 NaN）。

用 ``matplotlib.use("Agg")``（模块级已设定）+ ``monkeypatch.chdir(tmp_path)``
保证零副作用、不污染仓库。不触网、不读数据湖、不依赖 czsc/backtrader。

未覆盖项（**不可达防御**，不写"强行命中"的测试）：``:63`` 的
``else all_dates[-1]`` —— 由 ``days_forward = int(tc - len(df_plot)) + 5`` 可得
``len(all_dates) == int(tc) + 5 > int(tc)``，故 ``int(tc) < len(all_dates)`` 恒真，
``else`` 分支数学上不可达。
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from uniquant.brain.lppl.visualizer import LPPLVisualizer

#: DejaVu Sans 无 CJK 字形 ⇒ 绘图时产生大量无害的 UserWarning，整个模块静音
pytestmark = pytest.mark.filterwarnings("ignore:Glyph.*missing from font")


def _df(n: int = 40) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "close": np.linspace(10.0, 20.0, n),
        }
    )


def _result(tc: float = 50.0, window: int = 30) -> dict:
    return {
        "params": (tc, 0.4, 8.0, 1.0, -1.0, 0.1, 0.5),
        "window": window,
        "span": "2024-01 2024-02",
    }


class TestVisualizeFit:
    def test_saves_chart_png(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        out = LPPLVisualizer().visualize_fit(_df(), _result(), "TEST")
        assert out is not None
        assert out.endswith(".png")
        assert (tmp_path / out).is_file()

    def test_save_failure_returns_none(self, tmp_path, monkeypatch) -> None:
        """``plt.savefig`` 抛 ``OSError`` ⇒ 内层 ``except`` 兜底返回 None。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(plt, "savefig", _raise_oserror)

        out = LPPLVisualizer().visualize_fit(_df(), _result(), "TEST")
        assert out is None


class TestCalculateLppl:
    def test_masks_non_positive_tau_as_nan(self) -> None:
        t = np.array([-5.0, 0.0, 5.0, 10.0])
        vals = LPPLVisualizer()._calculate_lppl(t, 10.0, 0.4, 8.0, 1.0, -1.0, 0.1, 0.5)
        # tau = 10 - t = [15, 10, 5, 0] ⇒ 仅最后一点 tau == 0 被置 NaN
        assert np.isfinite(vals[:3]).all()
        assert np.isnan(vals[3])


class TestPlotRiskMatrix:
    def test_saves_matrix_png(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        matrix = {
            "000300.SH": {"tc_days": 42, "confidence": 0.81, "status": "Warning"},
            "000905.SH": {"tc_days": 17, "confidence": 0.55, "status": "Danger"},
            "000016.SH": {"tc_days": 90, "confidence": 0.30, "status": "Safe"},
            "399006.SZ": {"status": "Unknown"},  # 覆盖 .get 默认（tc_days/confidence/颜色）
        }
        out = LPPLVisualizer().plot_risk_matrix(matrix)
        assert out == "lppl_risk_matrix.png"
        assert (tmp_path / out).is_file()

    def test_save_failure_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(plt, "savefig", _raise_oserror)

        out = LPPLVisualizer().plot_risk_matrix(
            {"000300.SH": {"tc_days": 42, "confidence": 0.81, "status": "Safe"}}
        )
        assert out is None


def _raise_oserror(*args, **kwargs):
    raise OSError("simulated disk failure")
