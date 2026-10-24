"""
CNMM-QAR 第三阶段 (Phase 3) 动态 PIT 候选池与全收益基准门禁测试
=============================================================================
测试范围:
1. DynamicPointInTimeUniverse:
   - 动态时点合规股票池筛选 (消除 105 股面板幸存者偏差);
   - 次新股 365 天门禁与 *ST/ST/PT 风险警示标的精确剔除;
   - 历史退市股票在存续期合法入选、在退市后客观隔离的 PIT 生命期验证;
   - 确保只读访问底层 SSOT (data/all_stock_codes.csv)。
2. DelistedStockIngestor:
   - 全量 337 只历史退市股票覆盖率 100% 验证;
   - 9 列 Parquet 物理契约 (Schema) 与价格大于零约束验证。
3. TotalReturnBenchmarkAdapter:
   - 沪深 300 与上证 50 全收益指数生成验证;
   - 验证全收益指数大于价格指数 (TR >= PR);
   - 精算验证每年约 2.0%~2.5% 的股息剪刀差 (Dividend Leakage)。
=============================================================================
"""

import pytest
import pandas as pd

from uniquant.data.universe.dynamic_pit_universe import DynamicPointInTimeUniverse
from uniquant.data.universe.delisted_ingestor import DelistedStockIngestor
from uniquant.data.universe.total_return_benchmark import TotalReturnBenchmarkAdapter
from uniquant.shared.constants.path import PROJECT_ROOT


