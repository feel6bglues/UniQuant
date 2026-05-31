"""
字段映射验证测试
验证数据字段与源代码模块字段的一致性
"""

import pytest
from datetime import date
from pathlib import Path

import pandas as pd

from uniquant.shared.constants import DataSourceConstants
from uniquant.data.utils.normalizer import normalize_column_names
from uniquant.data.managers.stock_metadata_manager import StockMetadataManager, StockMetadata


class TestFieldMapping:
    """字段映射测试类"""
    
    def test_date_field_aliases(self):
        """测试日期字段别名映射"""
        df = pd.DataFrame({
            "日期": [20240101],
            "trade_date": [20240102],
            "dividOperateDate": [20240103],
        })
        
        normalized = normalize_column_names(df)
        
        assert "date" in normalized.columns
        assert normalized["date"].iloc[0] == 20240101
    
    def test_price_field_aliases(self):
        """测试价格字段别名映射"""
        df = pd.DataFrame({
            "开盘": [10.0],
            "收盘": [11.0],
            "最高": [12.0],
            "最低": [9.0],
        })
        
        normalized = normalize_column_names(df)
        
        assert "open" in normalized.columns
        assert "close" in normalized.columns
        assert "high" in normalized.columns
        assert "low" in normalized.columns
        assert normalized["open"].iloc[0] == 10.0
    
    def test_volume_field_aliases(self):
        """测试成交量字段别名映射"""
        df = pd.DataFrame({
            "vol": [1000000],
            "amount": [10000000],
        })
        
        normalized = normalize_column_names(df)
        
        assert "volume" in normalized.columns
        assert normalized["volume"].iloc[0] == 1000000
    
    def test_change_rate_field_aliases(self):
        """测试涨跌幅字段别名映射"""
        df = pd.DataFrame({
            "pct_change": [2.5],
            "涨跌额": [0.25],
        })
        
        normalized = normalize_column_names(df)
        
        assert "change_rate" in normalized.columns
        assert "change_amount" in normalized.columns
    
    def test_metadata_field_aliases(self):
        """测试元数据字段别名映射"""
        df = pd.DataFrame({
            "ipoDate": ["20200101"],
            "outDate": ["20251231"],
            "sector": ["科技"],
            "type": ["股票"],
            "status": ["上市"],
        })
        
        normalized = normalize_column_names(df)
        
        assert "ipo_date" in normalized.columns
        assert "delist_date" in normalized.columns
        assert "sector" in normalized.columns
        assert "stock_type" in normalized.columns
        assert "stock_status" in normalized.columns
    
    def test_factor_field_aliases(self):
        """测试复权因子字段别名映射"""
        df = pd.DataFrame({
            "foreAdjustFactor": [1.5],
            "backAdjustFactor": [1.2],
            "adjustFactor": [1.3],
        })
        
        normalized = normalize_column_names(df)
        
        assert "qfq_factor" in normalized.columns
        assert "hfq_factor" in normalized.columns
        assert "adj_factor" in normalized.columns


class TestDataSourceConstants:
    """数据源常量测试类"""
    
    def test_date_cols_exist(self):
        """测试日期列别名存在"""
        assert hasattr(DataSourceConstants, "DATE_COLS")
        assert "date" in DataSourceConstants.DATE_COLS
        assert "trade_date" in DataSourceConstants.DATE_COLS
    
    def test_price_cols_exist(self):
        """测试价格列别名存在"""
        assert hasattr(DataSourceConstants, "OPEN_COLS")
        assert hasattr(DataSourceConstants, "CLOSE_COLS")
        assert hasattr(DataSourceConstants, "HIGH_COLS")
        assert hasattr(DataSourceConstants, "LOW_COLS")
    
    def test_volume_cols_exist(self):
        """测试成交量列别名存在"""
        assert hasattr(DataSourceConstants, "VOLUME_COLS")
        assert "volume" in DataSourceConstants.VOLUME_COLS
        assert "vol" in DataSourceConstants.VOLUME_COLS
    
    def test_change_rate_cols_exist(self):
        """测试涨跌幅列别名存在"""
        assert hasattr(DataSourceConstants, "CHANGE_RATE_COLS")
        assert "pct_change" in DataSourceConstants.CHANGE_RATE_COLS
    
    def test_metadata_cols_exist(self):
        """测试元数据列别名存在"""
        assert hasattr(DataSourceConstants, "SECTOR_COLS")
        assert hasattr(DataSourceConstants, "IPO_DATE_COLS")
        assert hasattr(DataSourceConstants, "DELIST_DATE_COLS")
        assert hasattr(DataSourceConstants, "STOCK_TYPE_COLS")
        assert hasattr(DataSourceConstants, "STOCK_STATUS_COLS")


class TestStockMetadataManager:
    """股票元数据管理器测试类"""
    
    def test_metadata_dataclass(self):
        """测试StockMetadata数据类"""
        metadata = StockMetadata(
            code="000001",
            name="平安银行",
            market="SZ",
            sector="银行",
            ipo_date=date(1991, 4, 3),
        )
        
        assert metadata.code == "000001"
        assert metadata.name == "平安银行"
        assert metadata.market == "SZ"
        assert metadata.sector == "银行"
        assert metadata.ipo_date == date(1991, 4, 3)
    
    def test_infer_market(self):
        """测试市场推断"""
        manager = StockMetadataManager()
        
        assert manager._infer_market("000001") == "SZ"
        assert manager._infer_market("600000") == "SH"
        assert manager._infer_market("300001") == "SZ"
        assert manager._infer_market("830001") == "BJ"


class TestFieldMappingIntegration:
    """字段映射集成测试类"""
    
    def test_full_normalization_flow(self):
        """测试完整标准化流程"""
        raw_df = pd.DataFrame({
            "日期": [20240101, 20240102],
            "开盘": [10.0, 10.5],
            "收盘": [10.5, 11.0],
            "最高": [11.0, 11.5],
            "最低": [9.5, 10.0],
            "vol": [1000000, 1200000],
            "成交额": [10000000, 12000000],
            "pct_change": [5.0, 4.76],
        })
        
        normalized = normalize_column_names(raw_df)
        
        expected_cols = ["date", "open", "close", "high", "low", "volume", "amount", "change_rate"]
        for col in expected_cols:
            assert col in normalized.columns, f"缺少标准字段: {col}"
    
    def test_parquet_field_coverage(self):
        """测试Parquet文件字段覆盖率"""
        data_dir = Path("./data")
        daily_dir = data_dir / "lake" / "quotes" / "daily"
        
        if not daily_dir.exists():
            pytest.skip("日线数据目录不存在")
        
        parquet_files = list(daily_dir.glob("*.parquet"))
        if not parquet_files:
            pytest.skip("没有日线数据文件")
        
        sample_file = parquet_files[0]
        df = pd.read_parquet(sample_file)
        normalized = normalize_column_names(df)
        
        required_fields = ["date", "open", "high", "low", "close", "volume"]
        missing_fields = [f for f in required_fields if f not in normalized.columns]
        
        assert not missing_fields, f"缺少必要字段: {missing_fields}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
