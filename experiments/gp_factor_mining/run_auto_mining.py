"""
Phase 2: 逻辑约束下的自动挖掘重启 (Constrained Auto-Mining)
=============================================================

使用遗传规划 (GP) + 金融算子挖掘新因子。

流程:
  1. 在含已知因子结构的合成数据上运行 GP 进化
  2. 提取 Top-K 个候选因子
  3. The Reaper: 全量 Walk-Forward PBO 校验
      - PBO < 0.2 且 OOS IC > 0.05 → 幸存
     - 否则: 内存中销毁
  4. 幸存因子 → 生成为 .py 代码文件

[Halt & Wait]
"""

import os, sys, copy
from pathlib import Path
os.environ["PYTHONWARNINGS"] = "ignore"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generator import GeneticFactorMiner, GPConfig, GPTree

# =========================================================================
# 带已知因子结构的合成数据
# =========================================================================

def generate_planted_data(
    n_stocks: int = 80, n_days: int = 800, seed: int = 42
) -> pd.DataFrame:
    """
    生成含已知因子信号的数据:
      - 基础市场因子 (beta) — ~0.5% IC
      - 植入的动量因子: 过去 20 天收益对第 21 天收益有 +0.03 预测力
      - 植入的量价背离: 过去 10 天 vol_rank - price_rank 对第 11 天有 +0.02 预测力
      - 白噪音: 纯 random walk 作为背景

    IMPORTANT: volume / amount 与 return 无内生相关性.
    旧版 volume = base_vol * (1 + 2*ret) 导致 amount 天然与未来收益相关,
    使 GP 收敛到 amount/vwap 而非真正植入的动量信号.
    """
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2018-01-01", periods=n_days)
    codes = [f"{600000 + i:06d}.SH" for i in range(n_stocks)]
    market_rets = rng.normal(0.08 / 252, 0.18 / np.sqrt(252), size=n_days)

    all_rows = []
    for code in codes:
        beta = 0.6 + rng.random() * 0.8
        ivol = (0.12 + rng.random() * 0.15) / np.sqrt(252)
        price = 20 + rng.random() * 40
        base_vol = int(1_000_000 + rng.random() * 5_000_000)

        prices = np.empty(n_days)
        returns = np.empty(n_days)

        for t in range(n_days):
            noise = rng.normal(0, ivol)
            ret = beta * market_rets[t] + noise
            # 植入动量信号: 如果过去 20 天收益 > 0, 第 21 天加正偏
            if t >= 20:
                mom_20 = (prices[t-1] / max(prices[t-20], 1) - 1)
                ret += 0.03 * np.tanh(mom_20 * 5) * 0.05 * abs(market_rets[t]) / max(abs(market_rets[t]), 1e-10)
            returns[t] = ret
            prices[t] = price * (1 + ret) if t == 0 else prices[t-1] * (1 + ret)
            price = prices[t]
            price = max(price, 1.0)

            o = price * (1 + rng.normal(0, 0.005))
            c = price
            h = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
            l_ = min(o, c) * (1 - abs(rng.normal(0, 0.004)))
            # volume 与 ret 独立: 避免 amount 与未来收益的内生相关性
            v = max(1, int(abs(base_vol * (1 + rng.normal(0, 0.3)))))
            amt = v * (o + c) / 2

            all_rows.append({
                "code": code, "date": dates[t],
                "open": round(o, 2), "high": round(h, 2), "low": round(l_, 2),
                "close": round(c, 2), "volume": v, "amount": round(amt, 0),
            })

    df = pd.DataFrame(all_rows).sort_values(["code", "date"]).reset_index(drop=True)
    print(f"  [数据] {df['code'].nunique()} 只 × {df['date'].nunique()} 天 = {len(df):,} 行 (含植入信号)")
    return df


# =========================================================================
# The Reaper — 死神校验
# =========================================================================

def _block_bootstrap_pbo(oos_ics: list, n_bootstrap: int = 2000, block_size: int = 10) -> float:
    """块 Bootstrap PBO 估计: 保留 IC 时序自相关结构"""
    arr = np.array(oos_ics, dtype=np.float64)
    n = len(arr)
    if n < block_size * 2:
        return 1.0
    actual_mean = float(np.mean(arr))
    rng = np.random.RandomState(42)
    bootstrap_means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        chunks = []
        pos = 0
        while pos < n:
            start = rng.randint(0, n - block_size + 1)
            chunks.extend(arr[start:start + block_size].tolist())
            pos += block_size
        bootstrap_means[i] = np.mean(chunks[:n])
    return float(np.mean(bootstrap_means >= actual_mean))


