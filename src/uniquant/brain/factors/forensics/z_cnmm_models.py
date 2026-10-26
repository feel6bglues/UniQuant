#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant Brain Forensics: Z_CNMM 数据模型、字段映射与特征结构定义
================================================================================
模块路径: uniquant.brain.factors.forensics.z_cnmm_models
法医会计准则: CAS 14 (收入确认), CAS 8 (资产减值), CAS 31 (现金流量表), CAS 22/37 (金融工具)
"""

from dataclasses import dataclass
from typing import Dict, List


# ==============================================================================
# 字段别名表与 24 个核心投影科目 (用于 PyArrow/DuckDB 列投影下推消除 OOM)
# ==============================================================================
CORE_PROJECTED_COLUMNS: List[str] = [
    # 基础识别 (3)
    "code",
    "report_date",
    "industry",
    # 货币资金与借款 (5)
    "货币资金",
    "cash",
    "短期借款",
    "short_term_borrow",
    "其中:利息收入(利润表-财务费用)",
    "利息收入(万元)",
    "利息收入",
    # 营收与利润应计 (7)
    "应收账款",
    "accounts_rec",
    "其中：营业收入",
    "营业收入",
    "revenue",
    "五、净利润",
    "净利润",
    "归属于母公司所有者的净利润",
    "net_profit",
    "经营活动产生的现金流量净额",
    "ocf",
    # 资产与在建折旧 (8)
    "资产总计",
    "总资产",
    "total_assets",
    "流动资产合计",
    "current_assets",
    "固定资产",
    "ppe",
    "在建工程",
    "cip",
    "固定资产折旧、油气资产折耗、生产性生物资产折旧",
    "固定资产折旧",
    "depreciation",
    "其他应收款",
    "other_rec",
    # 金融特异性隔离科目 (8)
    "流动比率(非金融类指标)",
    "流动比率",
    "current_ratio",
    "向中央银行借款(万元)",
    "向中央银行借款",
    "central_bank_borrow",
    "客户存款和同业存放款项",
    "吸收存款及同业存放",
    "存出资本保证金",
    "代理买卖证券款",
    "保险责任准备金",
    "吸收存款",
    "拆入资金",
]

FINANCIAL_ALIASES: Dict[str, List[str]] = {
    "cash": ["货币资金", "cash"],
    "short_term_borrow": ["短期借款", "short_term_borrow", "short_term_loan"],
    "interest_income": [
        "其中:利息收入(利润表-财务费用)",
        "利息收入(万元)",
        "利息收入",
        "interest_income",
    ],
    "accounts_rec": ["应收账款", "accounts_rec", "accounts_receivable"],
    "revenue": ["其中：营业收入", "营业收入", "revenue", "operating_income"],
    "net_profit": ["五、净利润", "净利润", "归属于母公司所有者的净利润", "net_profit"],
    "ocf": ["经营活动产生的现金流量净额", "ocf", "operating_cash_flow"],
    "total_assets": ["资产总计", "总资产", "total_assets"],
    "current_assets": ["流动资产合计", "current_assets"],
    "ppe": ["固定资产", "ppe", "fixed_assets"],
    "cip": ["在建工程", "cip", "construction_in_progress"],
    "depreciation": [
        "固定资产折旧、油气资产折耗、生产性生物资产折旧",
        "固定资产折旧",
        "depreciation",
    ],
    "other_rec": ["其他应收款", "other_rec", "other_receivables"],
    "current_ratio": ["流动比率(非金融类指标)", "流动比率", "current_ratio"],
    "central_bank_borrow": [
        "向中央银行借款(万元)",
        "向中央银行借款",
        "central_bank_borrow",
    ],
    "code": ["code", "股票代码", "symbol", "ts_code"],
    "report_date": ["report_date", "报告期", "date", "fiscal_date"],
    "industry": [
        "industry",
        "sw_l1",
        "申万一级行业",
        "申万一级",
        "sw_industry",
        "sector",
    ],
}

# 常见已知商业银行代码集合 (6位代码)
KNOWN_BANKS = {
    "000001",
    "600036",
    "601398",
    "601939",
    "601288",
    "601988",
    "601328",
    "601166",
    "600919",
    "601009",
    "002142",
    "600926",
    "601658",
    "600000",
    "600016",
    "601818",
    "601998",
    "601997",
    "600908",
    "002807",
    "002839",
    "002936",
    "002948",
    "002958",
    "600901",
    "600928",
    "601077",
    "601128",
    "601187",
    "601229",
    "601528",
    "601577",
    "601665",
    "601825",
    "601838",
    "601860",
    "603323",
}

# 常见已知证券与保险代码集合
KNOWN_SECURITIES_INSURANCE = {
    "600030",
    "600999",
    "601066",
    "601688",
    "601788",
    "601878",
    "601881",
    "601901",
    "601995",
    "000776",
    "000783",
    "000728",
    "000712",
    "000686",
    "000166",
    "601236",
    "601377",
    "601456",
    "601318",
    "601628",
    "601336",
    "601601",
    "600291",
    "002736",
    "002926",
    "002939",
    "002945",
    "600958",
}

# 常见金融行业标签集合
FINANCIAL_INDUSTRY_LABELS = {
    "银行",
    "非银金融",
    "金融",
    "金融业",
    "Banking",
    "Financials",
    "Securities",
    "Insurance",
    "BankingFinance",
    "Bank",
}


@dataclass
class ZCNMMForensicEvaluation:
    """单个标的/财报期法医评估明细"""

    code: str
    report_date: int
    industry: str
    is_financial: bool
    is_exempt: bool
    status: str  # CLEAN_PASS, INTERCEPTED_ALERT, ISOLATED_EXEMPT
    dsri_raw: float
    aqi_raw: float
    sloan_raw: float
    depi_raw: float
    cashtrap_raw: float
    cashtrap_flag: bool
    dsri_z: float
    aqi_z: float
    sloan_z: float
    depi_z: float
    cashtrap_z: float
    z_cnmm: float
    risk_percentile: float
    is_blacklisted: bool
    is_whitelisted: bool
    verdict: str


@dataclass
class ZCNMMRecordEvaluation:
    """单期财报逐笔评估结构契约"""

    code: str
    report_date: int
    monetary_funds_yi: float
    short_term_borrow_yi: float
    interest_income_yi: float
    interest_rate_pct: float
    debt_ratio_pct: float
    is_financial: bool
    status: str
    cashtrap_flag: bool
    z_cnmm: float
    is_blacklisted: bool
    is_whitelisted: bool
    verdict: str


__all__ = [
    "CORE_PROJECTED_COLUMNS",
    "FINANCIAL_ALIASES",
    "KNOWN_BANKS",
    "KNOWN_SECURITIES_INSURANCE",
    "FINANCIAL_INDUSTRY_LABELS",
    "ZCNMMForensicEvaluation",
    "ZCNMMRecordEvaluation",
]
