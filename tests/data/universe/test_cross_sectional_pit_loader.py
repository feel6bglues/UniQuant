#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for CrossSectionalPITDataLoader (DuckDB + Polars Accelerated Dynamic PIT)
"""

import time
import pytest
import polars as pl

from uniquant.data.universe.dynamic_pit_loader import CrossSectionalPITDataLoader
from uniquant.data.universe.dynamic_pit_universe import DynamicPointInTimeUniverse


@pytest.mark.requires_lake
class TestCrossSectionalPITDataLoader:
    """验证 DuckDB + Polars 跨截面点在时财报与行情关联引擎"""

    @pytest.fixture(scope="class")
    def loader(self):
        return CrossSectionalPITDataLoader()

    @pytest.fixture(scope="class")
    def pit_universe(self):
        return DynamicPointInTimeUniverse()

    def test_symbol_normalization(self, loader):
        """验证股票代码归一化契约"""
        assert loader._normalize_symbol("000001") == "000001.SZ"
        assert loader._normalize_symbol("600519") == "600519.SH"
        assert loader._normalize_symbol("sh.600000") == "600000.SH"
        assert loader._normalize_symbol("sz.000002") == "000002.SZ"
        assert loader._normalize_symbol("000001.SZ") == "000001.SZ"
        assert loader._normalize_symbol("920002") == "920002.BJ"

    def test_duckdb_financial_scan_to_polars(self, loader):
        """验证 DuckDB 并行读取全市场财报与 Polars 衍生计算"""
        t0 = time.time()
        df_fin = loader.load_all_financial_reports()
        t1 = time.time()

        assert isinstance(df_fin, pl.DataFrame)
        assert len(df_fin) > 40000, f"财报记录过少: {len(df_fin)}"
        assert t1 - t0 < 15.0, f"财报加载耗时过长: {t1 - t0:.2f}s"

        # 检查关键法医衍生列
        required_cols = ["code", "year", "cfo_yi", "total_assets_yi", "cip_ratio", "oth_rec_ratio", "roe", "cfo_ratio"]
        for col in required_cols:
            assert col in df_fin.columns, f"缺失衍生指标列: {col}"

    def test_duckdb_cross_section_prices(self, loader):
        """验证 DuckDB 向量化提取指定截面日价格矩阵"""
        dates = ["2024-05-06", "2024-02-01"]
        t0 = time.time()
        df_prices = loader.load_cross_section_prices(dates)
        t1 = time.time()

        assert isinstance(df_prices, pl.DataFrame)
        assert len(df_prices) > 8000, f"价格记录数不足: {len(df_prices)}"
        assert t1 - t0 < 5.0, f"价格截面查询耗时过长: {t1 - t0:.2f}s"
        assert "trade_date" in df_prices.columns
        assert "close" in df_prices.columns

    def test_cross_sectional_screening_performance_and_accuracy(self, loader, pit_universe):
        """验证全市场 4,643+ 标的单截面纯因果 Alpha 筛选耗时与结果正确性"""
        as_of_date = "2024-05-06"
        prior_date = "2024-02-01"
        fiscal_year = 2023

        eligible = pit_universe.get_eligible_universe(as_of_date, min_listing_days=365, exclude_st=True)
        assert len(eligible) > 3000

        df_prices = loader.load_cross_section_prices([as_of_date, prior_date])

        t0 = time.time()
        res = loader.screen_and_score_cross_section(
            as_of_date=as_of_date,
            fiscal_year=fiscal_year,
            eligible_symbols=eligible,
            df_prices=df_prices,
            prior_60_date=prior_date,
            top_n=40,
        )
        t1 = time.time()

        elapsed_ms = (t1 - t0) * 1000.0
        assert elapsed_ms < 1000.0, f"单截面因果筛选耗时超标: {elapsed_ms:.1f}ms"

        selected = res["selected_symbols"]
        assert len(selected) == 40, f"优选组合数量不足: {len(selected)}"
        diag = res["diagnostics"]
        assert diag["s3_cde_survivors"] > 2000
        assert diag["s6_cnmm_safe_candidates"] > 1500
        assert diag["screening_latency_ms"] < 1000.0