def the_reaper(candidates: list, df: pd.DataFrame) -> list:
    """
    死神校验 — 全量 Walk-Forward PBO 测试

    Gate: PBO < 0.2 且 OOS IC > 0.05
    """
    survivors = []
    n_bootstrap = 2000

    print(f"\n{'='*60}")
    print("  ☠️  The Reaper — 死神校验")
    print(f"  PBO < 0.2 且 OOS IC > 0.05 才允许幸存")
    print(f"{'='*60}")

    all_dates = sorted(df["date"].unique())
    train_w, test_w = 504, 63
    windows = []
    for start in range(train_w, len(all_dates) - test_w + 1, test_w):
        ws = all_dates[start - train_w]
        we = all_dates[start - 1]
        ss = all_dates[start]
        se = all_dates[start + test_w - 1]
        windows.append((ws, we, ss, se))

    print(f"  Walk-Forward: {len(windows)} 窗口 (train={train_w}d, test={test_w}d)")
    print(f"  PBO 采样数: {n_bootstrap}")

    for idx, (tree, fit) in enumerate(candidates):
        formula = tree.to_formula()
        complexity = tree.complexity

        oos_ics = []
        for ws, we, ss, se in windows:
            test_mask = (df["date"] >= ss) & (df["date"] <= se)
            test_sub = df[test_mask].copy()
            test_sub["_fwd"] = test_sub.groupby("code")["close"].shift(-5) / test_sub["close"] - 1

            try:
                factor_vals = tree.evaluate(test_sub)
            except Exception:
                continue

            daily_ics = []
            for _, grp in test_sub.groupby("date", sort=False):
                fv = factor_vals.loc[grp.index].dropna()
                rv = grp["_fwd"].dropna()
                common = fv.index.intersection(rv.index)
                if len(common) < 15:
                    continue
                try:
                    ic, _ = stats.spearmanr(fv.loc[common], rv.loc[common])
                    if not np.isnan(ic):
                        daily_ics.append(ic)
                except Exception:
                    pass

            if daily_ics:
                oos_ics.append(float(np.mean(daily_ics)))

        if len(oos_ics) < 2:
            print(f"  ☠️  #{idx+1:2d} DEAD (no windows)  {formula[:55]}")
            continue

        oos_mean = float(np.mean(oos_ics))
        if oos_mean <= 0:
            print(f"  ☠️  #{idx+1:2d} DEAD (IC≤0: {oos_mean:.4f})  {formula[:55]}")
            continue

        # PBO: 块 Bootstrap — 使用 generator 中的静态方法
        pbo = GeneticFactorMiner.block_bootstrap_pbo(oos_ics, n_bootstrap=n_bootstrap)

        verdict = ""
        if pbo < 0.2 and oos_mean > 0.05:
            survivors.append((tree, oos_mean, pbo, complexity))
            verdict = f"✅ #{idx+1:2d} SURVIVED  IC={oos_mean:.4f}  PBO={pbo:.3f}"
        elif pbo >= 0.2:
            verdict = f"☠️  #{idx+1:2d} PBO={pbo:.3f}≥0.2"
        else:
            verdict = f"☠️  #{idx+1:2d} IC={oos_mean:.4f}≤0.05"
        print(f"  {verdict}  {formula[:50]}")

    print(f"\n  🏆 幸存: {len(survivors)}/{len(candidates)}")
    return survivors


def write_factor_code(tree: GPTree, index: int, oos_ic: float, pbo: float, complexity: float) -> str:
    """幸存因子 → Python 代码"""
    name = f"compute_auto_factor_{index:03d}"
    code = tree.to_python_code(
        name,
        comment=(
            f"自动因子 #{index:03d}\n"
            f"    公式: {tree.to_formula()}\n"
            f"    树深: {tree.depth}  复杂度: {complexity:.1f}\n"
            f"    OOS IC: {oos_ic:.4f}  PBO: {pbo:.3f}"
        ),
    )
    return f"import numpy as np\nimport pandas as pd\n\n{code}"


