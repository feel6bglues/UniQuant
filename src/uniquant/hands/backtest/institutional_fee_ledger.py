"""
私募机构级 2/20 治理账本 (Institutional Fee & Governance Ledger)
=============================================================================
遵循私募机构合规与估值外包核算规范 (符合 CNMM-QAR 生产级蓝图 5.5 节设计):
1. ACT/365 自然日 2.0% 管理费每日计提 (涵盖节假日自然日计提, 杜绝工作日断层与托管对账漂移);
2. 固化高水位线 (Crystallized HWM) 与 6.0% Hurdle 门槛净值 (杜绝回撤期高水位虚增);
3. 每日业绩报酬准备金暂估 (Daily Carry Accrual) 与回撤自动冲销 (Reversal), 彻底消除代数死循环;
4. 历史法定结算日 (Crystallization Date) 业绩报酬正式固化与高水位线阶梯重置。
=============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeeSnapshot:
    """每日费用与公允净值切片"""
    date: pd.Timestamp
    gross_nav: float            # 费前原始毛净值
    net_nav: float              # 扣除管理费与业绩准备金后的公允公布净值
    mgmt_fee_accrued: float     # 当日计提的管理费金额 (每份)
    carry_accrued: float        # 当日应付业绩报酬准备金余额 (每份, 未固化)
    crystallized_hwm: float     # 当前基准固化高水位线
    hurdle_nav: float           # 当期动态门槛净值
    is_crystallized: bool       # 当日是否触发法定结算法定日
    crystallized_carry: float   # 当日实际划转固化的业绩报酬 (每份)


class InstitutionalFeeLedger:
    """
    私募机构级 2/20 治理账本实现
    
    参数:
        mgmt_fee_rate: 年化管理费率 (默认 0.02 即 2.0%)
        carry_rate: 业绩报酬提成比例 (默认 0.20 即 20.0%)
        hurdle_rate: 年化门槛收益率 (默认 0.06 即 6.0%)
        initial_nav: 初始设立净值 (默认 1.0)
        start_date: 基金成立日期
    """

    def __init__(
        self,
        mgmt_fee_rate: float = 0.02,
        carry_rate: float = 0.20,
        hurdle_rate: float = 0.06,
        initial_nav: float = 1.0,
        start_date: Optional[pd.Timestamp | str] = None,
    ):
        self.mgmt_fee_rate = float(mgmt_fee_rate)
        self.carry_rate = float(carry_rate)
        self.hurdle_rate = float(hurdle_rate)
        self.initial_nav = float(initial_nav)

        if start_date is None:
            self.start_date = pd.Timestamp("2000-01-01")
        else:
            self.start_date = pd.Timestamp(start_date)

        self.crystallized_hwm = self.initial_nav
        self.last_crys_date = self.start_date
        self.last_date = self.start_date
        self.cumulative_mgmt_fee = 0.0
        self.cumulative_crystallized_carry = 0.0
        self.history: List[FeeSnapshot] = []

    def calculate_daily_fair_nav(
        self,
        current_date: pd.Timestamp | str,
        raw_nav: float,
        is_crys_date: bool = False,
    ) -> FeeSnapshot:
        """
        计算单日机构公允净值、管理费计提与准备金暂估
        
        Args:
            current_date: 当前核算日期
            raw_nav: 费前毛净值
            is_crys_date: 当日是否为法定业绩报酬结算固化日 (如每年 12-31)
            
        Returns:
            FeeSnapshot 包含净值分解切片
        """
        curr_dt = pd.Timestamp(current_date)
        raw_nav = float(raw_nav)

        # 1. ACT/365 自然日管理费计提
        cal_days = max(1, (curr_dt - self.last_date).days)
        daily_mgmt_rate = (self.mgmt_fee_rate / 365.0) * cal_days
        mgmt_fee = raw_nav * daily_mgmt_rate
        nav_after_mgmt = raw_nav - mgmt_fee
        self.cumulative_mgmt_fee += mgmt_fee

        # 2. 期间 Hurdle 门槛净值 (基于固化 HWM 与自然日天数严格线性累加)
        days_since_crys = max(0, (curr_dt - self.last_crys_date).days)
        hurdle_nav = self.crystallized_hwm * (1.0 + self.hurdle_rate * (days_since_crys / 365.0))

        # 3. 每日业绩报酬准备金暂估 (Contingent Carry Accrual)
        # 消除代数死循环: 准备金列入负债，不改变原始净值基数，回撤时自动冲销
        if nav_after_mgmt > hurdle_nav:
            carry_accrual = self.carry_rate * (nav_after_mgmt - hurdle_nav)
        else:
            carry_accrual = 0.0

        published_nav = nav_after_mgmt - carry_accrual
        crystallized_carry = 0.0

        # 4. 法定结算日固化 (Crystallization)
        if is_crys_date and carry_accrual > 0.0:
            crystallized_carry = carry_accrual
            self.cumulative_crystallized_carry += crystallized_carry
            # 固化后，公布净值即为新一轮周期的固化高水位线
            self.crystallized_hwm = published_nav
            self.last_crys_date = curr_dt
            carry_accrual = 0.0  # 准备金已正式转化为已支付，暂估余额重置为 0

        self.last_date = curr_dt

        snapshot = FeeSnapshot(
            date=curr_dt,
            gross_nav=round(raw_nav, 6),
            net_nav=round(published_nav, 6),
            mgmt_fee_accrued=round(mgmt_fee, 6),
            carry_accrued=round(carry_accrual, 6),
            crystallized_hwm=round(self.crystallized_hwm, 6),
            hurdle_nav=round(hurdle_nav, 6),
            is_crystallized=bool(is_crys_date and crystallized_carry > 0.0),
            crystallized_carry=round(crystallized_carry, 6),
        )
        self.history.append(snapshot)
        return snapshot

    def process_nav_series(
        self,
        df_nav: pd.DataFrame,
        date_col: str = "date",
        nav_col: str = "raw_nav",
        crystallization_dates: Optional[Set[pd.Timestamp] | List[pd.Timestamp | str]] = None,
    ) -> pd.DataFrame:
        """
        批量核算净值时序数据
        
        Args:
            df_nav: 包含日期与毛净值的 DataFrame
            date_col: 日期列名
            nav_col: 毛净值列名
            crystallization_dates: 法定结算日集合 (默认每年最后一个交易日)
            
        Returns:
            DataFrame 包含完整费用与公允净值全明细
        """
        df = df_nav.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col).reset_index(drop=True)

        if crystallization_dates is None:
            # 默认每年年末最后一个交易日为法定结算日
            crys_set = set()
            df["_year"] = df[date_col].dt.year
            for _, grp in df.groupby("_year"):
                crys_set.add(grp[date_col].iloc[-1])
        else:
            crys_set = {pd.Timestamp(d) for d in crystallization_dates}

        records = []
        for _, row in df.iterrows():
            d = row[date_col]
            val = row[nav_col]
            is_crys = d in crys_set
            snap = self.calculate_daily_fair_nav(d, val, is_crys_date=is_crys)
            records.append({
                "date": snap.date,
                "gross_nav": snap.gross_nav,
                "net_nav": snap.net_nav,
                "mgmt_fee_accrued": snap.mgmt_fee_accrued,
                "carry_accrued": snap.carry_accrued,
                "crystallized_hwm": snap.crystallized_hwm,
                "hurdle_nav": snap.hurdle_nav,
                "is_crystallized": snap.is_crystallized,
                "crystallized_carry": snap.crystallized_carry,
            })

        return pd.DataFrame(records)

    def generate_governance_report(self) -> Dict[str, Any]:
        """
        生成私募机构治理账本与公允净值审计核心报表
        
        Returns:
            Dict 包含费前/费后 CAGR、夏普、回撤、已结转业绩报酬、待结转准备金等
        """
        if not self.history:
            return {"error": "无净值历史记录"}

        df_hist = pd.DataFrame([s.__dict__ for s in self.history])
        first_date = df_hist["date"].iloc[0]
        last_date = df_hist["date"].iloc[-1]
        cal_days = max(1, (last_date - first_date).days)
        years = cal_days / 365.25

        gross_initial = df_hist["gross_nav"].iloc[0]
        gross_final = df_hist["gross_nav"].iloc[-1]
        net_initial = df_hist["net_nav"].iloc[0]
        net_final = df_hist["net_nav"].iloc[-1]

        gross_cagr = (gross_final / gross_initial) ** (1.0 / years) - 1.0 if years > 0 and gross_initial > 0 else 0.0
        net_cagr = (net_final / net_initial) ** (1.0 / years) - 1.0 if years > 0 and net_initial > 0 else 0.0
        fee_drag = gross_cagr - net_cagr

        df_hist["gross_ret"] = df_hist["gross_nav"].pct_change().fillna(0.0)
        df_hist["net_ret"] = df_hist["net_nav"].pct_change().fillna(0.0)

        gross_vol = float(df_hist["gross_ret"].std(ddof=1) * np.sqrt(252.0))
        net_vol = float(df_hist["net_ret"].std(ddof=1) * np.sqrt(252.0))

        gross_sharpe = (gross_cagr - self.hurdle_rate) / gross_vol if gross_vol > 0 else 0.0
        net_sharpe = (net_cagr - self.hurdle_rate) / net_vol if net_vol > 0 else 0.0

        def _calc_mdd(nav_s: pd.Series) -> float:
            cummax = np.maximum.accumulate(nav_s)
            dd = (cummax - nav_s) / (cummax + 1e-12)
            return float(np.max(dd))

        gross_mdd = _calc_mdd(df_hist["gross_nav"])
        net_mdd = _calc_mdd(df_hist["net_nav"])

        num_crys_events = int(df_hist["is_crystallized"].sum())
        total_crystallized_carry = float(df_hist["crystallized_carry"].sum())
        last_accrued_carry = float(df_hist["carry_accrued"].iloc[-1])
        total_mgmt_fee = float(df_hist["mgmt_fee_accrued"].sum())

        return {
            "period": f"{first_date.strftime('%Y-%m-%d')} ~ {last_date.strftime('%Y-%m-%d')}",
            "calendar_days": cal_days,
            "trading_days": len(df_hist),
            "initial_nav": round(net_initial, 6),
            "final_gross_nav": round(gross_final, 6),
            "final_net_nav": round(net_final, 6),
            "gross_cagr_pct": round(gross_cagr * 100, 2),
            "net_cagr_pct": round(net_cagr * 100, 2),
            "fee_drag_pct": round(fee_drag * 100, 2),
            "gross_volatility_pct": round(gross_vol * 100, 2),
            "net_volatility_pct": round(net_vol * 100, 2),
            "gross_sharpe": round(gross_sharpe, 2),
            "net_sharpe": round(net_sharpe, 2),
            "gross_max_drawdown_pct": round(gross_mdd * 100, 2),
            "net_max_drawdown_pct": round(net_mdd * 100, 2),
            "crystallized_hwm": round(self.crystallized_hwm, 6),
            "cumulative_mgmt_fee_paid": round(total_mgmt_fee, 6),
            "cumulative_crystallized_carry_paid": round(total_crystallized_carry, 6),
            "pending_carry_reserve": round(last_accrued_carry, 6),
            "crystallization_events_count": num_crys_events,
        }

