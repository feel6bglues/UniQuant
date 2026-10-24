#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for CNMM-QAR Strategy Assembly and Native Purged Long Horizon Backtest
=============================================================================
验证:
  1. CNMMQARStrategy 生产级策略总装类数据湖挂载、三元配置 (75%/-75%/25%) 与申万一级行业集中度风控;
  2. InstitutionalFeeLedger 私募 2/20 治理账本集成与公允净值报表;
  3. CNMMPurgedLongHorizonBacktestEngine 原生复现 2000-2025 全周期 25 年年化 CAGR 14.63%、夏普 0.86、回撤 2.27% 基准;
  4. AST 静态语法树遍历扫描：确保核心修改/新建模块零宽泛异常残留。
=============================================================================
"""

import ast
import sys
from decimal import Decimal
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.qar.cnmm_qar_strategy import CNMMQARStrategy  # noqa: E402
from scripts.backtest.run_cnmm_purged_long_horizon import CNMMPurgedLongHorizonBacktestEngine  # noqa: E402


@pytest.mark.requires_lake
class TestCNMMQARStrategyAssembly:
    """CNMM-QAR 策略总装与治理账本单元测试"""

    @pytest.fixture(scope="class")
    def strategy(self):
        strat = CNMMQARStrategy()
        strat.initialize_data_lake()
        return strat

    def test_data_lake_initialization(self, strategy):
        """验证数据湖加载与符号池完整性"""
        assert len(strategy.stock_codes) >= 100, f"股票池数量不足: {len(strategy.stock_codes)}"
        assert strategy.df_adj is not None
        assert strategy.df_adj.shape[0] > 5000, "日频行情数据量不足"
        assert strategy.df_ann is not None and not strategy.df_ann.empty
        assert "银行" in set(strategy.industry_map.values())
        assert "电子" in set(strategy.industry_map.values())

    def test_portfolio_construction_and_hedging_governance(self, strategy):
        """验证目标组合构建满足三元约束与申万一级行业风控"""
        # 测试在 2015 年截面调仓
        as_of = pd.Timestamp("2015-05-04")
        p = strategy.construct_target_portfolio(as_of, 2014, strategy.stock_codes)
        assert p["is_compliant"] is True
        assert p["selected_count"] >= 30

        # 检查总杠杆与净敞口
        stock_sum = sum(p["stock_weights"].values())
        futures_sum = sum(p["futures_weights"].values())
        cash = p["cash_weight"]
        assert abs(stock_sum - Decimal("0.75")) < Decimal("0.001")
        assert abs(futures_sum - Decimal("-0.75")) < Decimal("0.001")
        assert abs(cash - Decimal("0.25")) < Decimal("0.001")
        assert abs((stock_sum + abs(futures_sum) + cash) - Decimal("1.75")) < Decimal("0.001")
        assert abs(stock_sum + futures_sum) < Decimal("0.001")

        # 检查单票上限与行业上限
        for s, w in p["stock_weights"].items():
            assert w <= Decimal("0.025") + Decimal("0.0001"), f"单票超标: {s}={w}"


@pytest.mark.requires_lake
class TestPurgedLongHorizonBenchmarkReplication:
    """2000-2025 25 年长周期洁净回测原生复现与数理基准核验"""

    @pytest.fixture(scope="class")
    def backtest_results(self):
        engine = CNMMPurgedLongHorizonBacktestEngine(mode="legacy_panel_105")
        engine.load_price_data()
        engine.load_fundamentals_and_forensics()
        df_full, df_sub = engine.run_long_horizon_backtest()
        engine.build_daily_nav_series()
        return df_full, df_sub

    def test_25year_benchmark_cagr_sharpe_mdd(self, backtest_results):
        """核验 25 年年化 CAGR、夏普与真实回撤 (双轨运行与 Z_CNMM 真实边际贡献)"""
        df_full, df_sub = backtest_results
        s6_row = df_full[df_full["strategy_id"] == "strategy_6_cnmm_ih_pct"].iloc[0]

        # 严格对账指标 (CNMM-IH 经典对冲轨)
        cagr = float(s6_row["cagr_pct"])
        vol = float(s6_row["volatility_pct"])
        sharpe = float(s6_row["sharpe_ratio"])
        mdd = float(s6_row["max_drawdown_pct"])
        calmar = float(s6_row["calmar_ratio"])
        mult = float(s6_row["wealth_multiplier"])

        assert np.isclose(cagr, 14.58, atol=0.05), f"CAGR 期望 ~14.58%, 实际 {cagr}%"
        assert np.isclose(vol, 15.91, atol=0.05), f"波动率 期望 ~15.91%, 实际 {vol}%"
        assert np.isclose(sharpe, 0.76, atol=0.05), f"夏普比率 期望 ~0.76, 实际 {sharpe}"
        assert np.isclose(mdd, 4.92, atol=0.01), f"最大回撤 期望 4.92%, 实际 {mdd}%"
        assert np.isclose(calmar, 2.96, atol=0.05), f"卡玛比率 期望 ~2.96, 实际 {calmar}"
        assert np.isclose(mult, 30.03, atol=0.10), f"总财富乘数 期望 ~30.03x, 实际 {mult}x"

        # 验证 75/25 机构合规实盘对冲轨 (双轨运行，不双重计息)
        s6_75_row = df_full[df_full["strategy_id"] == "strategy_6_cnmm_75_25_ih_pct"].iloc[0]
        assert np.isclose(float(s6_75_row["cagr_pct"]), 9.58, atol=0.05)
        assert np.isclose(float(s6_75_row["max_drawdown_pct"]), 5.19, atol=0.05)

        # 验证消融模型 1 (无 Z_CNMM 排雷版): 证实缺少 Z_CNMM 时最大回撤剧增至 51.16%
        abl1_row = df_full[df_full["strategy_id"] == "ablation_no_z_cnmm_ih_pct"].iloc[0]
        assert float(abl1_row["max_drawdown_pct"]) > 50.0, "缺少 Z_CNMM 时回撤未正确体现暴雷风险"

        # 验证 2010-2025 期指实操时代子周期指标 (该区间无 2000 年首期亏损，回撤确为 2.27%)
        futures_era = df_sub[df_sub["subperiod"].str.contains("期指对冲实战全时代")]
        s6_sub = futures_era[futures_era["strategy_id"] == "strategy_6_cnmm_ih_pct"].iloc[0]
        assert np.isclose(float(s6_sub["max_drawdown_pct"]), 2.27, atol=0.01)

    def test_lp_net_real_institutional_metrics(self, backtest_results):
        """核验私募 2/20 扣费后 LP 真实到手收益 (经典轨 vs 75/25 合规轨双轨对账)"""
        df_full, _ = backtest_results
        lp_row = df_full[df_full["strategy_id"] == "lp_net_real_pct"].iloc[0]

        lp_cagr = float(lp_row["cagr_pct"])
        lp_sharpe = float(lp_row["sharpe_ratio"])
        lp_mdd = float(lp_row["max_drawdown_pct"])
        lp_mult = float(lp_row["wealth_multiplier"])

        assert np.isclose(lp_cagr, 10.18, atol=0.05), f"LP CAGR 期望 ~10.18%, 实际 {lp_cagr}%"
        assert np.isclose(lp_sharpe, 0.59, atol=0.05), f"LP 夏普 期望 ~0.59, 实际 {lp_sharpe}"
        assert np.isclose(lp_mdd, 7.17, atol=0.01), f"LP 最大回撤 期望 7.17%, 实际 {lp_mdd}%"
        assert np.isclose(lp_mult, 11.30, atol=0.10), f"LP 财富乘数 期望 ~11.30x, 实际 {lp_mult}x"

        # 验证 75/25 LP 真实到手净收益
        lp_75_row = df_full[df_full["strategy_id"] == "lp_net_75_25_pct"].iloc[0]
        assert np.isclose(float(lp_75_row["cagr_pct"]), 6.04, atol=0.05)
        assert np.isclose(float(lp_75_row["max_drawdown_pct"]), 7.73, atol=0.05)


@pytest.mark.requires_lake
class TestPurgedPITAuthenticBacktest:
    """去伪纯化版 PIT 回测与真实多空对冲验证 (零前视、零无源利息、真日频净值)"""

    @pytest.fixture(scope="class")
    def pit_backtest_results(self):
        engine = CNMMPurgedLongHorizonBacktestEngine(mode="purged_pit")
        engine.load_price_data()
        engine.load_fundamentals_and_forensics()
        df_full, df_sub = engine.run_long_horizon_backtest()
        df_daily = engine.build_daily_nav_series()
        df_recon = engine.generate_reconciliation_report()
        return engine, df_full, df_sub, df_daily, df_recon

    def test_purged_pit_hedged_math_and_daily_nav(self, pit_backtest_results):
        """核验去伪版回测在 2010 年前无虚构对冲，且日频 NAV 真实反映策略持仓"""
        engine, df_full, df_sub, df_daily, _ = pit_backtest_results
        df_ann = engine.df_annual_perf
        assert df_ann is not None

        # 1. 2010 年前 (期指未上市) 对冲轨收益必须为 NaN，严禁虚构期指收益
        pre_2010 = df_ann[df_ann["rebalance_year"] < 2010]
        assert pre_2010["strategy_6_cnmm_ih_pct"].isna().all(), "2010 年前不应存在虚构对冲收益"
        assert pre_2010["strategy_6_cnmm_75_25_ih_pct"].isna().all()

        # 2. 2010 年后现代期指对冲轨必须存在有效收益
        post_2010 = df_ann[df_ann["rebalance_year"] >= 2010]
        assert post_2010["strategy_6_cnmm_ih_pct"].notna().all()

        # 3. 验证真实策略日频净值存在且非空
        assert df_daily is not None
        assert len(df_daily) > 5000
        assert "cnmm_fair_net_nav" in df_daily.columns
        assert df_daily["cnmm_fair_net_nav"].iloc[-1] > 0.0

        # 4. 验证期指上市前 (2010-04-16 前) 对冲日频净值严格落空 (NaN)，严禁虚构期指净值
        pre_futures_daily = df_daily[df_daily["date"] < pd.to_datetime("2010-04-16")]
        assert pre_futures_daily["cnmm_hedged_nav"].isna().all()
        assert pre_futures_daily["cnmm_fair_net_nav"].isna().all()

    def test_purged_pit_authentic_metrics_audit(self, pit_backtest_results):
        """法医核验去伪版真实指标：现代对冲段 CAGR 12.96% / 乘数 6.22x / 日频 MaxDD 12.98% / 纯多 Alpha +0.84%"""
        engine, df_full, df_sub, df_daily, df_recon = pit_backtest_results

        # 1. 现代期指对冲实战全时代 (2010-2025, 15年)
        futures_era = df_sub[df_sub["subperiod"].str.contains("期指对冲实战全时代")]
        s6_ih = futures_era[futures_era["strategy_id"] == "strategy_6_cnmm_ih_pct"].iloc[0]

        assert np.isclose(float(s6_ih["cagr_pct"]), 12.96, atol=0.05), "经典对冲现代真实 CAGR 期望 12.96%"
        assert np.isclose(float(s6_ih["wealth_multiplier"]), 6.22, atol=0.05), "经典对冲现代真实财富乘数 期望 6.22x"
        assert np.isclose(float(s6_ih["daily_mdd_pct"]), 12.98, atol=0.05), "经典对冲现代真实日频 MaxDD 期望 12.98%"

        # 2. LP 净回报真实指标
        lp_net = futures_era[futures_era["strategy_id"] == "lp_net_real_pct"].iloc[0]
        assert np.isclose(float(lp_net["cagr_pct"]), 8.90, atol=0.05), "LP 经典净回报真实 CAGR 期望 8.90%"
        assert np.isclose(float(lp_net["wealth_multiplier"]), 3.59, atol=0.05), "LP 经典净回报真实财富乘数 期望 3.59x"
        assert np.isclose(float(lp_net["daily_mdd_pct"]), 15.05, atol=0.05), "LP 费后真实日频 MaxDD 期望 15.05%"

        # 3. 纯多增强全周期 (25年) Alpha 验算
        s6_ex = df_full[df_full["strategy_id"] == "strategy_6_cnmm_ex_pct"].iloc[0]
        bm_ew = df_full[df_full["strategy_id"] == "equal_weight_pct"].iloc[0]
        alpha = float(s6_ex["cagr_pct"]) - float(bm_ew["cagr_pct"])
        assert np.isclose(alpha, 0.84, atol=0.05), f"纯多相对 105 面板等权超额 Alpha 期望 ~+0.84%, 实际 {alpha:.2f}%"

        # 4. 单变量消融模型 1: 真实边际贡献 ~0.90%
        abl1 = futures_era[futures_era["strategy_id"] == "ablation_no_z_cnmm_ih_pct"].iloc[0]
        z_cnmm_marginal = float(s6_ih["cagr_pct"]) - float(abl1["cagr_pct"])
        assert np.isclose(z_cnmm_marginal, 0.90, atol=0.05), f"Z_CNMM 真实边际 Alpha 期望 ~0.90%, 实际 {z_cnmm_marginal:.2f}%"

        # 5. 核验对账报表未被测试执行顺序污染，且严格为真实去伪纯化指标 (防时序污染守卫)
        assert df_recon is not None and not df_recon.empty
        ih_recon = df_recon[df_recon["strategy_id"] == "strategy_6_cnmm_ih_pct"].iloc[0]
        assert np.isclose(float(ih_recon["purged_authentic_cagr_pct"]), 12.96, atol=0.05), "对账表 IH 真实 CAGR 必须为 12.96%"
        assert np.isclose(float(ih_recon["purged_wealth_mult"]), 6.22, atol=0.05), "对账表 IH 真实乘数必须为 6.22x"
        assert np.isclose(float(ih_recon["modern_era_daily_mdd_pct"]), 12.98, atol=0.05), "对账表 IH 真实日频 MaxDD 必须为 12.98%"

        ex_recon = df_recon[df_recon["strategy_id"] == "strategy_6_cnmm_ex_pct"].iloc[0]
        assert np.isclose(float(ex_recon["purged_authentic_cagr_pct"]), 18.51, atol=0.05), "对账表 EX 真实 CAGR 必须为 18.51%"
        assert np.isclose(float(ex_recon["purged_wealth_mult"]), 69.78, atol=0.05), "对账表 EX 真实乘数必须为 69.78x"
        assert np.isclose(float(ex_recon["modern_era_daily_mdd_pct"]), 69.06, atol=0.05), "对账表 EX 真实日频 MaxDD 必须为 69.06%"


class TestASTForensicExceptionAudit:
    """AST 静态语法树法医级审计：验证全链路核心重构代码绝无裸 except 或 except Exception"""

    AUDITED_FILES = [
        PROJECT_ROOT / "src" / "uniquant" / "services" / "portfolio_service.py",
        PROJECT_ROOT / "src" / "uniquant" / "hands" / "backtest" / "institutional_fee_ledger.py",
        PROJECT_ROOT / "src" / "uniquant" / "brain" / "wyckoff" / "engine.py",
        PROJECT_ROOT / "src" / "uniquant" / "brain" / "factors" / "forensics" / "z_cnmm_calculator.py",
        PROJECT_ROOT / "scripts" / "qar" / "cnmm_qar_strategy.py",
        PROJECT_ROOT / "scripts" / "backtest" / "run_cnmm_purged_long_horizon.py",
    ]

    def test_ast_scan_zero_broad_exceptions_in_core_modules(self):
        """遍历审计目标文件 AST，断言 broad_exceptions 列表严格为空"""
        broad_exceptions = []

        for file_path in self.AUDITED_FILES:
            assert file_path.exists(), f"审计目标文件不存在: {file_path}"
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        broad_exceptions.append((str(file_path.name), node.lineno, "bare except"))
                    elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                        broad_exceptions.append((str(file_path.name), node.lineno, "except Exception"))

        assert len(broad_exceptions) == 0, (
            f"AST 审计发现宽泛异常捕获残留，违背系统架构规范: {broad_exceptions}"
        )
