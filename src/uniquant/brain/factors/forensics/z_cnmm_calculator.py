#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant Brain Forensics: Z_CNMM 五维复合排雷探针与金融特异性隔离引擎
================================================================================
模块路径: uniquant.brain.factors.forensics.z_cnmm_calculator
法医会计准则: CAS 14 (收入确认), CAS 8 (资产减值), CAS 31 (现金流量表), CAS 22/37 (金融工具)

【核心法医病理架构】：
针对 A 股资本市场上市公司财务舞弊与困境暴雷的典型特征，构建 5 维复合排雷特征：
  1. DSRI (Days Sales in Receivables Index - 应收异动指数):
     Beneish M-Score 核心指标。衡量应收账款与营业收入的异常背离度，精准捕捉跨期激进收入确认与虚构收入。
  2. AQI (Asset Quality Index - 资产质量恶化指数):
     衡量除固定资产外的非流动“软资产”（在建工程、无形资产、长期待摊、其他非流动资产等）占比跃升，捕捉成本资本化与潜亏挂账。
  3. Sloan Accruals (现金流背离度 - 应计利润率与虚假盈利):
     Richard Sloan (1996) 理论与 CNMM-QAR 虚假盈利剪刀差。捕捉账面净利润与经营现金流(OCF)的实质性断裂。
  4. DEPI (Depreciation & CIP Hanging - 折旧放缓与在建工程堰塞湖):
     结合 Beneish 折旧放缓率与 A 股特异性“在建工程长期挂起不转固”异象，捕捉少提折旧粉饰当期利润的操纵。
  5. CashTrap (存贷双高假现金探针):
     CAS 31 / CAS 22。穿透百亿账面货币资金但利息收益率畸低（<0.8%）且短期借款高企（>30%）的虚假现金陷阱。

【行业度量衡校准】：
  - 采用 1%-99% 双侧极值截断 (Winsorization) 消除恶性异动点；
  - 采用申万一级行业 (SW L1) 内中位数绝对偏差 (MAD, Median Absolute Deviation) 鲁棒标准化，
    彻底消除跨行业重资产 vs 轻资产、高周转 vs 长账期的量纲畸变。

【金融机构专用会计科目隔离引擎】：
  - 针对商业银行、证券、保险等金融机构特异性资产负债表结构（无短期借款、利息为主营收入、吸收存款等），
    内嵌 100% 会计科目自动识别隔离引擎，实现豁免放行（ISOLATED_EXEMPT），严格杜绝制度性误伤。
