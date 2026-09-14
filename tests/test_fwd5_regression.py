"""
fwd5 错位 bug 回归测试 — P11/P12/P14/逻辑因子五门脚本的 fwd5 定义 (2026-08-28)

背景 (D+15 验证):
原 `panel["fwd5"] = pct_change(-5, fill_method=None).shift(-5)` 经 pandas 语义
验证 = close[t+5]/close[t+10]-1, 即"未来5-10日"收益, 视野错位 5 天, 导致
动量残差门系统性误判 (P14 三因子、P11 价值族全被假"动量 beta 幻影"灭掉)。

正确 = close[t+5]/close[t]-1 (未来0-5日), 与 analyzer.compute_ic_ir 官方
`shift(-period)/close - 1` 逐位一致。

本测试锁定 correct_fwd5 语义, 防止回归。
"""

import numpy as np
import pandas as pd

from scripts.factor_mining.five_gate import correct_fwd5


def test_correct_fwd5_is_future_0_5_day():
    # 已知序列: close[t]=t+1, close[t+5]/close[t]-1
    closes = [float(i + 1) for i in range(12)]
    df = pd.DataFrame({
        "code": ["000001.SZ"] * len(closes),
        "date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
        "close": closes,
    })
    panel = df.set_index(["code", "date"])
    fwd5 = correct_fwd5(panel)
    # t=0: close[5]/close[0]-1 = 6/1-1 = 5.0
    assert abs(fwd5.iloc[0] - 5.0) < 1e-9
    # t=1: close[6]/close[1]-1 = 7/2-1 = 2.5
    assert abs(fwd5.iloc[1] - 2.5) < 1e-9
    # 尾部 5 个为 NaN (无未来数据)
    assert fwd5.iloc[-5:].isna().all()


def test_correct_fwd5_differs_from_buggy_pct_change_shift():
    # 错位版 pct_change(-5).shift(-5) = close[t+5]/close[t+10]-1 (未来5-10日)
    closes = [float(i + 1) for i in range(12)]
    df = pd.DataFrame({
        "code": ["000001.SZ"] * len(closes),
        "date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
        "close": closes,
    })
    panel = df.set_index(["code", "date"])
    fwd5 = correct_fwd5(panel)
    buggy = panel["close"].pct_change(-5, fill_method=None).shift(-5)
    # 正确与错位不同 (t=0: 正确 5.0, 错位 6/11-1=-0.4545)
    assert abs(fwd5.iloc[0] - buggy.iloc[0]) > 1e-6
    # 正确 = close[t+5]/close[t]-1
    assert abs(fwd5.iloc[0] - (closes[5] / closes[0] - 1)) < 1e-9
    # 错位 = close[t+5]/close[t+10]-1
    assert abs(buggy.iloc[0] - (closes[5] / closes[10] - 1)) < 1e-9


def test_correct_fwd5_grouped_by_code():
    # 多股互不污染
    n = 12
    closes_a = [float(i + 1) for i in range(n)]
    closes_b = [float(i + 100) for i in range(n)]
    dates = list(pd.date_range("2026-01-01", periods=n, freq="D"))
    df = pd.DataFrame({
        "code": ["000001.SZ"] * n + ["000002.SZ"] * n,
        "date": dates + dates,
        "close": closes_a + closes_b,
    })
    panel = df.set_index(["code", "date"])
    fwd5 = correct_fwd5(panel)
    # 000001.SZ t=0 = 5.0
    assert abs(fwd5.loc["000001.SZ"].iloc[0] - 5.0) < 1e-9
    # 000002.SZ t=0 = close[5]/close[0]-1 = 105/100-1 = 0.05
    assert abs(fwd5.loc["000002.SZ"].iloc[0] - 0.05) < 1e-9


def test_correct_fwd5_matches_analyzer_forward_ret():
    # 与 analyzer.compute_ic_ir 的 forward return 定义逐位一致
    from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode
    rng = np.random.RandomState(0)
    n = 200
    n_stock = 20
    codes = [f"{i:06d}.SZ" for i in range(n_stock)]
    frames = []
    for _ in range(n_stock):
        c = 10.0 + np.cumsum(rng.randn(n) * 0.01)
        frames.append(c)
    df = pd.DataFrame({
        "code": [c for c in codes for _ in range(n)],
        "date": list(pd.date_range("2024-01-01", periods=n, freq="D")) * n_stock,
        "close": np.concatenate(frames),
    })
    df["factor"] = df["close"].rank(pct=True)
    an = FactorAnalyzer()
    res = an.compute_ic_ir(df, factor_cols=["factor"], holding_periods=[5],
                           date_col="date", code_col="code", price_col="close",
                           mode=AnalysisMode.BACKTEST)
    ic_analyzer = res["factor"][5].ic_mean
    # 用 correct_fwd5 逐日 rank IC 复算, 应接近 analyzer (同 fwd 定义)
    panel = df.set_index(["code", "date"]).sort_index()
    panel["fwd5"] = correct_fwd5(panel)
    ics = []
    for _, g in panel.groupby(level=1):
        f = g["factor"].dropna()
        r = g["fwd5"].dropna()
        common = f.index.intersection(r.index)
        if len(common) < 20:
            continue
        fr = f.loc[common].rank()
        rr = r.loc[common].rank()
        ics.append(fr.corr(rr, method="pearson"))
    my_ic = float(np.mean(ics))
    # 同一 fwd 定义下两种实现应高度一致 (analyzer 用 shift(-5), correct_fwd5 亦如此)
    assert abs(my_ic - ic_analyzer) < 1e-3  # 过滤阈值不同(n>=20 vs n>=5), 允许微小差
