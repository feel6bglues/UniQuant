#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for ZCNMMCalculator (CAS Accounting Forensics Engine)
===========================================================
验证:
  1. 金融机构隔离引擎 (银行/证券/保险会计科目与代码特征准入豁免);
  2. 5 维会计法医指标单项计算 (DSRI, AQI, Sloan, DEPI, CashTrap);
  3. 申万行业 MAD 鲁棒截面标准化与 1%-99% Winsorization;
  4. 截面 Z_CNMM 复合排雷评分与 P75 一票否决门禁;
  5. 单标的逐笔评估接口 evaluate_record。
"""

import pandas as pd
import pytest

from uniquant.brain.factors.forensics.z_cnmm_calculator import (
    ZCNMMCalculator,
    evaluate_z_cnmm_cross_section,
)


class TestZCNMMCalculator:
    """Z_CNMM 五维法医排雷算子单元测试套件"""

    @pytest.fixture
    def sample_cross_section(self) -> pd.DataFrame:
        """构建合成的 10 家公司截面财务数据"""
        data = {
            "code": [f"{i:06d}" for i in range(1, 11)],
            "report_date": [20231231] * 10,
            "industry": ["医药生物"] * 5 + ["电子"] * 5,
            # 营收与应收
            "营业收入": [100.0, 120.0, 80.0, 200.0, 150.0, 300.0, 250.0, 180.0, 90.0, 50.0],
            "应收账款": [20.0, 25.0, 40.0, 30.0, 25.0, 50.0, 40.0, 35.0, 15.0, 10.0],
            # 资产与折旧
            "资产总计": [500.0, 600.0, 400.0, 1000.0, 800.0, 1500.0, 1200.0, 900.0, 450.0, 250.0],
            "流动资产合计": [250.0, 300.0, 180.0, 500.0, 400.0, 800.0, 600.0, 450.0, 220.0, 120.0],
            "固定资产": [150.0, 200.0, 120.0, 300.0, 250.0, 450.0, 350.0, 280.0, 130.0, 80.0],
            "在建工程": [30.0, 40.0, 80.0, 50.0, 45.0, 80.0, 70.0, 60.0, 20.0, 15.0],
            "固定资产折旧": [10.0, 12.0, 5.0, 25.0, 20.0, 35.0, 30.0, 22.0, 11.0, 6.0],
            "其他应收款": [5.0, 6.0, 20.0, 10.0, 8.0, 15.0, 12.0, 10.0, 4.0, 2.0],
            # 盈利与现金流
            "净利润": [10.0, 15.0, -5.0, 30.0, 20.0, 45.0, 35.0, 25.0, 8.0, 3.0],
            "经营活动产生的现金流量净额": [12.0, 14.0, -10.0, 35.0, 18.0, 50.0, 30.0, 20.0, 9.0, 4.0],
            # 存贷特征
            "货币资金": [80.0, 100.0, 50.0, 200.0, 150.0, 300.0, 220.0, 160.0, 70.0, 30.0],
            "短期借款": [20.0, 30.0, 100.0, 50.0, 40.0, 80.0, 60.0, 50.0, 15.0, 10.0],
            "利息收入": [1.5, 2.0, 0.1, 4.0, 3.0, 6.0, 4.5, 3.2, 1.2, 0.6],
        }
        return pd.DataFrame(data)

    def test_identify_financial_institution(self):
        """验证金融机构识别与隔离放行"""
        calc = ZCNMMCalculator()

        # 商业银行代码
        assert calc.identify_financial_institution({}, code="600036") is True
        assert calc.identify_financial_institution({}, code="000001") is True

        # 券商与保险
        assert calc.identify_financial_institution({}, code="600030") is True
        assert calc.identify_financial_institution({}, code="601318") is True

        # 行业标签识别
        assert calc.identify_financial_institution({"industry": "银行"}) is True
        assert calc.identify_financial_institution({"industry": "非银金融"}) is True

        # 普通工业制造业企业应被判定为 False
        assert calc.identify_financial_institution({"industry": "医药生物"}, code="600276") is False
        assert calc.identify_financial_institution({"industry": "电子"}, code="002415") is False

    def test_compute_individual_dimensions(self, sample_cross_section):
        """验证 DSRI, AQI, Sloan, DEPI, CashTrap 维度计算无异常"""
        calc = ZCNMMCalculator()
        df = sample_cross_section

        # 1. DSRI 应收异动
        dsri = calc.compute_dsri(df)
        assert len(dsri) == len(df)
        assert not dsri.isna().all()

        # 2. AQI 资产质量
        aqi = calc.compute_aqi(df)
        assert len(aqi) == len(df)
        assert (aqi >= 0.0).all()

        # 3. Sloan 应计
        sloan = calc.compute_sloan_accruals(df)
        assert len(sloan) == len(df)

        # 4. DEPI 折旧与在建
        depi = calc.compute_depi(df)
        assert len(depi) == len(df)

        # 5. CashTrap 存贷探针
        cashtrap_ratio, cashtrap_flags = calc.compute_cashtrap(df)
        assert len(cashtrap_ratio) == len(df)
        assert len(cashtrap_flags) == len(df)

    def test_mad_standardization_and_winsorization(self, sample_cross_section):
        """验证 1%-99% 极值截断与申万行业 MAD 鲁棒标准化"""
        calc = ZCNMMCalculator()
        df = sample_cross_section

        raw_series = df["在建工程"] / df["资产总计"]
        winsored = calc.winsorize_1_99(raw_series)
        assert len(winsored) == len(raw_series)

        mad_z = calc.mad_standardize_by_industry(winsored, df["industry"])
        assert len(mad_z) == len(raw_series)
        # MAD 标准化后中位数接近 0
        assert abs(mad_z.median()) < 0.5

    def test_compute_z_cnmm_cross_section_and_filter(self, sample_cross_section):
        """验证截面全量 Z_CNMM 计算与 P75 一票否决筛选"""
        calc = ZCNMMCalculator(p75_cutoff=0.75)
        df_res = calc.compute_z_cnmm(sample_cross_section)

        assert "z_cnmm" in df_res.columns
        assert "risk_percentile" in df_res.columns
        assert "is_blacklisted" in df_res.columns
        assert "status" in df_res.columns

        # 验证黑名单比例约在 25% 左右
        blacklisted = df_res[df_res["is_blacklisted"]]
        assert len(blacklisted) >= 1
        assert len(blacklisted) <= 4

        # 验证高危标的 (第 3 家公司亏损且在建激增) 处于排雷关注
        bad_co = df_res[df_res["code"] == "000003"]
        assert bad_co["z_cnmm"].iloc[0] > 0.0

        # 验证便利包装函数 evaluate_z_cnmm_cross_section
        df_quick = evaluate_z_cnmm_cross_section(sample_cross_section)
        assert isinstance(df_quick, pd.DataFrame)
        assert "z_cnmm" in df_quick.columns
        assert len(df_quick) == len(sample_cross_section)

    def test_evaluate_single_record(self):
        """验证单标的逐笔字典评估接口"""
        calc = ZCNMMCalculator()
        single_row = {
            "code": "000001",
            "report_date": 20231231,
            "industry": "银行",
            "营业收入": 1000.0,
            "资产总计": 50000.0,
        }
        res = calc.evaluate_record(single_row, code="000001")
        assert res["code"] == "000001"
        assert res["is_financial"] is True
        assert res["status"] == "ISOLATED_EXEMPT"