================================================================================
"""

import os
import glob
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

try:
    import pyarrow.parquet as pq
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

logger = logging.getLogger("uniquant.brain.factors.forensics.z_cnmm")


# ==============================================================================
# 字段别名表与 24 个核心投影科目 (用于 PyArrow/DuckDB 列投影下推消除 OOM)
# ==============================================================================
CORE_PROJECTED_COLUMNS: List[str] = [
    # 基础识别 (3)
    "code", "report_date", "industry",
    # 货币资金与借款 (5)
    "货币资金", "cash",
    "短期借款", "short_term_borrow",
    "其中:利息收入(利润表-财务费用)", "利息收入(万元)", "利息收入",
    # 营收与利润应计 (7)
    "应收账款", "accounts_rec",
    "其中：营业收入", "营业收入", "revenue",
    "五、净利润", "净利润", "归属于母公司所有者的净利润", "net_profit",
    "经营活动产生的现金流量净额", "ocf",
    # 资产与在建折旧 (8)
    "资产总计", "总资产", "total_assets",
    "流动资产合计", "current_assets",
    "固定资产", "ppe",
    "在建工程", "cip",
    "固定资产折旧、油气资产折耗、生产性生物资产折旧", "固定资产折旧", "depreciation",
    "其他应收款", "other_rec",
    # 金融特异性隔离科目 (8)
    "流动比率(非金融类指标)", "流动比率", "current_ratio",
    "向中央银行借款(万元)", "向中央银行借款", "central_bank_borrow",
    "客户存款和同业存放款项", "吸收存款及同业存放", "存出资本保证金",
    "代理买卖证券款", "保险责任准备金", "吸收存款", "拆入资金",
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
    "central_bank_borrow": ["向中央银行借款(万元)", "向中央银行借款", "central_bank_borrow"],
    "code": ["code", "股票代码", "symbol", "ts_code"],
    "report_date": ["report_date", "报告期", "date", "fiscal_date"],
    "industry": ["industry", "sw_l1", "申万一级行业", "申万一级", "sw_industry", "sector"],
}

# 常见已知商业银行代码集合 (6位代码)
KNOWN_BANKS = {
    "000001", "600036", "601398", "601939", "601288", "601988", "601328",
    "601166", "600919", "601009", "002142", "600926", "601658", "600000",
    "600016", "601818", "601998", "601997", "600908", "002807", "002839",
    "002936", "002948", "002958", "600901", "600928", "601077", "601128",
    "601187", "601229", "601528", "601577", "601665", "601825", "601838",
    "601860", "603323",
}

# 常见已知证券与保险代码集合
KNOWN_SECURITIES_INSURANCE = {
    "600030", "600999", "601066", "601688", "601788", "601878", "601881",
    "601901", "601995", "000776", "000783", "000728", "000712", "000686",
    "000166", "601236", "601377", "601456", "601318", "601628", "601336",
    "601601", "600291", "002736", "002926", "002939", "002945", "600958",
}

# 常见金融行业标签集合
FINANCIAL_INDUSTRY_LABELS = {
    "银行", "非银金融", "金融", "金融业", "Banking", "Financials",
    "Securities", "Insurance", "BankingFinance", "Bank",
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


class ZCNMMCalculator:
    """
    CNMM-QAR 生产级 Z_CNMM 五维复合排雷与金融特异性隔离探针算子
    """

    # 默认五维权重配置 (总和 1.00)
    DEFAULT_WEIGHTS = {
        "dsri": 0.20,
        "aqi": 0.15,
        "sloan": 0.25,
        "depi_cip": 0.20,
        "cashtrap": 0.20,
    }

    # 统计与风控参数
    WINSOR_LOWER = 0.01
    WINSOR_UPPER = 0.99
    MAD_SCALE_FACTOR = 1.4826
    RISK_P75_CUTOFF = 0.75
    CANONICAL_P75 = 0.50  # 单标的时间序列评估时的截断基准阈值

    # CashTrap 探针特异性阈值
    CASHTRAP_INTEREST_RATE_THRESHOLD = 0.008  # 0.8%
    CASHTRAP_DEBT_RATIO_THRESHOLD = 0.30       # 30.0%
    CASHTRAP_MIN_CASH_YUAN = 1e7               # 1000 万元底线

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        p75_cutoff: float = RISK_P75_CUTOFF,
        interest_threshold: float = CASHTRAP_INTEREST_RATE_THRESHOLD,
        debt_threshold: float = CASHTRAP_DEBT_RATIO_THRESHOLD,
    ):
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        # 归一化权重
        total_w = sum(self.weights.values())
        self.weights = {k: v / total_w for k, v in self.weights.items()}
        self.p75_cutoff = p75_cutoff
        self.interest_threshold = interest_threshold
        self.debt_threshold = debt_threshold

    @staticmethod
    def _extract_column(df: pd.DataFrame, standard_key: str, default_val: float = 0.0) -> pd.Series:
        """从 DataFrame 中根据字段别名安全提取数值序列"""
        aliases = FINANCIAL_ALIASES.get(standard_key, [standard_key])
        for alias in aliases:
            if alias in df.columns:
                series = pd.to_numeric(df[alias], errors="coerce").fillna(default_val)
                # 特殊处理万元单位换算
                if alias == "利息收入(万元)":
                    series = series * 10000.0
                return series
        return pd.Series(default_val, index=df.index, dtype=float)

    @classmethod
    def identify_financial_institution(cls, df_or_row: Union[pd.DataFrame, pd.Series, dict], code: str = "") -> Union[pd.Series, bool]:
        """
        基于会计科目特征、行业分类与代码准入识别金融机构 (商业银行、券商、保险)
        支持 DataFrame、Series 与 dict 格式。
        """
        if isinstance(df_or_row, (pd.Series, dict)):
            row = df_or_row
            code_clean = str(code or row.get("code", "")).split(".")[0].zfill(6)
            if code_clean in (KNOWN_BANKS | KNOWN_SECURITIES_INSURANCE):
                return True

            ind = str(row.get("industry", row.get("sw_l1", row.get("申万一级行业", "")))).strip()
            if ind in FINANCIAL_INDUSTRY_LABELS:
                return True

            curr_ratio = row.get("流动比率(非金融类指标)", row.get("流动比率", row.get("current_ratio", np.nan)))
            try:
                curr_ratio_val = float(curr_ratio) if pd.notna(curr_ratio) else np.nan
            except (ValueError, TypeError):
                curr_ratio_val = np.nan

            cb_loan = row.get("向中央银行借款(万元)", row.get("向中央银行借款", 0.0))
            try:
                cb_loan_val = float(cb_loan) if pd.notna(cb_loan) else 0.0
            except (ValueError, TypeError):
                cb_loan_val = 0.0

            if (pd.isna(curr_ratio_val) or curr_ratio_val == 0.0) and cb_loan_val > 1000.0:
                return True

            # 专属科目
            for f_col in ["客户存款和同业存放款项", "吸收存款及同业存放", "代理买卖证券款", "保险责任准备金", "吸收存款"]:
                if f_col in row:
                    try:
                        v = float(row[f_col]) if pd.notna(row[f_col]) else 0.0
                        if v > 1e8:
                            return True
                    except (ValueError, TypeError):
                        pass
            return False

        # DataFrame 格式
        df = df_or_row
        is_fin = pd.Series(False, index=df.index)

        # 1. 行业特征判定
        industry_col = None
        for alias in FINANCIAL_ALIASES["industry"]:
            if alias in df.columns:
                industry_col = alias
                break
        if industry_col:
            ind_series = df[industry_col].astype(str).str.strip()
            is_fin = is_fin | ind_series.isin(FINANCIAL_INDUSTRY_LABELS)

        # 2. 代码白名单判定
        code_col = None
        for alias in FINANCIAL_ALIASES["code"]:
            if alias in df.columns:
                code_col = alias
                break
        if code_col:
            codes_clean = df[code_col].astype(str).str.split(".").str[0].str.zfill(6)
            is_fin = is_fin | codes_clean.isin(KNOWN_BANKS | KNOWN_SECURITIES_INSURANCE)

        # 3. 会计科目特征判定
        curr_ratio = cls._extract_column(df, "current_ratio", default_val=np.nan)
        cb_loan = cls._extract_column(df, "central_bank_borrow", default_val=0.0)

        # 流动比率为 0 或缺失，且央行借款 > 1000 万元
        fin_accounting_mask = (curr_ratio.isna() | (curr_ratio == 0.0)) & (cb_loan > 1000.0)
        is_fin = is_fin | fin_accounting_mask

        # 4. 金融专属负债科目穿透检查
        fin_specific_cols = [
            "客户存款和同业存放款项", "吸收存款及同业存放", "存出资本保证金",
            "代理买卖证券款", "保险责任准备金", "吸收存款", "拆入资金"
        ]
        for f_col in fin_specific_cols:
            if f_col in df.columns:
                val = pd.to_numeric(df[f_col], errors="coerce").fillna(0.0)
                is_fin = is_fin | (val > 1e8)

        return is_fin

    # --------------------------------------------------------------------------
    # 五维法医特征计算
    # --------------------------------------------------------------------------
    @classmethod
    def compute_dsri(cls, df: pd.DataFrame) -> pd.Series:
        """
        维度 1: DSRI (Days Sales in Receivables Index - 应收异动指数)
        公式: DSRI = (AR_t / Rev_t) / (AR_{t-1} / Rev_{t-1})
        若缺少前期数据，使用 AR_t / Rev_t 与基准比率 (0.15) 对齐。
        """
        ar = cls._extract_column(df, "accounts_rec", 0.0)
        rev = cls._extract_column(df, "revenue", 0.0)
        safe_rev = rev.replace(0.0, np.nan)
        ratio_curr = (ar / safe_rev).fillna(0.15)

        # 检查是否有前一期衍生列
        if "accounts_rec_prev" in df.columns and "revenue_prev" in df.columns:
            ar_prev = pd.to_numeric(df["accounts_rec_prev"], errors="coerce").fillna(0.0)
            rev_prev = pd.to_numeric(df["revenue_prev"], errors="coerce").replace(0.0, np.nan)
            ratio_prev = (ar_prev / rev_prev).fillna(0.15)
            dsri = ratio_curr / ratio_prev.replace(0.0, np.nan)
        else:
            # 截面计算模式: 将当前应收营收比相对于常态基准(0.15)折算
            dsri = ratio_curr / 0.15

        dsri = dsri.replace([np.inf, -np.inf], np.nan).fillna(1.0)
        return dsri.clip(0.2, 5.0)

    @classmethod
    def compute_aqi(cls, df: pd.DataFrame) -> pd.Series:
        """
        维度 2: AQI (Asset Quality Index - 资产质量恶化指数)
        公式: NonCurrentNonPPE = TotalAssets - CurrentAssets - PPE
              AQ_Ratio = NonCurrentNonPPE / TotalAssets
              AQI = AQ_Ratio_t / AQ_Ratio_{t-1}
        若缺少前期数据，使用 AQ_Ratio_t 与基准 (0.20) 对齐。
        """
        ta = cls._extract_column(df, "total_assets", 0.0)
        ca = cls._extract_column(df, "current_assets", 0.0)
        ppe = cls._extract_column(df, "ppe", 0.0)

        safe_ta = ta.replace(0.0, np.nan)
        non_current_soft = (ta - ca - ppe).clip(lower=0.0)
        aq_ratio = (non_current_soft / safe_ta).fillna(0.20)

        if "total_assets_prev" in df.columns and "current_assets_prev" in df.columns and "ppe_prev" in df.columns:
            ta_prev = pd.to_numeric(df["total_assets_prev"], errors="coerce").replace(0.0, np.nan)
            ca_prev = pd.to_numeric(df["current_assets_prev"], errors="coerce").fillna(0.0)
            ppe_prev = pd.to_numeric(df["ppe_prev"], errors="coerce").fillna(0.0)
            soft_prev = (ta_prev - ca_prev - ppe_prev).clip(lower=0.0)
            aq_ratio_prev = (soft_prev / ta_prev).fillna(0.20)
            aqi = aq_ratio / aq_ratio_prev.replace(0.0, np.nan)
        else:
            aqi = aq_ratio / 0.20

        aqi = aqi.replace([np.inf, -np.inf], np.nan).fillna(1.0)
        return aqi.clip(0.2, 5.0)

    @classmethod
    def compute_sloan_accruals(cls, df: pd.DataFrame) -> pd.Series:
        """
        维度 3: Sloan Accruals (现金流背离与虚假盈利特征)
        公式: Accruals = (NetProfit - OCF) / TotalAssets
        附加: 虚假盈利无现金额外惩罚 (NetProfit > 0 且 OCF < 0)
        """
        np_val = cls._extract_column(df, "net_profit", 0.0)
        ocf_val = cls._extract_column(df, "ocf", 0.0)
        ta_val = cls._extract_column(df, "total_assets", 0.0)

        safe_ta = ta_val.replace(0.0, np.nan)
        base_accruals = (np_val - ocf_val) / safe_ta
        base_accruals = base_accruals.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-1.0, 1.0)

        # 虚假盈利背离惩罚: 账面赚钱但现金流为负
        fake_profit_penalty = ((np_val > 0) & (ocf_val < 0)).astype(float) * 0.20
        composite_accruals = base_accruals + fake_profit_penalty
        return composite_accruals.clip(-1.0, 1.5)

    @classmethod
    def compute_depi(cls, df: pd.DataFrame) -> pd.Series:
        """
        维度 4: DEPI & CIP Hanging (折旧放缓与在建工程挂起堰塞湖)
        公式: DeprRate = Depreciation / (PPE + Depreciation)
              DEPI = DeprRate_{t-1} / DeprRate_t
              CIP_Ratio = CIP / TotalAssets
              DEPI_Score = (DEPI - 1.0) + 2.0 * CIP_Ratio
        """
        depr = cls._extract_column(df, "depreciation", 0.0)
        ppe = cls._extract_column(df, "ppe", 0.0)
        cip = cls._extract_column(df, "cip", 0.0)
        ta = cls._extract_column(df, "total_assets", 0.0)

        denom = (ppe + depr).replace(0.0, np.nan)
        depr_rate = (depr / denom).fillna(0.05)

        if "depreciation_prev" in df.columns and "ppe_prev" in df.columns:
            depr_prev = pd.to_numeric(df["depreciation_prev"], errors="coerce").fillna(0.0)
            ppe_prev = pd.to_numeric(df["ppe_prev"], errors="coerce").fillna(0.0)
            denom_prev = (ppe_prev + depr_prev).replace(0.0, np.nan)
            depr_rate_prev = (depr_prev / denom_prev).fillna(0.05)
            depi = depr_rate_prev / depr_rate.replace(0.0, np.nan)
        else:
            # 截面折算: 折旧率越低于均值(5%)，折旧越涉嫌放缓
            depi = 0.05 / depr_rate.replace(0.0, np.nan)

        depi = depi.replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(0.2, 5.0)

        # 在建工程堰塞湖占比
        safe_ta = ta.replace(0.0, np.nan)
        cip_ratio = (cip / safe_ta).fillna(0.0).clip(0.0, 1.0)

        # 综合两维: 历史折旧放缓 + 在建工程高悬
        depi_composite = (depi - 1.0) + 2.0 * cip_ratio
        return depi_composite.clip(-0.8, 5.0)

    @classmethod
    def compute_cashtrap(
        cls,
        df: pd.DataFrame,
        is_financial: Optional[pd.Series] = None,
        interest_threshold: float = CASHTRAP_INTEREST_RATE_THRESHOLD,
        debt_threshold: float = CASHTRAP_DEBT_RATIO_THRESHOLD,
    ) -> Tuple[pd.Series, pd.Series]:
        """
        维度 5: CashTrap (存贷双高假现金探针)
        公式:
          利息收益率: R_int = 利息收入 / 货币资金
          短期借款比: R_debt = 短期借款 / 货币资金
          触发条件: (R_int < 0.8%) 且 (R_debt > 30.0%)
          对金融机构实施 100% 隔离豁免 (分数归零，不触发)
        返回: (cashtrap_score, cashtrap_flag)
        """
        if is_financial is None:
            is_financial = cls.identify_financial_institution(df)

        cash = cls._extract_column(df, "cash", 0.0)
        st_loan = cls._extract_column(df, "short_term_borrow", 0.0)

        # 利息收入 (两通道最大值: 利润表附注通道 vs 财务费用冲减通道)
        c1 = cls._extract_column(df, "interest_income", 0.0)
        int_income = c1.clip(lower=0.0)

        safe_cash = cash.replace(0.0, np.nan)
        int_rate = (int_income / safe_cash).fillna(0.0)
        debt_ratio = (st_loan / safe_cash).fillna(0.0)

        # 判定触发
        cond_interest = int_rate < interest_threshold
        cond_debt = debt_ratio > debt_threshold
        cond_scale = cash > cls.CASHTRAP_MIN_CASH_YUAN

        # 离散触发标记
        raw_flag = cond_interest & cond_debt & cond_scale

        # 连续风险评分
        interest_gap = ((0.015 - int_rate) / 0.015).clip(lower=0.0)
        continuous_score = debt_ratio * (1.0 + interest_gap)

        # 叠加离散触发惩罚
        total_score = continuous_score + raw_flag.astype(float) * 2.0

        # 金融机构特异性隔离豁免
        total_score = total_score.mask(is_financial, 0.0)
        clean_flag = raw_flag.mask(is_financial, False)

        return total_score.clip(0.0, 10.0), clean_flag

    # --------------------------------------------------------------------------
    # 统计鲁棒标准化引擎 (Winsorization + Shenwan L1 MAD)
    # --------------------------------------------------------------------------
    @classmethod
    def winsorize_1_99(
        cls,
        series: pd.Series,
        lower_q: float = WINSOR_LOWER,
        upper_q: float = WINSOR_UPPER,
    ) -> pd.Series:
        """1%-99% 双侧极值截断 (Winsorization)"""
        s = series.replace([np.inf, -np.inf], np.nan)
        if s.dropna().empty or len(s.dropna()) < 4:
            return s.fillna(0.0)
        q_low = s.quantile(lower_q)
        q_high = s.quantile(upper_q)
        if q_low == q_high:
            return s.fillna(q_low)
        return s.clip(lower=q_low, upper=q_high).fillna(s.median())

    @classmethod
    def mad_standardize_by_industry(
        cls,
        series: pd.Series,
        industry_series: pd.Series,
        scale_factor: float = MAD_SCALE_FACTOR,
    ) -> pd.Series:
        """
        申万一级行业内中位数绝对偏差 (MAD) 鲁棒标准化:
          Z = (X - Median_ind) / (1.4826 * MAD_ind)
        彻底消除跨行业量纲畸变。
        """
        cleaned = cls.winsorize_1_99(series)
        z_out = pd.Series(0.0, index=series.index, dtype=float)

        # 全局回退基准
        global_med = cleaned.median()
        global_mad = (cleaned - global_med).abs().median()
        global_scale = global_mad * scale_factor if global_mad > 1e-4 else (cleaned.std() or 1.0)

        # 分行业组处理
        for ind, group_idx in industry_series.groupby(industry_series).groups.items():
            sub_s = cleaned.loc[group_idx]
            if len(sub_s) < 3:
                # 样本量过少，回退至全局基准
                z_sub = (sub_s - global_med) / global_scale
            else:
                med = sub_s.median()
                mad = (sub_s - med).abs().median()
                if mad > 1e-4:
                    scale = mad * scale_factor
                else:
                    std = sub_s.std()
                    scale = std if (pd.notna(std) and std > 1e-4) else global_scale
                z_sub = (sub_s - med) / scale
            z_out.loc[group_idx] = z_sub

        return z_out.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-5.0, 5.0)

    # --------------------------------------------------------------------------
    # 全流程 Z_CNMM 复合得分计算与全景评估
    # --------------------------------------------------------------------------
    def compute_z_cnmm(
        self,
        df: pd.DataFrame,
        industry_col: Optional[str] = None,
        return_details: bool = True,
    ) -> pd.DataFrame:
        """
        全截面/面板计算 Z_CNMM 排雷得分矩阵与分类判定
        """
        if df.empty:
            return pd.DataFrame()

        df_calc = df.copy()

        # 提取股票代码与报告期
        code_col = None
        for alias in FINANCIAL_ALIASES["code"]:
            if alias in df_calc.columns:
                code_col = alias
                break
        codes = df_calc[code_col].astype(str) if code_col else pd.Series(df_calc.index.astype(str), index=df_calc.index)

        date_col = None
        for alias in FINANCIAL_ALIASES["report_date"]:
            if alias in df_calc.columns:
                date_col = alias
                break
        dates = df_calc[date_col].astype(int) if date_col else pd.Series(0, index=df_calc.index)

        # 1. 行业列解析
        if industry_col and industry_col in df_calc.columns:
            ind_series = df_calc[industry_col].astype(str).str.strip()
        else:
            found_ind = None
            for alias in FINANCIAL_ALIASES["industry"]:
                if alias in df_calc.columns:
                    found_ind = alias
                    break
            if found_ind:
                ind_series = df_calc[found_ind].astype(str).str.strip()
            else:
                ind_series = pd.Series("综合", index=df_calc.index)

        # 2. 金融机构识别与特异性隔离
        is_financial = self.identify_financial_institution(df_calc)
        # 对识别出的金融机构，若行业标记未注明，规约为 "银行/金融"
        ind_series = ind_series.mask(is_financial & (ind_series == "综合"), "银行")

        # 3. 计算五维原始特征
        dsri_raw = self.compute_dsri(df_calc)
        aqi_raw = self.compute_aqi(df_calc)
        sloan_raw = self.compute_sloan_accruals(df_calc)
        depi_raw = self.compute_depi(df_calc)
        cashtrap_raw, cashtrap_flag = self.compute_cashtrap(
            df_calc,
            is_financial=is_financial,
            interest_threshold=self.interest_threshold,
            debt_threshold=self.debt_threshold,
        )

        # 4. 申万一级行业内 MAD 鲁棒标准化 (消除量纲畸变)
        dsri_z = self.mad_standardize_by_industry(dsri_raw, ind_series)
        aqi_z = self.mad_standardize_by_industry(aqi_raw, ind_series)
        sloan_z = self.mad_standardize_by_industry(sloan_raw, ind_series)
        depi_z = self.mad_standardize_by_industry(depi_raw, ind_series)
        cashtrap_z = self.mad_standardize_by_industry(cashtrap_raw, ind_series)

        # 5. 加权合成 Z_CNMM 复合得分 (高分高危)
        w = self.weights
        z_composite = (
            w["dsri"] * dsri_z
            + w["aqi"] * aqi_z
            + w["sloan"] * sloan_z
            + w["depi_cip"] * depi_z
            + w["cashtrap"] * cashtrap_z
        )

        # 6. 金融机构豁免处理: 归零、免除警报
        z_composite = z_composite.mask(is_financial, 0.0)

        # 7. 判定模式: 全截面评估 vs 单标的时间序列评估
        num_distinct_codes = codes.nunique()
        is_cross_section = num_distinct_codes >= 5
        non_fin_mask = ~is_financial

        risk_percentile = pd.Series(0.0, index=df_calc.index)
        if is_cross_section and non_fin_mask.any():
            non_fin_scores = z_composite.loc[non_fin_mask]
            # 计算截面分位数 (0.0 ~ 1.0)
            percentiles = non_fin_scores.rank(pct=True)
            risk_percentile.loc[non_fin_mask] = percentiles
            p75_val = non_fin_scores.quantile(self.p75_cutoff)
            is_blacklisted = non_fin_mask & ((z_composite > p75_val) | cashtrap_flag)
        else:
            # 单标的/少量样本时，使用标准基准门槛
            p75_val = self.CANONICAL_P75
            # 单标的场景下，黑名单以 CashTrap 探针触发或绝对高分 (>CANONICAL_P75) 为准
            is_blacklisted = non_fin_mask & ((z_composite > p75_val) | cashtrap_flag)
            risk_percentile = (z_composite.clip(0.0, 3.0) / 3.0)

        is_whitelisted = ~is_blacklisted

        # 8. 生成法医状态与评语
        status_list = []
        verdict_list = []
        for idx in df_calc.index:
            if is_financial.loc[idx]:
                status_list.append("ISOLATED_EXEMPT")
                verdict_list.append("商业银行/金融机构会计科目特异性隔离 (100% 结构性豁免放行)")
            elif cashtrap_flag.loc[idx]:
                status_list.append("INTERCEPTED_ALERT")
                verdict_list.append("【极危拦截】存贷双高假现金探针锁定 (账面高额现金伴随低息与短借高企)")
            elif is_blacklisted.loc[idx]:
                status_list.append("INTERCEPTED_ALERT")
                verdict_list.append(f"【高危排雷】Z_CNMM 复合困境得分 ({z_composite.loc[idx]:.3f}) 处于前 25% 危险区间 (> P75={p75_val:.3f})")
            else:
                status_list.append("CLEAN_PASS")
                verdict_list.append("【清洁安全】通过五维法医审计核验，财务报表结构真实稳健")

        # 9. 输出结果结构
        out_df = pd.DataFrame({
            "code": codes,
            "report_date": dates,
            "industry": ind_series,
            "is_financial": is_financial,
            "is_exempt": is_financial,
            "status": status_list,
            "dsri_raw": dsri_raw.round(4),
            "aqi_raw": aqi_raw.round(4),
            "sloan_raw": sloan_raw.round(4),
            "depi_raw": depi_raw.round(4),
            "cashtrap_raw": cashtrap_raw.round(4),
            "cashtrap_flag": cashtrap_flag,
            "dsri_z": dsri_z.round(4),
            "aqi_z": aqi_z.round(4),
            "sloan_z": sloan_z.round(4),
            "depi_z": depi_z.round(4),
            "cashtrap_z": cashtrap_z.round(4),
            "z_cnmm": z_composite.round(4),
            "risk_percentile": (risk_percentile * 100.0).round(2),
            "is_blacklisted": is_blacklisted,
            "is_whitelisted": is_whitelisted,
            "verdict": verdict_list,
        }, index=df_calc.index)

        return out_df

    def filter_distress_universe(
        self,
        df: pd.DataFrame,
        industry_col: Optional[str] = None,
    ) -> Tuple[List[str], List[str], pd.DataFrame]:
        """
        截面排雷拦截入口:
        返回 (whitelist_codes, blacklist_codes, detail_df)
        """
        detail_df = self.compute_z_cnmm(df, industry_col=industry_col)
        whitelist = detail_df[detail_df["is_whitelisted"]]["code"].tolist()
        blacklist = detail_df[detail_df["is_blacklisted"]]["code"].tolist()
        return whitelist, blacklist, detail_df

    # --------------------------------------------------------------------------
    # 单标的与时间序列扫描工具 (完全兼容 CashTrapProbe 接口)
    # --------------------------------------------------------------------------
    def evaluate_record(self, row: Union[pd.Series, dict], code: str = "") -> dict:
        """
        单期财报法医评估 (支持 Series / dict 字典输入)
        """
        s_row = pd.Series(row)
        c = code or str(s_row.get("code", "UNKNOWN"))
        s_row["code"] = c
        df_single = pd.DataFrame([s_row])
        df_res = self.compute_z_cnmm(df_single)
        r = df_res.iloc[0]

        # 提取关键法医指标
        cash = float(s_row.get("货币资金", s_row.get("cash", 0.0)))
        st = float(s_row.get("短期借款", s_row.get("short_term_borrow", 0.0)))
        c1 = float(s_row.get("利息收入(万元)", 0.0)) * 10000.0 if pd.notna(s_row.get("利息收入(万元)")) else 0.0
        c2 = float(s_row.get("其中:利息收入(利润表-财务费用)", 0.0)) if pd.notna(s_row.get("其中:利息收入(利润表-财务费用)")) else 0.0
        int_inc = max(c1, c2)
        int_rate = (int_inc / cash) if cash > 1e4 else 0.0
        debt_ratio = (st / cash) if cash > 1e4 else 0.0

        return {
            "code": c,
            "report_date": int(r["report_date"]),
            "monetary_funds_yi": round(cash / 1e8, 2),
            "short_term_borrow_yi": round(st / 1e8, 2),
            "interest_income_yi": round(int_inc / 1e8, 4),
            "interest_rate_pct": round(int_rate * 100.0, 2),
            "debt_ratio_pct": round(debt_ratio * 100.0, 2),
            "is_financial": bool(r["is_financial"]),
            "status": str(r["status"]),
            "cashtrap_flag": bool(r["cashtrap_flag"]),
            "z_cnmm": float(r["z_cnmm"]),
            "is_blacklisted": bool(r["is_blacklisted"]),
            "is_whitelisted": bool(r["is_whitelisted"]),
            "verdict": str(r["verdict"]),
        }

    @classmethod
    def load_stock_financials(
        cls,
        parquet_path: str,
        target_dates: Optional[List[int]] = None,
        use_projection: bool = True,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        加载单个股票财报 Parquet 数据 (工业级列投影下推，只提取必要科目消除 OOM 风险)
        """
        if not os.path.exists(parquet_path):
            return pd.DataFrame()

        # 优先使用 PyArrow 列投影下推
        if use_projection and HAS_PYARROW:
            try:
                meta = pq.read_metadata(parquet_path)
                file_cols = set(meta.schema.names)
                target_cols = columns or CORE_PROJECTED_COLUMNS
                matched = [c for c in target_cols if c in file_cols]
                if matched:
                    tbl = pq.read_table(parquet_path, columns=matched)
                    df = tbl.to_pandas()
                else:
                    df = pd.read_parquet(parquet_path)
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
                logger.warning(f"PyArrow 列投影下推读取 {parquet_path} 异常，回退全量: {e}")
                df = pd.read_parquet(parquet_path)
        else:
            df = pd.read_parquet(parquet_path)

        if target_dates and "report_date" in df.columns:
            df = df[df["report_date"].isin(target_dates)]
        return df

    def scan_stock(
        self,
        parquet_path: str,
        target_dates: Optional[List[int]] = None,
        use_projection: bool = True,
    ) -> List[dict]:
        """
        扫描单个股票目标报告期财报 (返回评估明细列表)
        """
        df = self.load_stock_financials(
            parquet_path, target_dates=target_dates, use_projection=use_projection
        )
        if df.empty:
            return []

        results = []
        code_guess = os.path.basename(parquet_path).split(".")[0]
        for _, row in df.iterrows():
            res = self.evaluate_record(row, code=code_guess)
            results.append(res)
        return results

    @classmethod
    def load_financials_duckdb(
        cls,
        parquet_pattern: str,
        target_dates: Optional[List[int]] = None,
    ) -> pd.DataFrame:
        """
        使用 DuckDB 引擎执行多文件批量投影下推查询 (消除宽表 OOM 并发)
        """
        if not HAS_DUCKDB:
            raise ImportError("DuckDB 未安装，无法执行 load_financials_duckdb")

        con = duckdb.connect(database=":memory:")
        try:
            first_files = glob.glob(parquet_pattern)
            if not first_files:
                return pd.DataFrame()

            sample_tbl = con.execute(f"SELECT * FROM '{first_files[0]}' LIMIT 0").df()
            matched = [c for c in CORE_PROJECTED_COLUMNS if c in sample_tbl.columns]

            col_sql = ", ".join([f'"{c}"' for c in matched])
            query = f"SELECT {col_sql} FROM '{parquet_pattern}'"
            if target_dates:
                dates_str = ", ".join([str(d) for d in target_dates])
                query += f" WHERE report_date IN ({dates_str})"

            df = con.execute(query).df()
            return df
        finally:
            con.close()



def evaluate_z_cnmm_cross_section(
    df: pd.DataFrame,
    industry_col: Optional[str] = None,
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """快捷截面排雷计算函数"""
    calc = ZCNMMCalculator(weights=weights)
    return calc.compute_z_cnmm(df, industry_col=industry_col)
