"""
测试 FinancialFactorBridge
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.custom_factors import compute_momentum_20d
from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.financial_bridge import (
    FinancialFactorBridge,
    FIELD_MAPPING_DICT,
)
from uniquant.services.scan_service import ScanPipeline, ScanConfig


class TestFinancialFactorBridge:
    """FinancialFactorBridge 测试类"""
    
    @pytest.fixture
    def bridge(self):
        return FinancialFactorBridge()
    
    @pytest.fixture
    def sample_financial_df(self):
        """创建示例财务数据"""
        return pd.DataFrame({
            "code": ["000001.SZ"] * 4,
            "report_date": pd.date_range("2023-03-31", periods=4, freq="QE"),
            "基本每股收益": [0.5, 0.6, 0.55, 0.65],
            "每股净资产": [10.0, 10.5, 11.0, 11.5],
            "净资产收益率": [5.0, 5.5, 5.0, 5.5],
        })
    
    @pytest.fixture
    def sample_daily_df(self):
        """创建示例日线数据"""
        return pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=100),
            "code": ["000001.SZ"] * 100,
            "open": np.random.uniform(10, 12, 100),
            "close": np.random.uniform(10, 12, 100),
            "qfq_close": np.random.uniform(10, 12, 100),
        })
    
    def test_field_mapping_dict(self):
        """测试字段映射字典"""
        assert "基本每股收益" in FIELD_MAPPING_DICT
        assert FIELD_MAPPING_DICT["基本每股收益"] == "eps"
        assert "每股净资产" in FIELD_MAPPING_DICT
        assert FIELD_MAPPING_DICT["每股净资产"] == "bps"
    
    def test_map_fields(self, bridge, sample_financial_df):
        """测试字段映射"""
        result = bridge.map_fields(sample_financial_df)
        
        assert "eps" in result.columns
        assert "bps" in result.columns
        assert "roe" in result.columns
        assert "基本每股收益" not in result.columns
    
    def test_map_fields_empty(self, bridge):
        """测试空 DataFrame 映射"""
        result = bridge.map_fields(pd.DataFrame())
        assert result.empty
    
    def test_calculate_eps_ttm(self, bridge, sample_financial_df):
        """测试 TTM EPS 计算"""
        mapped = bridge.map_fields(sample_financial_df)
        result = bridge.calculate_eps_ttm(mapped)
        
        assert "eps_ttm" in result.columns
        
        last_eps_ttm = result.iloc[-1]["eps_ttm"]
        expected = sample_financial_df["基本每股收益"].sum()
        assert abs(last_eps_ttm - expected) < 0.01
    
    def test_calculate_pe_pb(self, bridge, sample_daily_df, sample_financial_df):
        """测试 PE/PB 计算"""
        fin_mapped = bridge.map_fields(sample_financial_df)
        fin_with_ttm = bridge.calculate_eps_ttm(fin_mapped)
        
        result = bridge.calculate_pe_pb(sample_daily_df, fin_with_ttm)
        
        assert "pe_ttm" in result.columns
        assert "pb" in result.columns
    
    def test_calculate_pe_pb_missing_columns(self, bridge, sample_daily_df):
        """测试缺少必要列时的 PE/PB 计算"""
        daily_missing = sample_daily_df.drop(columns=["qfq_close"])
        
        result = bridge.calculate_pe_pb(daily_missing, pd.DataFrame())
        assert "pe_ttm" not in result.columns
        assert "pb" not in result.columns
    
    def test_process(self, bridge, sample_daily_df, sample_financial_df):
        """测试完整处理流程"""
        result = bridge.process(sample_daily_df, sample_financial_df)
        
        assert not result.empty
        assert "pe_ttm" in result.columns or result.empty
    
    def test_get_latest_factors(self, bridge, sample_financial_df):
        """测试获取最新财务因子"""
        result = bridge.get_latest_factors(sample_financial_df)
        
        assert not result.empty
        assert "code" in result.columns
        assert len(result) == 1
    
    def test_get_latest_factors_empty(self, bridge):
        """测试空数据获取最新因子"""
        result = bridge.get_latest_factors(pd.DataFrame())
        assert result.empty

    def test_map_fields_real_world_aliases(self, bridge):
        """测试真实财务湖字段别名兼容"""
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "report_date": [pd.Timestamp("2024-03-31")],
            "资产总计": [100.0],
            "负债合计": [60.0],
            "所有者权益（或股东权益）合计": [40.0],
            "归属于母公司所有者的净利润": [12.0],
            "四、利润总额": [15.0],
            "资产负债率(%)": [60.0],
            "流动比率(非金融类指标)": [1.8],
            "速动比率(非金融类指标)": [1.2],
            "销售毛利率(%)(非金融类指标)": [35.0],
            "销售净利率(%)": [12.0],
            "扣除非经常性损益后的净利润": [10.0],
        })

        result = bridge.map_fields(df)

        expected = [
            "total_assets",
            "total_liabilities",
            "equity",
            "net_profit_parent",
            "total_profit",
            "debt_ratio",
            "current_ratio",
            "quick_ratio",
            "gross_margin",
            "net_margin",
            "net_profit_deducted",
        ]
        for col in expected:
            assert col in result.columns

    def test_normalize_financial_code_formats(self, bridge):
        """测试财务 code 标准化为证券代码格式"""
        df = pd.DataFrame({
            "code": [1, "000001", "600000", "830001"],
            "report_date": pd.to_datetime(["2024-03-31"] * 4),
            "基本每股收益": [1.0, 1.0, 1.0, 1.0],
        })

        result = bridge.map_fields(df)

        assert result["code"].tolist() == [
            "000001.SZ",
            "000001.SZ",
            "600000.SH",
            "830001.BJ",
        ]

    def test_calculate_pe_pb_falls_back_to_close(self, bridge, sample_financial_df):
        """测试默认价格列缺失时降级到 close"""
        daily_df = pd.DataFrame({
            "date": pd.to_datetime(["2023-12-31", "2024-01-02"]),
            "code": ["000001.SZ", "000001.SZ"],
            "close": [10.0, 11.0],
        })

        fin_mapped = bridge.map_fields(sample_financial_df)
        fin_with_ttm = bridge.calculate_eps_ttm(fin_mapped)

        result = bridge.calculate_pe_pb(daily_df, fin_with_ttm)

        assert "pe_ttm" in result.columns
        assert "pb" in result.columns

    def test_calculate_pe_pb_uses_announcement_date_when_available(self, bridge):
        """测试优先使用公告日期对齐日线"""
        daily_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-04-10", "2024-04-30"]),
            "code": ["000001.SZ", "000001.SZ"],
            "close": [10.0, 12.0],
        })
        financial_df = pd.DataFrame({
            "code": ["000001.SZ"],
            "report_date": pd.to_datetime(["2024-03-31"]),
            "财报公告日期": [20240415],
            "基本每股收益": [2.0],
            "每股净资产": [4.0],
        })

        result = bridge.process(daily_df, financial_df, price_col="close")

        assert pd.isna(result.iloc[0]["pe_ttm"])
        assert result.iloc[1]["pe_ttm"] == pytest.approx(6.0)
        assert result.iloc[1]["pb"] == pytest.approx(3.0)


class TestScanPipelineFinancialIntegration:
    """ScanPipeline 财务集成测试"""

    def test_default_factor_cols_include_turnover_factor(self):
        config = ScanConfig()

        assert "turnover_momentum_20d" in config.factor_cols

    def test_build_factors_keeps_symbol_boundaries_for_rolling_factors(self):
        pipeline = ScanPipeline(config=ScanConfig(lightweight=True))
        original_factors = FactorRegistry._factors.copy()

        try:
            FactorRegistry._factors.clear()
            FactorRegistry.register(
                name="momentum_20d",
                compute_func=compute_momentum_20d,
                category="technical",
                default_weight=1.0,
            )

            dates = pd.date_range("2024-01-01", periods=25, freq="D")
            pipeline.daily_data = {
                "AAA": pd.DataFrame({
                    "date": dates,
                    "open": np.arange(1, 26, dtype=float),
                    "high": np.arange(1.1, 26.1, dtype=float),
                    "low": np.arange(0.9, 25.9, dtype=float),
                    "close": np.arange(1, 26, dtype=float),
                    "volume": np.arange(100, 125, dtype=float),
                    "amount": np.arange(1000, 1025, dtype=float),
                }),
                "BBB": pd.DataFrame({
                    "date": dates,
                    "open": np.arange(101, 126, dtype=float),
                    "high": np.arange(101.1, 126.1, dtype=float),
                    "low": np.arange(100.9, 125.9, dtype=float),
                    "close": np.arange(101, 126, dtype=float),
                    "volume": np.arange(200, 225, dtype=float),
                    "amount": np.arange(2000, 2025, dtype=float),
                }),
            }

            pipeline.build_factors()

            aaa = pipeline.combined_df[pipeline.combined_df["code"] == "AAA"].reset_index(drop=True)
            bbb = pipeline.combined_df[pipeline.combined_df["code"] == "BBB"].reset_index(drop=True)

            expected_aaa = pipeline.daily_data["AAA"]["close"].pct_change(20).reset_index(drop=True)
            expected_bbb = pipeline.daily_data["BBB"]["close"].pct_change(20).reset_index(drop=True)

            pd.testing.assert_series_equal(
                aaa["momentum_20d"].reset_index(drop=True),
                expected_aaa,
                check_names=False,
                check_dtype=False,
            )
            pd.testing.assert_series_equal(
                bbb["momentum_20d"].reset_index(drop=True),
                expected_bbb,
                check_names=False,
                check_dtype=False,
            )
        finally:
            FactorRegistry._factors = original_factors

    def test_load_data_supports_financial_subdir_override(self, tmp_path):
        data_dir = tmp_path / "data"
        daily_dir = data_dir / "lake" / "quotes" / "daily"
        financial_v2_dir = data_dir / "lake" / "financial_v2"
        daily_dir.mkdir(parents=True, exist_ok=True)
        financial_v2_dir.mkdir(parents=True, exist_ok=True)

        daily_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-04-10", "2024-04-30"]),
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.8, 10.8],
            "close": [10.0, 12.0],
            "volume": [1000, 1200],
            "amount": [10000, 14400],
        })
        daily_df.to_parquet(daily_dir / "000001.SZ.parquet", index=False)

        financial_df = pd.DataFrame({
            "code": ["000001.SZ"],
            "report_date": pd.to_datetime(["2024-03-31"]),
            "基本每股收益": [2.0],
            "每股净资产": [4.0],
        })
        financial_df.to_parquet(financial_v2_dir / "000001.SZ.parquet", index=False)

        pd.DataFrame(
            [{"code": "sz.000001", "代码": "000001", "type": 1, "status": 1}]
        ).to_csv(data_dir / "all_stock_codes.csv", index=False, encoding="utf-8-sig")

        pipeline = ScanPipeline(
            data_dir=str(data_dir),
            config=ScanConfig(financial_subdir="financial_v2"),
        )

        pipeline.load_data(symbols=["000001.SZ"])

        assert "000001.SZ" in pipeline.daily_data
        assert "000001.SZ" in pipeline.financial_data
        assert pipeline.financial_data["000001.SZ"]["code"].tolist() == ["000001.SZ"]

    def test_build_factors_merges_financial_metrics(self, monkeypatch):
        pipeline = ScanPipeline(config=ScanConfig())
        pipeline.daily_data = {
            "000001.SZ": pd.DataFrame({
                "date": pd.to_datetime(["2024-04-10", "2024-04-30"]),
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.8, 10.8],
                "close": [10.0, 12.0],
                "volume": [1000, 1200],
                "amount": [10000, 14400],
            })
        }
        pipeline.financial_data = {
            "000001.SZ": pd.DataFrame({
                "code": ["000001"],
                "report_date": pd.to_datetime(["2024-03-31"]),
                "财报公告日期": [20240415],
                "基本每股收益": [2.0],
                "每股净资产": [4.0],
            })
        }

        def fake_compute_all_factors(self, df):
            return pd.DataFrame(index=df.index)

        monkeypatch.setattr(
            "uniquant.brain.factors.composer.FactorComposer.compute_all_factors",
            fake_compute_all_factors,
        )

        pipeline.build_factors()

        assert "pe_ttm" in pipeline.combined_df.columns
        assert "pb" in pipeline.combined_df.columns
        assert pd.isna(pipeline.combined_df.iloc[0]["pe_ttm"])
        assert pipeline.combined_df.iloc[1]["pe_ttm"] == pytest.approx(6.0)
