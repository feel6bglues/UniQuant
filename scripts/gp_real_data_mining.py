"""
Stage 2: 真实 A 股数据 GP 因子挖掘脚本
========================================
使用 akshare 接入真实沪深 300 / 中证 500 历史数据 (2018-2025),
由打补丁后的 GP 引擎在训练集 (2018-2022) 上挖掘 20 代,
报告种群多样性指标和 Top 因子公式。
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "gp_factor_mining"))
from generator import (
    GPConfig,
    GeneticFactorMiner,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("gp_real_data")

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def fetch_csi_constituents(index_code: str = "000300") -> list[str]:
    """通过 akshare 获取指数成分股列表"""
    import akshare as ak
    df = ak.index_stock_cons(symbol=index_code)
    codes = df["品种代码"].str.strip().str.zfill(6).tolist()
    logger.info(f"  {index_code} 成分股: {len(codes)} 只")
    return codes


def map_to_akshare_symbol(code: str) -> str:
    """将 6 位代码映射为 akshare stock_zh_a_daily 所需的 sz/sh 前缀"""
    pref = code[0:2]
    if pref in ("60", "68"):
        return f"sh{code}"
    elif pref in ("00", "30", "02"):
        return f"sz{code}"
    elif pref in ("83", "87", "43", "92"):
        return f"bj{code}"
    return code


def fetch_stock_data_akshare(
    symbol: str,
    start_date: str = "20180101",
    end_date: str = "20251231",
    max_retries: int = 3,
) -> pd.DataFrame:
    """使用 akshare stock_zh_a_daily 获取单只股票日线数据"""
    import akshare as ak
    for attempt in range(max_retries):
        try:
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df["code"] = symbol[2:]  # strip sz/sh prefix
                return df
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.debug(f"    {symbol} fetch failed: {e}")
    return pd.DataFrame()


def build_multi_stock_df(
    symbols_6digit: list[str],
    start_date: str = "20180101",
    end_date: str = "20251231",
    max_stocks: int = 300,
) -> pd.DataFrame:
    """构建多股票 OHLCV DataFrame"""
    symbols = symbols_6digit[:max_stocks]
    akshare_symbols = [map_to_akshare_symbol(s) for s in symbols]

    all_dfs = []
    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info(f"  开始并行获取 {len(symbols)} 只股票数据...")
    start_t = time.time()

    with ThreadPoolExecutor(max_workers=8) as pool:
        fut_map = {
            pool.submit(fetch_stock_data_akshare, asym, start_date, end_date): sym
            for asym, sym in zip(akshare_symbols, symbols)
        }
        for i, fut in enumerate(as_completed(fut_map)):
            sym = fut_map[fut]
            try:
                df = fut.result()
                if df is not None and not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                logger.debug(f"  {sym} failed: {e}")
            if (i + 1) % 50 == 0:
                elapsed = time.time() - start_t
                logger.info(f"    {i+1}/{len(symbols)} 完成, 耗时 {elapsed:.0f}s")

    elapsed = time.time() - start_t
    logger.info(f"  获取完成: {len(all_dfs)}/{len(symbols)} 只成功, 耗时 {elapsed:.0f}s")

    if not all_dfs:
        raise RuntimeError("未获取到任何股票数据")

    combined = pd.concat(all_dfs, ignore_index=True)

    # 标准化列名
    required_cols = {"date", "open", "high", "low", "close", "volume", "amount", "code"}
    col_map = {}
    for c in combined.columns:
        cl = c.lower().strip()
        if cl in ("日期", "date"):
            col_map[c] = "date"
        elif cl in ("开盘", "open"):
            col_map[c] = "open"
        elif cl in ("最高", "high"):
            col_map[c] = "high"
        elif cl in ("最低", "low"):
            col_map[c] = "low"
        elif cl in ("收盘", "close"):
            col_map[c] = "close"
        elif cl in ("成交量", "volume"):
            col_map[c] = "volume"
        elif cl in ("成交额", "amount"):
            col_map[c] = "amount"
    combined.rename(columns=col_map, inplace=True)

    # 确保所需列都存在
    missing = required_cols - set(combined.columns)
    if missing:
        logger.warning(f"  缺少列: {missing}, 可用列: {list(combined.columns)}")
        for m in missing:
            combined[m] = np.nan

    # 类型转换
    combined["date"] = pd.to_datetime(combined["date"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce")

    combined.sort_values(["code", "date"], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    col_order = ["code", "date", "open", "high", "low", "close", "volume", "amount"]
    final_cols = [c for c in col_order if c in combined.columns]
    return combined[final_cols]


def compute_index_corr(best_factor_values: pd.Series, df: pd.DataFrame) -> float:
    """计算因子值与 amount 的相关性 (横截面均值)"""
    from scipy import stats

    corrs = []
    temp = df.copy()
    temp["_fv"] = best_factor_values
    for _, grp in temp.dropna(subset=["_fv", "amount"]).groupby("date", sort=False):
        if len(grp) < 20:
            continue
        c, _ = stats.spearmanr(grp["_fv"], grp["amount"].astype(float))
        if not np.isnan(c):
            corrs.append(abs(c))
    return float(np.mean(corrs)) if corrs else 0.0


def run_gp_mining(args):
    """主逻辑: 获取真实数据 + 运行 GP 挖掘"""
    print("=" * 60)
    print("  阶段 2: 真实 A 股数据 GP 因子挖掘 (打补丁后)")
    print("=" * 60)

    # 1. 获取指数成分股
    print(f"\n[1] 获取 {args.index} 成分股...")
    codes_6digit = fetch_csi_constituents(args.index)

    # 2. 获取日线数据
    print(f"\n[2] 获取日线数据 ({args.start_date} ~ {args.end_date})...")
    df = build_multi_stock_df(
        codes_6digit,
        start_date=args.start_date,
        end_date=args.end_date,
        max_stocks=args.max_stocks,
    )
    print(f"    数据形状: {df.shape}")
    print(f"    股票数: {df['code'].nunique()}")
    print(f"    日期范围: {df['date'].min().date()} ~ {df['date'].max().date()}")
    print(f"    列: {list(df.columns)}")

    # 3. 配置 GP (打补丁后)
    print("\n[3] 初始化 GP 引擎 (打补丁后)...")
    config = GPConfig(
        pop_size=args.pop_size,
        n_generations=args.n_generations,
        max_depth=args.max_depth,
        tournament_size=args.tournament_size,
        crossover_rate=args.crossover_rate,
        mutation_rate=args.mutation_rate,
        elitism_ratio=args.elitism_ratio,
        holding_period=args.holding_period,
        complexity_penalty=args.complexity_penalty,
        amount_neutralize=True,
        amount_penalty_weight=args.amount_penalty,
        diversity_pressure=args.diversity_pressure,
        seed=args.seed,
    )

    miner = GeneticFactorMiner(config=config)
    print(f"    种群大小: {config.pop_size}")
    print(f"    代数: {config.n_generations}")
    print(f"    Amount 中性化: {config.amount_neutralize}")
    print(f"    Amount 惩罚权重: {config.amount_penalty_weight}")
    print(f"    多样性压力: {config.diversity_pressure}")

    # 4. 运行挖掘
    print("\n[4] 开始 GP 挖掘...")
    start_t = time.time()
    results = miner.mine(df, code_col="code", date_col="date", price_col="close")
    elapsed = time.time() - start_t
    print(f"\n  挖掘完成: 耗时 {elapsed:.0f}s")

    # 5. 报告 Top 因子
    print("\n[5] Top-10 存活因子报告:")
    print("-" * 60)
    for i, (tree, fitness) in enumerate(results[:10]):
        has_amt = miner._has_amount_terminal(tree)
        amt_flag = "⚠️ AMOUNT" if has_amt else "✓ no-amount"
        formula = tree.to_formula()

        # 计算 amount 相关性 (抽样)
        try:
            sample_vals = tree.evaluate(df)
            amt_corr = compute_index_corr(sample_vals, df)
        except Exception:
            amt_corr = -1.0

        print(f"  #{i+1:02d}  fitness={fitness:.4f}  "
              f"depth={tree.depth}  complexity={tree.complexity:.1f}  "
              f"{amt_flag}  |corr(amount)|={amt_corr:.3f}")
        print(f"         formula: {formula}")
        print()

    # 6. 种群多样性总结
    print("\n[6] 种群多样性总结:")
    formula_set = set()
    amount_count = 0
    all_corrs = []
    for tree, _ in results:
        formula_set.add(miner._formula_signature(tree))
        if miner._has_amount_terminal(tree):
            amount_count += 1
        try:
            sv = tree.evaluate(df)
            ac = compute_index_corr(sv, df)
            all_corrs.append(ac)
        except Exception:
            pass

    print(f"  Top-50 唯一公式数: {len(formula_set)} / 50")
    print(f"  Top-50 含 amount 的个体: {amount_count} / 50")
    if all_corrs:
        print(f"  平均 |corr(amount)|: {float(np.mean(all_corrs)):.3f}")
        print(f"  最大 |corr(amount)|: {float(np.max(all_corrs)):.3f}")
        print(f"  低于 0.6 阈值比例: {sum(1 for c in all_corrs if c < 0.6) / len(all_corrs) * 100:.1f}%")

    # 7. 保存结果
    output = PROJECT_ROOT / "data" / "gp_mining_results.csv"
    rows = []
    for i, (tree, fitness) in enumerate(results[:50]):
        rows.append({
            "rank": i + 1,
            "fitness": round(fitness, 4),
            "depth": tree.depth,
            "complexity": round(tree.complexity, 2),
            "has_amount": miner._has_amount_terminal(tree),
            "formula": tree.to_formula(),
        })
    pdf = pd.DataFrame(rows)
    pdf.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n  结果已保存: {output}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="真实 A 股数据 GP 因子挖掘")
    parser.add_argument("--index", default="000300", help="指数代码 (000300=沪深300, 000905=中证500)")
    parser.add_argument("--start-date", default="20180101", help="起始日期")
    parser.add_argument("--end-date", default="20251231", help="结束日期")
    parser.add_argument("--max-stocks", type=int, default=300, help="最大股票数")
    parser.add_argument("--pop-size", type=int, default=100, help="种群大小")
    parser.add_argument("--n-generations", type=int, default=20, help="迭代代数")
    parser.add_argument("--max-depth", type=int, default=5, help="树最大深度")
    parser.add_argument("--tournament-size", type=int, default=3, help="锦标赛大小")
    parser.add_argument("--crossover-rate", type=float, default=0.7, help="交叉率")
    parser.add_argument("--mutation-rate", type=float, default=0.2, help="变异率")
    parser.add_argument("--elitism-ratio", type=float, default=0.05, help="精英比例")
    parser.add_argument("--holding-period", type=int, default=5, help="持有期")
    parser.add_argument("--complexity-penalty", type=float, default=0.05, help="复杂度惩罚")
    parser.add_argument("--amount-penalty", type=float, default=0.5, help="Amount 相关性惩罚权重")
    parser.add_argument("--diversity-pressure", type=float, default=0.3, help="多样性选择压力")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    run_gp_mining(args)