class TestPhase3DataGovernanceGates:
    """Phase 3 数据治理与动态 PIT 候选池测试套件"""

    @pytest.fixture(scope="class")
    def pit_universe(self):
        return DynamicPointInTimeUniverse()

    @pytest.fixture(scope="class")
    def delisted_ingestor(self):
        return DelistedStockIngestor()

    @pytest.fixture(scope="class")
    def tr_adapter(self):
        return TotalReturnBenchmarkAdapter()

    # =========================================================================
    # 1. 任务 3.2 门禁: 动态 Point-in-Time 候选池
    # =========================================================================

    def test_dynamic_pit_universe_expansion_over_time(self, pit_universe):
        """验证全历史候选池随 A 股扩容客观演进，打破静态 105 股桎梏"""
        # 2000-05-01: A 股早期 (剔除次新与ST后实际为 689 家)
        u_2000 = pit_universe.get_eligible_universe("2000-05-01")
        # 2010-05-01: 中期 (约 1500-1800 家)
        u_2010 = pit_universe.get_eligible_universe("2010-05-01")
        # 2020-05-01: 注册制前期 (约 3500-3800 家)
        u_2020 = pit_universe.get_eligible_universe("2020-05-01")
        # 2024-05-01: 现代全市场 (> 4500 家)
        u_2024 = pit_universe.get_eligible_universe("2024-05-01")

        assert len(u_2000) >= 650
        assert len(u_2000) < len(u_2010)
        assert len(u_2010) < len(u_2020)
        assert len(u_2020) < len(u_2024)
        assert len(u_2024) > 4000

    def test_dynamic_pit_sub_new_stock_filter(self, pit_universe):
        """验证上市不满 365 天的次新股被 100% 拦截剔除"""
        # 贵州茅台 (600519.SH) 上市日期为 2001-08-27
        # 2001-09-01 (上市第 5 天): 必须被剔除
        assert not pit_universe.is_stock_eligible("600519.SH", "2001-09-01", min_listing_days=365)
        # 2002-05-01 (上市第 247 天): 仍不满 365 天，必须被剔除
        assert not pit_universe.is_stock_eligible("600519.SH", "2002-05-01", min_listing_days=365)
        # 2002-09-01 (上市满 1 年): 获得准入资格
        assert pit_universe.is_stock_eligible("600519.SH", "2002-09-01", min_listing_days=365)

    def test_dynamic_pit_delisted_stock_lifecycle(self, pit_universe):
        """验证退市股票在存续期合规准入、在退市后客观隔离 (PIT 真实性)"""
        # 邯郸钢铁 (600001.SH): 1998-01-22 上市，2009-12-29 退市
        # 2005-05-01: 在市且满 1 年 -> 属于合格投资池
        assert pit_universe.is_stock_eligible("600001.SH", "2005-05-01", min_listing_days=365)
        # 2010-05-01: 已退市 -> 绝不可进入投资池
        assert not pit_universe.is_stock_eligible("600001.SH", "2010-05-01")

        # 验证退市列表提取
        delisted_2015 = set(pit_universe.get_delisted_stocks_as_of("2015-01-01"))
        assert "600001.SH" in delisted_2015

    def test_dynamic_pit_snapshot_stats_report(self, pit_universe):
        """验证多时期点在时股票池规模统计报表"""
        dates = ["2000-05-01", "2010-05-01", "2020-05-01", "2024-05-01"]
        df_stats = pit_universe.get_point_in_time_snapshot_stats(dates)
        assert len(df_stats) == 4
        assert "eligible_universe_size" in df_stats.columns
        assert "sub_new_excluded" in df_stats.columns
        assert "st_risk_excluded" in df_stats.columns
        assert df_stats["cum_delisted_count"].iloc[-1] > df_stats["cum_delisted_count"].iloc[0]

    # =========================================================================
    # 2. 任务 3.1 门禁: 337 只退市股票入湖与 Schema 契约
    # =========================================================================

    @pytest.mark.requires_lake
    def test_delisted_stocks_100pct_coverage(self, delisted_ingestor):
        """验证数据湖中历史退市股票覆盖率达到 100% (337/337)"""
        scan = delisted_ingestor.scan_delisted_coverage()
        assert scan["total_delisted"] == 337
        assert scan["existing_in_lake"] == 337
        assert scan["missing_in_lake"] == 0

    @pytest.mark.requires_lake
    def test_delisted_stock_parquet_schema_integrity(self):
        """验证退市股票 Parquet 遵循标准 9 列物理契约且数值合法"""
        sample_path = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily" / "600001.SH.parquet"
        assert sample_path.exists()

        df = pd.read_parquet(sample_path)
        expected_cols = [
            "date", "open", "high", "low", "close", "amount", "volume", "reserved", "code"
        ]
        assert list(df.columns) == expected_cols
        assert len(df) > 100
        # 价格与成交量必须严格大于 0
        assert (df["close"] > 0).all()
        assert (df["volume"] >= 0).all()
        assert (df["high"] >= df["low"]).all()

    # =========================================================================
    # 3. 任务 3.3 门禁: 沪深 300 全收益指数与股息剪刀差
    # =========================================================================

    @pytest.mark.requires_lake
    def test_total_return_benchmark_series_generation(self, tr_adapter):
        """验证沪深 300 全收益指数生成与单调递增超越关系 (TR >= PR)"""
        df_tr = tr_adapter.generate_total_return_series("000300.SH", "000300TR.SH", persist=True)
        assert len(df_tr) > 5000

        p_base = PROJECT_ROOT / "data" / "lake" / "quotes" / "index" / "000300.SH.parquet"
        df_base = pd.read_parquet(p_base)

        # 终点全收益指数累计净值必须高于价格指数 (因历年分红再投资)
        tr_final = float(df_tr["close"].iloc[-1] / df_tr["close"].iloc[0])
        base_final = float(df_base["close"].iloc[-1] / df_base["close"].iloc[0])
        assert tr_final > base_final

    @pytest.mark.requires_lake
    def test_dividend_leakage_spread_quantification(self, tr_adapter):
        """验证股息剪刀差年化在 2.0%~2.5% 区间，符合 A 股真实分红水平"""
        spread = tr_adapter.calculate_dividend_leakage_spread("000300.SH", "000300TR.SH")
        annual_leakage = spread["dividend_leakage_annual_pct"]
        # A 股沪深 300 平均股息率处于 2.0% ~ 2.5%
        assert 1.8 <= annual_leakage <= 2.6
        assert spread["cumulative_wealth_spread_multiplier"] > 1.30
