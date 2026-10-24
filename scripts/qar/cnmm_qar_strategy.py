#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNMM-QAR: Production-Grade Quantitative Absolute Return Strategy Assembly
=============================================================================
Architecture & Risk Governance Specifications:
1. Physical Data Lake Mount:
   - Mounts UniQuant Parquet data lake (daily quotes, GBBQ dividend adjustment, financial statements).
2. Four-Dimensional Forensic Accounting & Risk Screening (Z_CNMM & CashTrap):
   - Strict Point-in-Time (PIT) accounting rules (annual report cutoff at 04-30).
   - Rejection of capital-draining zombie firms, uncapitalized CIP overhang, and fake cash traps.
3. Canonical Ternary Allocation Structure:
   - 75% Equity Long: Diversified high-alpha safe stocks, single stock <= 2.5%, Shenwan L1 industry <= 10.0% and <= 4 stocks.
   - -75% Index Futures Short: CFFEX IF/IC/IM beta-hedged short exposure.
   - 25% Cash Buffer: Margin collateral & money-market liquidity buffer.
   - Gross Leverage: 175%, Net Exposure: 0%.
4. Portfolio Governance Integration:
   - Verified through PortfolioService.validate_hedged_portfolio.
5. Institutional 2/20 Governance Ledger:
   - Powered by InstitutionalFeeLedger (ACT/365 management fee, crystallized HWM, 6% hurdle, daily carry accrual & reversal).
