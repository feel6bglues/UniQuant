"""
测试 AnalysisService 中 strength 计算的除零防御

核心目标：
1. 验证 open == 0 时 strength 不产生 Inf
2. 验证正常数据时 strength 计算正确
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from uniquant.services.analysis_service_legacy import AnalysisService


class TestStrengthDivZeroDefense:
    """strength 计算除零防御测试"""

    @pytest.fixture
    def service(self):
        mock_data_service = MagicMock()
        mock_data_service.stock_map = {"000001.SZ": "平安银行", "000002.SZ": "万科A", "000003.SZ": "测试股"}
        mock_data_service.get_stock_name.side_effect = lambda code: mock_data_service.stock_map.get(code, "未知")
        mock_data_service.refresh_stock_map = MagicMock()
        return AnalysisService(data_service=mock_data_service)

    # ------------------------------------------------------------------ #
    #  测试 1：open == 0 → strength 不应产生 Inf
    # ------------------------------------------------------------------ #
    def test_strength_zero_open_no_inf(self, service):
        """open 为 0 时，strength 不应产生 Inf。"""
        df = pd.DataFrame({
            "code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "close": [10.0, 20.0, 30.0],
            "open": [9.5, 0.0, 19.0],
            "volume": [100000, 200000, 300000],
            "date": pd.to_datetime(["2024-01-15", "2024-01-15", "2024-01-15"]),
        })

        result = service.enrich_lake_data(df)

        assert "Strength" in result.columns
        assert not np.isinf(result["Strength"]).any(), (
            f"strength contains Inf: {result['Strength'].tolist()}"
        )

    # ------------------------------------------------------------------ #
    #  测试 2：正常数据 → strength 计算正确
    # ------------------------------------------------------------------ #
    def test_strength_normal_data(self, service):
        """正常数据时，strength = (close - open) / open。"""
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "close": [11.0],
            "open": [10.0],
            "volume": [100000],
            "date": pd.to_datetime(["2024-01-15"]),
        })

        result = service.enrich_lake_data(df)

        expected = round((11.0 - 10.0) / 10.0, 4)
        assert np.isclose(result.iloc[0]["Strength"], expected, atol=1e-4)

    # ------------------------------------------------------------------ #
    #  测试 3：pct_change 列存在 → 使用 pct_change 而非 open
    # ------------------------------------------------------------------ #
    def test_strength_uses_pct_change_when_available(self, service):
        """当 pct_change 列存在时，应使用 pct_change / 100。"""
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "close": [11.0],
            "open": [10.0],
            "volume": [100000],
            "date": pd.to_datetime(["2024-01-15"]),
            "pct_change": [5.0],
        })

        result = service.enrich_lake_data(df)

        expected = round(5.0 / 100.0, 4)
        assert np.isclose(result.iloc[0]["Strength"], expected, atol=1e-4)

    # ------------------------------------------------------------------ #
    #  测试 4：全零 open → 全部 strength 为 NaN 或 0
    # ------------------------------------------------------------------ #
    def test_strength_all_zero_open(self, service):
        """所有 open 都为 0 时，strength 不应产生 Inf。"""
        df = pd.DataFrame({
            "code": ["000001.SZ", "000002.SZ"],
            "close": [10.0, 20.0],
            "open": [0.0, 0.0],
            "volume": [100000, 200000],
            "date": pd.to_datetime(["2024-01-15", "2024-01-15"]),
        })

        result = service.enrich_lake_data(df)

        assert not np.isinf(result["Strength"]).any()
