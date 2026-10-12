"""
UniQuant Brain Forensics: OhlsonValuation & WinberryEuler Analyzer 测试
"""

import numpy as np
import pandas as pd

from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.forensics import (
    OhlsonValuationFactor,
    WinberryEulerAnalyzer,
)


class TestForensicsFactors:
    """测试 Ohlson 与 Winberry 因子实现与数理收敛性"""

    def test_registry_registration(self):
        """测试因子成功注册入 FactorRegistry"""
        if "ohlson_valuation" not in FactorRegistry._factors:
            FactorRegistry.register(
                name=OhlsonValuationFactor.name,
                compute_func=OhlsonValuationFactor().compute,
                category=OhlsonValuationFactor.category,
                default_weight=OhlsonValuationFactor.default_weight,
                description=OhlsonValuationFactor.description,
            )
        if "winberry_euler_drag" not in FactorRegistry._factors:
            FactorRegistry.register(
                name=WinberryEulerAnalyzer.name,
                compute_func=WinberryEulerAnalyzer().compute,
                category=WinberryEulerAnalyzer.category,
                default_weight=WinberryEulerAnalyzer.default_weight,
                description=WinberryEulerAnalyzer.description,
            )
        assert "ohlson_valuation" in FactorRegistry._factors
        assert "winberry_euler_drag" in FactorRegistry._factors
        
        info_ohlson = FactorRegistry._factors["ohlson_valuation"]
        assert info_ohlson.category == "forensics"
        
        info_winberry = FactorRegistry._factors["winberry_euler_drag"]
        assert info_winberry.category == "forensics"

    def test_ohlson_valuation_convergence_and_computation(self):
        """测试 Ohlson 经验贝叶斯后验与横截收敛裕度 >= 0.17"""
        factor = OhlsonValuationFactor(cost_of_equity_quarterly=0.02)
        
        # 构造跨期样本数据 (2 只标的各 8 期)
        records = []
        for code in ["000001", "600519"]:
            for t in range(8):
                records.append({
                    "code": code,
                    "report_date": 20220331 + t * 300,
                    "net_income": 10e8 + (t * 1e8 if code == "600519" else -t * 0.5e8),
                    "equity": 100e8 + t * 5e8,
                    "assets": 300e8 + t * 10e8,
                })
        df = pd.DataFrame(records)

        # 测试后验 omega 求解
        eb_map = factor.solve_empirical_bayes_omega(df)
        assert len(eb_map) == 2
        for code, omega_eb in eb_map.items():
            assert 0.15 <= omega_eb <= 0.85
            margin = (1.0 + factor.r_q) - omega_eb
            assert margin >= 0.17, f"股票 {code} 横截收敛裕度 {margin} < 0.17"

        # 测试因子得分计算
        scores = factor.compute(df)
        assert len(scores) == len(df)
        assert not scores.isna().any()
        assert not np.isinf(scores).any()
        # 600519 (index 15) 持续高盈利，其 Ohlson 价值因子得分应高于负增长的 000001 (index 7)
        assert scores.iloc[15] > scores.iloc[7]

    def test_winberry_euler_analyzer_computation(self):
        """测试 Winberry 投资欧拉方程在建工程拖累惩罚与因果 Alpha 粗筛"""
        analyzer = WinberryEulerAnalyzer(beta_cip=-0.0605)

        df = pd.DataFrame({
            "code": ["STOCK_A", "STOCK_B"],
            "cip": [100e8, 5e8],       # A: 在建工程极高 (挂起堰塞湖)
            "assets": [200e8, 200e8],   # 总资产相同
            "net_income": [10e8, 10e8],
            "equity": [50e8, 50e8],
        })

        scores = analyzer.compute(df)
        assert len(scores) == 2
        # A 在建工程占比 50%，B 仅 2.5%，故 A 受到更严重的负向欧拉拖累
        assert scores.iloc[1] > scores.iloc[0], "高在建工程标的未被正确惩罚"

        # 测试复合因果 Alpha
        omega_eb = pd.Series([0.40, 0.70])
        alpha = analyzer.compute_composite_causal_alpha(df, omega_eb_series=omega_eb)
        assert len(alpha) == 2
        assert alpha.iloc[1] > alpha.iloc[0]