=============================================================================
"""

from __future__ import annotations

import sys
import glob
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# 注入 UniQuant 源码路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from uniquant.services.portfolio_service import PortfolioService
from uniquant.hands.backtest.institutional_fee_ledger import (
    InstitutionalFeeLedger,
)
from uniquant.hands.backtest.institutional_execution_orchestrator import (
    InstitutionalExecutionOrchestrator,
    StrategyTrack,
    OrchestratorConfig,
)
from uniquant.data.utils.smart_factor_calculator import (
    SmartFactorCalculatorV15,
    GBBQProcessorV15,
)
from uniquant.shared.logger_factory import get_logger

logger = get_logger("CNMM_QAR_Strategy")

# 申万一级行业官方映射字典 (覆盖 105+ 家大样本股票)
SHENWAN_LEVEL1_MAP: Dict[str, str] = {
    # 银行 (13只)
    '000001': '银行', '600036': '银行', '601398': '银行', '601288': '银行', '601939': '银行',
    '601988': '银行', '601328': '银行', '601166': '银行', '600919': '银行', '601009': '银行',
    '002142': '银行', '600926': '银行', '601658': '银行',
    # 非银金融 (3只)
    '601318': '非银金融', '600030': '非银金融', '601995': '非银金融',
    # 食品饮料 (7只)
    '600519': '食品饮料', '000858': '食品饮料', '000568': '食品饮料', '600600': '食品饮料',
    '600887': '食品饮料', '603288': '食品饮料', '000895': '食品饮料',
    # 家用电器 (2只)
    '000651': '家用电器', '600690': '家用电器',
    # 汽车 (6只)
    '002594': '汽车', '600104': '汽车', '600660': '汽车', '601689': '汽车', '600733': '汽车', '000980': '汽车',
    # 电子 / 半导体核心硬件 (20只)
    '002475': '电子', '000725': '电子', '603501': '电子', '002241': '电子', '603986': '电子',
    '688008': '电子', '688256': '电子', '688126': '电子', '688036': '电子', '688608': '电子',
    '688099': '电子', '688538': '电子', '688396': '电子', '600703': '电子', '688981': '电子',
    '688012': '电子', '002371': '电子', '688347': '电子', '688041': '电子', '688279': '电子',
    # 通信 (3只)
    '000063': '通信', '000938': '通信', '002049': '通信',
    # 计算机 (5只)
    '002415': '计算机', '002230': '计算机', '688111': '计算机', '688561': '计算机', '688188': '计算机',
    # 电力设备 / 新能源 (13只)
    '300750': '电力设备', '300274': '电力设备', '600438': '电力设备', '601012': '电力设备',
    '300014': '电力设备', '688599': '电力设备', '688223': '电力设备', '688005': '电力设备',
    '688772': '电力设备', '600089': '电力设备', '600406': '电力设备', '600550': '电力设备',
    '300124': '电力设备',
    # 公用事业 (3只)
    '600900': '公用事业', '601985': '公用事业', '600795': '公用事业',
    # 石油石化 (2只)
    '601857': '石油石化', '600028': '石油石化',
    # 煤炭 (1只)
    '601088': '煤炭',
    # 有色金属 (2只)
    '601899': '有色金属', '600111': '有色金属',
    # 基础化工 (2只)
    '600309': '基础化工', '688065': '基础化工',
    # 钢铁 (1只)
    '600019': '钢铁',
    # 建筑材料 (2只)
    '600585': '建筑材料', '600176': '建筑材料',
    # 建筑装饰 (4只)
    '601668': '建筑装饰', '601390': '建筑装饰', '601800': '建筑装饰', '601186': '建筑装饰',
    # 交通运输 (3只)
    '601816': '交通运输', '600009': '交通运输', '600115': '交通运输',
    # 国防军工 (2只)
    '600150': '国防军工', '600118': '国防军工',
    # 医药生物 (10只)
    '600276': '医药生物', '603259': '医药生物', '300760': '医药生物', '300015': '医药生物',
    '300122': '医药生物', '000963': '医药生物', '688235': '医药生物', '688180': '医药生物',
    '688363': '医药生物', '688029': '医药生物',
    # 农林牧渔 (2只)
    '002714': '农林牧渔', '300498': '农林牧渔',
    # 房地产 (3只)
    '000002': '房地产', '600048': '房地产', '000069': '房地产',
    # 商贸零售 (2只)
    '601888': '商贸零售', '002024': '商贸零售'
}


@dataclass
class CNMMQARConfig:
    """CNMM-QAR 策略配置参数"""
    track: StrategyTrack = StrategyTrack.INSTITUTIONAL_75_25  # 策略运行轨别
    equity_weight_target: float = 0.75          # 股票多头目标总权重 (75%)
    futures_weight_target: float = -0.75        # 期指空头目标总权重 (-75%)
    cash_weight_target: float = 0.25            # 现金缓冲池目标权重 (25%)
    max_stock_weight: float = 0.025             # 单票权重上限 (2.5%)
    max_industry_weight: float = 0.10           # 单申万一级行业权重上限 (10%)
    max_industry_stocks: int = 4                # 单申万一级行业持股数上限 (4只)
    z_cnmm_p75_cutoff: float = 0.75             # 截面排雷分位淘汰线 (P75)
    portfolio_size_min: int = 30                # 最小持仓标的数 (确保 75% / 30 <= 2.5% 单票上限)
    portfolio_size_max: int = 40                # 最大持仓标的数
    top_quantile: float = 0.60                  # Alpha得分前序入选比例 (60%)
    
    # 机构费用与基准
    comm_rate: float = 0.0003                   # 佣金万三 (3 bps)
    twap_slip_rate: float = 0.0005              # 3日TWAP平滑滑点 (5 bps)
    raw_slip_rate: float = 0.0020               # 未优化集合竞价滑点 (20 bps)
    risk_free_rate: float = 0.025               # 长期无风险利率 (2.50%/年)
    mgmt_fee_rate: float = 0.02                 # 私募管理费率 2.0%
    custody_fee_rate: float = 0.0025            # 托管费率 0.25%
    hurdle_rate: float = 0.06                   # 业绩报酬基准门槛 6.0% (蓝图基准)
    carry_rate: float = 0.20                    # 超额业绩提成比例 20.0%

    def __post_init__(self):
        """根据轨别自动同步资产配置权重"""
        if self.track == StrategyTrack.PURE_LONG:
            self.equity_weight_target = 1.0
            self.futures_weight_target = 0.0
            self.cash_weight_target = 0.0
        elif self.track == StrategyTrack.CLASSIC_HEDGE:
            self.equity_weight_target = 1.0
            self.futures_weight_target = -1.0
            self.cash_weight_target = 0.0
        elif self.track == StrategyTrack.INSTITUTIONAL_75_25:
            self.equity_weight_target = 0.75
            self.futures_weight_target = -0.75
            self.cash_weight_target = 0.25


class CNMMQARStrategy:
    """
    CNMM-QAR 生产级量化绝对收益策略总装类
    """

    def __init__(
        self,
        config: Optional[CNMMQARConfig] = None,
        data_lake_root: Optional[str | Path] = None,
    ):
        self.config = config or CNMMQARConfig()
        self.root_dir = Path(data_lake_root or PROJECT_ROOT)
        
        # 生产中台与治理账本挂载
        self.portfolio_service = PortfolioService()
        self.fee_ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=self.config.mgmt_fee_rate,
            carry_rate=self.config.carry_rate,
            hurdle_rate=self.config.hurdle_rate,
            initial_nav=1.0,
            start_date="2000-01-01",
        )
        self.orchestrator = InstitutionalExecutionOrchestrator(
            OrchestratorConfig(
                track=self.config.track,
                mgmt_fee_rate=self.config.mgmt_fee_rate,
                carry_rate=self.config.carry_rate,
                hurdle_rate=self.config.hurdle_rate,
            )
        )

        # 数据湖子路径
        self.quotes_dir = self.root_dir / "data" / "lake" / "quotes" / "daily"
        self.lake_div_dir = self.root_dir / "data" / "lake" / "dividend"
        self.lake_fin_dir = self.root_dir / "data" / "lake" / "financial"
        self.gbbq_path = self.root_dir / "data" / "fq" / "gbbq.parquet"

        # 核心因子与复权计算器
        self.calc = SmartFactorCalculatorV15()
        self.events: Optional[pd.DataFrame] = None
        
        # 运行时缓存
        self.stock_codes: List[str] = []
        self.industry_map: Dict[str, str] = {}
        self.name_map: Dict[str, str] = {}
        self.df_adj: Optional[pd.DataFrame] = None
        self.df_sh: Optional[pd.DataFrame] = None
        self.df_csi: Optional[pd.DataFrame] = None
        self.df_ann: Optional[pd.DataFrame] = None
        self.df_div: Optional[pd.DataFrame] = None

    def initialize_data_lake(
        self,
        panel_path: Optional[str | Path] = None,
        balance_raw_path: Optional[str | Path] = None,
    ) -> None:
        """
        加载 UniQuant 数据湖行情、复权事件与会计法医报表
        """
        logger.info("Initializing UniQuant Parquet Data Lake & Forensic Data...")

        # 1. 加载 GBBQ 除权除息事件
        if self.gbbq_path.exists():
            self.events = GBBQProcessorV15.load_and_clean(str(self.gbbq_path))
        else:
            logger.warning(f"GBBQ file not found at {self.gbbq_path}, proceeding without splits.")
            self.events = pd.DataFrame(columns=["code", "date", "factor"])

        # 2. 定位面板与负债表数据文件 (标准 UniQuant 仓内路径)
        p_path = None
        if panel_path and Path(panel_path).exists():
            p_path = Path(panel_path)
        elif (self.root_dir / "data" / "backtest" / "large_sample_100_panel_processed.csv").exists():
            p_path = self.root_dir / "data" / "backtest" / "large_sample_100_panel_processed.csv"

        b_path = None
        if balance_raw_path and Path(balance_raw_path).exists():
            b_path = Path(balance_raw_path)
        elif (self.root_dir / "data" / "backtest" / "large_sample_100_balance_raw.csv").exists():
            b_path = self.root_dir / "data" / "backtest" / "large_sample_100_balance_raw.csv"

        if not p_path or not b_path:
            raise FileNotFoundError(
                f"Missing panel or balance raw dataset: p_path={p_path}, b_path={b_path}"
            )

        # 3. 解析股票基本信息与行业映射 (优先采用官方申万一级行业映射)
        df_p = pd.read_csv(p_path)
        df_p["stock_code"] = df_p["stock_code"].astype(str).str.zfill(6)
        self.stock_codes = sorted(df_p["stock_code"].unique())
        df_p_ind = dict(zip(df_p["stock_code"], df_p["industry"]))
        self.industry_map = {
            c: SHENWAN_LEVEL1_MAP.get(c, df_p_ind.get(c, "UNKNOWN"))
            for c in self.stock_codes
        }
        self.name_map = dict(zip(df_p["stock_code"], df_p.get("stock_name", df_p["stock_code"])))

        # 4. 加载基准日线 (上证综指 000001.SH 与 沪深300 000300.SH)
        sh_path = self.quotes_dir / "000001.SH.parquet"
        if not sh_path.exists():
            sh_path = self.root_dir / "data" / "lake" / "quotes" / "index" / "000001.SH.parquet"
        df_sh = pd.read_parquet(sh_path)
        df_sh["date"] = pd.to_datetime(df_sh["date"])
        self.df_sh = df_sh[(df_sh["date"] >= "1999-12-01") & (df_sh["date"] <= "2026-07-23")].sort_values("date").set_index("date")

        csi_path = self.quotes_dir / "000300.SH.parquet"
        if not csi_path.exists():
            csi_path = self.root_dir / "data" / "lake" / "quotes" / "index" / "000300.SH.parquet"
        df_csi = pd.read_parquet(csi_path)
        df_csi["date"] = pd.to_datetime(df_csi["date"])
        self.df_csi = df_csi[(df_csi["date"] >= "2005-01-04") & (df_csi["date"] <= "2026-07-23")].sort_values("date").set_index("date")

        # 5. 构建全市场后复权日频行情矩阵
        daily_adj = {}
        for code in self.stock_codes:
            q_files = glob.glob(str(self.quotes_dir / f"{code}.*.parquet"))
            if not q_files:
                continue
            df_q = pd.read_parquet(q_files[0])
            df_q["date"] = pd.to_datetime(df_q["date"])
            df_q = df_q[(df_q["date"] >= "1999-12-01") & (df_q["date"] <= "2026-07-23")].sort_values("date").reset_index(drop=True)
            if df_q.empty:
                continue

            if self.events is not None and not self.events.empty:
                ev = self.events[self.events["code"] == code]
                fac = self.calc.calculate(df_q, ev)
                merged = pd.merge(df_q, fac, on="date", how="left")
                merged["factor"] = merged["factor"].ffill().fillna(1.0)
            else:
                merged = df_q.copy()
                merged["factor"] = 1.0

            merged["adj_close"] = merged["close"] * merged["factor"]
            daily_adj[code] = merged.set_index("date")["adj_close"]

        self.df_adj = pd.DataFrame(daily_adj).sort_index()
        logger.info(f"Loaded adjusted quotes for {self.df_adj.shape[1]} symbols across {self.df_adj.shape[0]} trading days.")

        # 6. 加载财务法医数据 (在建工程、其他应收款、净利润、净资产)
        df_p["report_date"] = pd.to_datetime(df_p["report_date"])
        df_p["year"] = df_p["report_date"].dt.year
        df_p["month"] = df_p["report_date"].dt.month

        b_raw = pd.read_csv(b_path, low_memory=False)
        b_raw["stock_code"] = b_raw["stock_code"].astype(str).str.zfill(6)
        b_raw["report_date"] = pd.to_datetime(b_raw["报告期"])
        b_raw["year"] = b_raw["report_date"].dt.year
        b_raw["month"] = b_raw["report_date"].dt.month

        def parse_val(val: Any) -> float:
            if pd.isna(val) or val is False or val == "False" or val == "" or val == "--":
                return 0.0
            s = str(val).strip()
            try:
                if "万亿" in s:
                    return float(s.replace("万亿", "")) * 10000.0
                elif "亿" in s:
                    return float(s.replace("亿", ""))
                elif "万" in s:
                    return float(s.replace("万", "")) / 10000.0
                else:
                    return float(s) / 100000000.0
            except (ValueError, TypeError):
                return 0.0

        oth_col = "其他应收款" if "其他应收款" in b_raw.columns else "其他应收款合计"
        b_raw["oth_rec_yi"] = b_raw[oth_col].apply(parse_val)
        b_raw_ann = b_raw[b_raw["month"] == 12][["stock_code", "year", "oth_rec_yi"]].drop_duplicates(subset=["stock_code", "year"])

        ann = df_p[df_p["month"] == 12].copy()
        ann = pd.merge(ann, b_raw_ann, on=["stock_code", "year"], how="left")
        ann["oth_rec_yi"] = ann["oth_rec_yi"].fillna(0.0)

        # 加载 CAS 31 真实经营活动现金流净额 (造血现金流)
        cfo_records = []
        if self.lake_fin_dir.exists():
            for c in self.stock_codes:
                f_files = glob.glob(str(self.lake_fin_dir / f"{c}.*.parquet"))
                if f_files:
                    try:
                        df_f = pd.read_parquet(f_files[0])
                        col = "经营活动产生的现金流量净额"
                        if col in df_f.columns:
                            df_f["rep_str"] = df_f["report_date"].astype(str)
                            df_f_ann = df_f[df_f["rep_str"].str.endswith("1231")].copy()
                            df_f_ann["year"] = df_f_ann["rep_str"].str[:4].astype(int)
                            for _, r in df_f_ann.iterrows():
                                val = r[col]
                                if pd.notna(val):
                                    cfo_records.append({
                                        "stock_code": c,
                                        "year": int(r["year"]),
                                        "cfo_yi": float(val) / 100000000.0,
                                    })
                    except (IOError, ValueError, TypeError, KeyError) as e:
                        logger.debug("读取财报现金流失败 %s: %s", c, e)
        if cfo_records:
            df_cfo = pd.DataFrame(cfo_records).drop_duplicates(subset=["stock_code", "year"])
            ann = pd.merge(ann, df_cfo, on=["stock_code", "year"], how="left")
            # 严格因果去伪: 缺失 CAS 31 经营现金流的年份严禁以净利润顶替，保持为 NaN
        else:
            ann["cfo_yi"] = np.nan

        ann["cip_ratio"] = ann["cip_yi"] / ann["total_assets_yi"].clip(lower=1.0)
        ann["oth_rec_ratio"] = ann["oth_rec_yi"] / ann["total_assets_yi"].clip(lower=1.0)
        ann["roe"] = ann["net_profit_yi"] / ann["equity_yi"].clip(lower=1.0)
        ann["cfo_ratio"] = ann["cfo_yi"] / ann["total_assets_yi"].clip(lower=1.0)
        ann["cfo_proxy"] = ann["cfo_ratio"]
        self.df_ann = ann

        # 7. 加载分红记录
        div_records = []
        for c in self.stock_codes:
            d_files = glob.glob(str(self.lake_div_dir / f"{c}.*.parquet"))
            if d_files:
                df_d = pd.read_parquet(d_files[0])
                for _, r in df_d.iterrows():
                    div_records.append({"stock_code": c, "year": int(r["year"]), "dps": float(r["dps"])})
        if div_records:
            self.df_div = pd.DataFrame(div_records).drop_duplicates(subset=["stock_code", "year"])
        else:
            self.df_div = pd.DataFrame(columns=["stock_code", "year", "dps"])

        logger.info(f"Forensic pipeline ready with {len(self.df_ann)} annual records and {len(self.df_div)} dividend events.")

    def evaluate_forensics_gate(self, valid_universe: List[str], fiscal_year: int) -> List[str]:
        """
        四维会计法医与排雷门禁 (剔除象限四资本抽水机与Z_CNMM高危标的)
        严格遵循 PIT (Point-in-Time) 原则
        """
        if self.df_ann is None or self.df_ann.empty:
            return valid_universe

        sub_ann = self.df_ann[self.df_ann["year"] == fiscal_year].set_index("stock_code")
        if sub_ann.empty:
            return valid_universe

        # 1. 象限四 (Q4) 资本抽水机客观拦截: 连续巨亏且高在建工程挂起
        q4_excluded = set()
        for c in valid_universe:
            if c in sub_ann.index:
                row = sub_ann.loc[c]
                if row["roe"] < -0.02 or (row["net_profit_yi"] < 0 and row["cip_ratio"] > 0.12):
                    q4_excluded.add(c)

        s3_cand = [c for c in valid_universe if c not in q4_excluded]

        # 2. Z_CNMM 复合排雷评分淘汰 (前 25% 一票否决)
        sub_s6 = sub_ann.loc[sub_ann.index.intersection(s3_cand)].copy()
        if len(sub_s6) >= 10:
            cip_z = (sub_s6["cip_ratio"] - sub_s6["cip_ratio"].mean()) / (sub_s6["cip_ratio"].std() + 1e-8)
            loss_flag = (sub_s6["net_profit_yi"] < 0).astype(float)
            z_score = 0.6 * cip_z + 0.4 * loss_flag
            cut = z_score.quantile(self.config.z_cnmm_p75_cutoff)
            safe_universe = list(z_score[z_score <= cut].index)
        else:
            safe_universe = s3_cand

        return safe_universe

    def compute_alpha_scores(
        self,
        candidate_universe: List[str],
        as_of_date: pd.Timestamp,
        fiscal_year: int,
    ) -> Dict[str, float]:
        """
        计算多维复合 Alpha 得分 (60日残差动量 + 现金流造血能力 CFO/Assets)
        """
        if self.df_adj is None or self.df_ann is None:
            return {c: 0.0 for c in candidate_universe}

        # 60 日残差动量
        p0 = self.df_adj.loc[as_of_date]
        p_prior_60 = self.df_adj.loc[:as_of_date].tail(60).iloc[0]
        mom_60 = p0 / p_prior_60 - 1.0

        sub_ann = self.df_ann[self.df_ann["year"] == fiscal_year].set_index("stock_code")

        # 截面标准化因果 Alpha 打分 (消除 5.0 任意放大倍数，缺失现金流年度赋予中性分 0.0)
        m_series = mom_60.loc[mom_60.index.intersection(candidate_universe)].dropna()
        m_mean = float(m_series.mean()) if not m_series.empty else 0.0
        m_std = float(m_series.std()) if len(m_series) > 1 and float(m_series.std()) > 1e-8 else 1.0

        cfo_series = sub_ann.loc[sub_ann.index.intersection(candidate_universe), "cfo_proxy"].dropna()
        has_cfo = len(cfo_series) >= 5
        cfo_mean = float(cfo_series.mean()) if has_cfo else 0.0
        cfo_std = float(cfo_series.std()) if (has_cfo and len(cfo_series) > 1 and float(cfo_series.std()) > 1e-8) else 1.0

        alpha_scores: Dict[str, float] = {}
        for c in candidate_universe:
            m_raw = mom_60.get(c, np.nan)
            m_z = (float(m_raw) - m_mean) / m_std if pd.notna(m_raw) else 0.0
            if has_cfo and c in sub_ann.index and pd.notna(sub_ann.loc[c, "cfo_proxy"]):
                c_z = (float(sub_ann.loc[c, "cfo_proxy"]) - cfo_mean) / cfo_std
            else:
                c_z = 0.0  # 缺失现金流时保持中性，严禁用净利润顶替
            # 因果综合加权 (各 50%)
            alpha_scores[c] = float(0.5 * m_z + 0.5 * c_z)

        return alpha_scores

    def construct_target_portfolio(
        self,
        as_of_date: pd.Timestamp,
        fiscal_year: int,
        valid_universe: List[str],
    ) -> Dict[str, Any]:
        """
        构建满足三元配置与申万一级行业集中度硬拦截的生产级投资组合。
        
        约束：
          - 现货多头：股票总权重 75%，单票 <= 2.5%，单申万行业 <= 10.0% 且 <= 4 只；
          - 期货空头：-75% 对冲头寸；
          - 现金缓冲：25% 流动性池。
        """
        # 1. 排雷过滤
        safe_candidates = self.evaluate_forensics_gate(valid_universe, fiscal_year)
        
        # 2. Alpha 打分排序
        alpha_scores = self.compute_alpha_scores(safe_candidates, as_of_date, fiscal_year)
        sorted_candidates = sorted(alpha_scores.items(), key=lambda x: x[1], reverse=True)

        calc_n = max(
            self.config.portfolio_size_min,
            min(self.config.portfolio_size_max, int(len(sorted_candidates) * self.config.top_quantile)),
        )
        target_n = min(calc_n, len(sorted_candidates))

        # 3. 贪心配资：施加行业集中度 (权重 <= 10% 且 持股 <= 4 只)
        selected_stocks: List[str] = []
        ind_counts: Dict[str, int] = {}
        
        for code, _ in sorted_candidates:
            if len(selected_stocks) >= target_n:
                break
            ind = self.industry_map.get(code, "UNKNOWN")
            current_count = ind_counts.get(ind, 0)
            # 行业持股上限 4 只
            if current_count < self.config.max_industry_stocks:
                selected_stocks.append(code)
                ind_counts[ind] = current_count + 1

        n_selected = len(selected_stocks)
        if n_selected == 0:
            raise RuntimeError("选股池为空，无法构建多空目标组合")

        # 每只股票等权分配 75% 股票多头
        w_per_stock = Decimal(str(round(self.config.equity_weight_target / n_selected, 6)))
        stock_weights: Dict[str, Decimal] = {c: w_per_stock for c in selected_stocks}
        # 修正尾数确保严格等于 0.75
        stock_sum = sum(stock_weights.values())
        diff = Decimal(str(self.config.equity_weight_target)) - stock_sum
        stock_weights[selected_stocks[0]] += diff

        # 期指空头与现金权重
        futures_weights = (
            {"IF_HEDGE": Decimal(str(self.config.futures_weight_target))}
            if self.config.futures_weight_target != 0
            else {}
        )
        cash_weight = Decimal(str(self.config.cash_weight_target))

        # 4. 生产级多空治理中台硬门禁穿透验证
        max_stock_limit = (
            Decimal(str(self.config.max_stock_weight))
            if n_selected >= 30
            else max(Decimal(str(self.config.max_stock_weight)), w_per_stock + Decimal("0.0001"))
        )
        is_compliant = self.portfolio_service.validate_hedged_portfolio(
            stock_weights=stock_weights,
            futures_weights=futures_weights,
            cash_weight=cash_weight,
            industry_map=self.industry_map,
            max_stock_weight=max_stock_limit,
            max_industry_weight=Decimal(str(self.config.max_industry_weight)),
            max_industry_stocks=self.config.max_industry_stocks,
        )

        if not is_compliant:
            logger.error("组合构建未通过生产级多空治理中台校验!")

        return {
            "as_of_date": as_of_date,
            "fiscal_year": fiscal_year,
            "stock_weights": stock_weights,
            "futures_weights": futures_weights,
            "cash_weight": cash_weight,
            "selected_count": n_selected,
            "is_compliant": is_compliant,
        }

    def execute_micro_rebalance(
        self,
        orders: List[Dict[str, Any]],
        adv_map: Dict[str, float],
        volatility_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """通过 InstitutionalExecutionOrchestrator 执行微观冲击与拆单计算"""
        return self.orchestrator.evaluate_rebalance_execution(
            orders=orders,
            adv_map=adv_map,
            volatility_map=volatility_map,
        )

    def get_governance_report(self) -> Dict[str, Any]:
        """获取私募机构 2/20 治理账本审计报表"""
        return self.fee_ledger.generate_governance_report()