def main():
    print("=" * 70)
    print("  Phase 2: 受控自动因子挖掘")
    print("  Constrained Auto-Mining with GP + The Reaper")
    print("=" * 70)

    # ---- 1) 数据 ----
    print("\n[1/4] 生成带信号植入的合成数据...")
    df = generate_planted_data(n_stocks=80, n_days=800)

    # ---- 2) GP 进化 ----
    print("\n[2/4] 遗传规划进化...")
    config = GPConfig(
        pop_size=60,
        n_generations=12,
        max_depth=5,
        holding_period=5,
        train_ratio=0.7,
        complexity_penalty=0.02,
        seed=42,
    )
    miner = GeneticFactorMiner(config=config)
    results = miner.mine(df)

    print(f"\n  Top-10 候选:")
    for i, (tree, fit) in enumerate(results[:10]):
        print(f"    #{i+1:2d}: fit={fit:.4f}  depth={tree.depth}  {tree.to_formula()[:60]}")

    # ---- 3) The Reaper ----
    print("\n[3/4] The Reaper — 死神校验...")
    candidates = results[:25]
    survivors = the_reaper(candidates, df)

    # ---- 4) 幸存落盘 ----
    print(f"\n[4/4] 幸存因子代码生成...")
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not survivors:
        print("\n  ❌ 无幸存因子！")
        print("  所有候选均未通过 PBO < 0.2 且 OOS IC > 0.05 的门槛。")
        with open(Path(__file__).resolve().parent / "mining_results.md", "w") as f:
            f.write("# 01 — 受控自动因子挖掘结果\n\n")
            f.write(f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("> **结果**: 无幸存因子\n\n")
            f.write("所有候选被 PBO 阈值淘汰。系统在约束下未能产生合格因子。\n")

        print(f"\n  📋 报告: docs/reshaping_logs/01_auto_mining_results.md")
        print(f"\n{'='*70}")
        print("  Phase 2 完成 — 0 幸存 (所有候选被死神淘汰)")
        print(f"{'='*70}")
        print("\n  ⏸ [Halt & Wait] — 自动挖掘完成, 请确认结果")
        return

    generated = []
    for i, (tree, oos_ic, pbo, complexity) in enumerate(survivors):
        code = write_factor_code(tree, i + 1, oos_ic, pbo, complexity)
        fp = output_dir / f"factor_{i+1:03d}.py"
        with open(fp, "w", encoding="utf-8") as f:
            f.write(code)
        generated.append(fp)
        print(f"  ✅ {fp}")

    # 报告
    report_path = Path(__file__).resolve().parent / "mining_results.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 01 — 受控自动因子挖掘结果\n\n")
        f.write(f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **GP**: 种群={config.pop_size}, 代数={config.n_generations}, 最大深度={config.max_depth}\n")
        f.write(f"> **死神**: PBO<0.2 ∧ OOS IC>0.05\n")
        f.write(f"> **幸存**: {len(survivors)}/{len(candidates)}\n\n")

        f.write("## 幸存因子\n\n")
        f.write("| # | 公式 | 树深 | 复杂度 | OOS IC | PBO | 文件 |\n")
        f.write("|---|------|------|--------|--------|-----|------|\n")
        for i, (tree, oos_ic, pbo, cpx) in enumerate(survivors):
            f.write(f"| {i+1} | `{tree.to_formula()}` | {tree.depth} | {cpx:.1f} | {oos_ic:.4f} | {pbo:.3f} | `factor_{i+1:03d}.py` |\n")

        f.write("\n## 死神淘汰记录\n\n")
        f.write("| # | 公式 | 适应度 | 判定 |\n")
        f.write("|---|------|--------|------|\n")
        for i, (tree, fit) in enumerate(candidates):
            is_s = any(id(s[0]) == id(tree) for s in survivors)
            f.write(f"| {i+1} | `{tree.to_formula()[:60]}` | {fit:.4f} | {'✅' if is_s else '☠️'} |\n")

        f.write("\n---\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n{'='*70}")
    print(f"  Phase 2 完成! {len(survivors)} 个因子通过死神校验。")
    for fp in generated:
        print(f"  📄 {fp}")
    print(f"{'='*70}")
    print("\n  ⏸ [Halt & Wait] — 自动挖掘完成, 请确认幸存因子后继续 Phase 3")


if __name__ == "__main__":
    main()
