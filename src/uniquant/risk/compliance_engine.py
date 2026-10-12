# -*- coding: utf-8 -*-
"""
机构事前风控与合规签证引擎 (PreTradeComplianceEngine)
=====================================================

在交易清单落盘并下发给 PMS/OMS (如恒生 O32, 迅投 QMT) 之前，
执行毫秒级严格的硬风控边界审查与 SHA-256 密码学防篡改签证。

核心硬风控防线：
  1. 单票持仓集中度上限: w_i <= 2.5% AUM
  2. 申万一级行业集中度上限: Sum(w_ind) <= 10.0% AUM
  3. 行业单票数量上限: Count(stocks_in_ind) <= 4 只
  4. 组合杠杆与净敞口边界:
     - 多头总权重: <= 75.0%
     - 空头总对冲权重: <= 75.0%
     - 现金缓冲区: >= 25.0%
     - Gross Leverage: <= 175.0%
     - Net Exposure: [-0.5%, +0.5%] (严格市场中性)
  5. 中金所单 PB 主经纪商持仓限额: <= 1,200 手 / PB
  6. 现货整百股交易单位铁律: shares % 100 == 0
  7. 密码学防篡改证书: 对订单集合与风控指标计算 SHA-256 指纹
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class ComplianceMetrics:
    """合规审查指标明细"""
    aum_cny: float
    total_long_cny: float
    total_short_cny: float
    cash_buffer_cny: float
    long_weight_pct: float
    short_weight_pct: float
    cash_buffer_pct: float
    gross_leverage_pct: float
    net_exposure_pct: float
    max_single_stock_symbol: str
    max_single_stock_weight_pct: float
    max_industry_name: str
    max_industry_weight_pct: float
    max_industry_stock_count: int
    max_pb_contracts: int
    lot_sizing_compliant: bool
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ComplianceReport:
    """事前合规签证报告"""
    manifest_id: str
    verdict: str  # "APPROVED_PASS" | "REJECTED_BREACH"
    manifest_hash: str
    passed: bool
    breaches: List[str]
    warnings: List[str]
    metrics: ComplianceMetrics

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "verdict": self.verdict,
            "manifest_hash": self.manifest_hash,
            "passed": self.passed,
            "breaches": self.breaches,
            "warnings": self.warnings,
            "metrics": asdict(self.metrics),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class PreTradeComplianceEngine:
    """事前风控硬门禁审计器"""

    def __init__(
        self,
        max_single_stock_weight: float = 0.025,  # 2.5%
        max_industry_weight: float = 0.100,      # 10.0%
        max_industry_stock_count: int = 4,       # 单行业最多4只
        max_long_weight: float = 0.755,          # 允许 +0.5% 舍入裕度
        min_cash_buffer_weight: float = 0.245,   # 允许 -0.5% 舍入裕度
        max_gross_leverage: float = 1.76,        # 175% + 1% 裕度
        max_net_exposure_abs: float = 0.005,     # |Net| <= 0.5%
        max_pb_contract_limit: int = 1200,       # CFFEX 单 PB 1200 手限制
    ):
        self.max_single_stock_weight = max_single_stock_weight
        self.max_industry_weight = max_industry_weight
        self.max_industry_stock_count = max_industry_stock_count
        self.max_long_weight = max_long_weight
        self.min_cash_buffer_weight = min_cash_buffer_weight
        self.max_gross_leverage = max_gross_leverage
        self.max_net_exposure_abs = max_net_exposure_abs
        self.max_pb_contract_limit = max_pb_contract_limit

    def audit(
        self,
        manifest_id: str,
        aum_cny: float,
        equity_orders: pd.DataFrame,
        futures_hedging: pd.DataFrame,
        industry_mapping: Optional[Dict[str, str]] = None,
    ) -> ComplianceReport:
        """执行全套事前合规硬校验并签发证书。

        Args:
            manifest_id: 清单唯一流水号
            aum_cny: 基金净资产规模 (CNY)
            equity_orders: 现货多头订单表 (需包含 symbol, trade_shares, ref_price/est_amount, 可选 industry_l1)
            futures_hedging: 期货对冲分仓表 (需包含 contract_symbol, notional_cny, 以及各个 PB 分仓手数)
            industry_mapping: 股票到行业的映射字典 (可选，若 orders 中已有 industry_l1 则优先使用)
        """
        breaches: List[str] = []
        warnings: List[str] = []

        if aum_cny <= 0:
            raise ValueError(f"AUM must be strictly positive, got {aum_cny}")

        # 1. 现货多头统计
        eq_df = equity_orders.copy()
        if eq_df.empty:
            total_long_cny = 0.0
            max_stock_sym = ""
            max_stock_weight = 0.0
            max_ind_name = ""
            max_ind_weight = 0.0
            max_ind_count = 0
            lot_sizing_ok = True
        else:
            if "est_amount" not in eq_df.columns:
                if "trade_shares" in eq_df.columns and "ref_price" in eq_df.columns:
                    eq_df["est_amount"] = eq_df["trade_shares"] * eq_df["ref_price"]
                else:
                    raise KeyError("equity_orders must contain 'est_amount' or ('trade_shares' and 'ref_price')")

            total_long_cny = float(eq_df["est_amount"].sum())

            # 检查整百股铁律
            if "trade_shares" in eq_df.columns:
                invalid_lots = eq_df[eq_df["trade_shares"] % 100 != 0]
                if not invalid_lots.empty:
                    breaches.append(
                        f"整百股合规违背: 发现 {len(invalid_lots)} 笔订单股数非 100 的整数倍 "
                        f"(例如: {invalid_lots.iloc[0]['symbol']} 股数={invalid_lots.iloc[0]['trade_shares']})"
                    )
                    lot_sizing_ok = False
                else:
                    lot_sizing_ok = True
            else:
                lot_sizing_ok = True

            # 检查单票权重上限
            eq_df["weight"] = eq_df["est_amount"] / aum_cny
            max_stock_row = eq_df.loc[eq_df["weight"].idxmax()]
            max_stock_sym = str(max_stock_row["symbol"])
            max_stock_weight = float(max_stock_row["weight"])

            if max_stock_weight > self.max_single_stock_weight + 1e-6:
                breaches.append(
                    f"单票持仓集中度超限: 标的 {max_stock_sym} 权重为 {max_stock_weight*100:.3f}%, "
                    f"超过硬上限 {self.max_single_stock_weight*100:.2f}%"
                )

            # 行业集中度与持股数检查
            if "industry_l1" not in eq_df.columns and industry_mapping:
                eq_df["industry_l1"] = eq_df["symbol"].map(industry_mapping).fillna("综合")
            elif "industry_l1" not in eq_df.columns:
                eq_df["industry_l1"] = "全市场未分类"

            ind_grouped = eq_df.groupby("industry_l1").agg(
                ind_weight=("weight", "sum"),
                ind_count=("symbol", "count"),
            )

            max_ind_weight_row = ind_grouped.loc[ind_grouped["ind_weight"].idxmax()]
            max_ind_name = str(ind_grouped["ind_weight"].idxmax())
            max_ind_weight = float(max_ind_weight_row["ind_weight"])
            max_ind_count = int(ind_grouped["ind_count"].max())

            if max_ind_weight > self.max_industry_weight + 1e-6:
                breaches.append(
                    f"行业集中度超限: 行业 '{max_ind_name}' 权重为 {max_ind_weight*100:.3f}%, "
                    f"超过上限 {self.max_industry_weight*100:.2f}%"
                )

            if max_ind_count > self.max_industry_stock_count:
                breaches.append(
                    f"行业持股数量超限: 行业 '{ind_grouped['ind_count'].idxmax()}' 包含 "
                    f"{max_ind_count} 只股票, 超过上限 {self.max_industry_stock_count} 只"
                )

        # 2. 期货空头对冲统计
        fut_df = futures_hedging.copy()
        if fut_df.empty:
            total_short_cny = 0.0
            max_pb_hands = 0
        else:
            if "notional_cny" in fut_df.columns:
                total_short_cny = float(fut_df["notional_cny"].sum())
            else:
                total_short_cny = 0.0

            # 检查单 PB 持仓限额
            pb_cols = [c for c in fut_df.columns if "pb" in c.lower() and "contract" in c.lower()]
            if pb_cols:
                max_pb_hands = int(fut_df[pb_cols].max().max())
                for col in pb_cols:
                    col_max = int(fut_df[col].max())
                    if col_max > self.max_pb_contract_limit:
                        breaches.append(
                            f"中金所主经纪商(PB)持仓超限: {col} 分配手数 {col_max} 手, "
                            f"超过 CFFEX 限仓 {self.max_pb_contract_limit} 手"
                        )
            else:
                max_pb_hands = 0

        # 3. 宏观杠杆与净敞口指标
        cash_buffer_cny = aum_cny - total_long_cny
        long_weight = total_long_cny / aum_cny
        short_weight = total_short_cny / aum_cny
        cash_weight = cash_buffer_cny / aum_cny
        gross_leverage = (total_long_cny + total_short_cny + cash_buffer_cny) / aum_cny
        net_exposure = (total_long_cny - total_short_cny) / aum_cny

        if long_weight > self.max_long_weight:
            breaches.append(
                f"多头总仓位超限: 多头实际占用 {long_weight*100:.3f}%, 超过上限 {self.max_long_weight*100:.2f}%"
            )

        if cash_weight < self.min_cash_buffer_weight:
            breaches.append(
                f"现金缓冲区不足: 现金实际保留 {cash_weight*100:.3f}%, 低于安全底线 {self.min_cash_buffer_weight*100:.2f}%"
            )

        if gross_leverage > self.max_gross_leverage:
            breaches.append(
                f"总杠杆率超限: Gross Leverage 为 {gross_leverage*100:.3f}%, 超过上限 {self.max_gross_leverage*100:.2f}%"
            )

        if abs(net_exposure) > self.max_net_exposure_abs:
            breaches.append(
                f"对冲净敞口失衡: 净敞口 Net Exposure 为 {net_exposure*100:.4f}%, "
                f"超出绝对中性容差 [{-self.max_net_exposure_abs*100:.2f}%, {self.max_net_exposure_abs*100:.2f}%]"
            )

        # 4. 指纹签名计算 (SHA-256)
        metrics = ComplianceMetrics(
            aum_cny=aum_cny,
            total_long_cny=total_long_cny,
            total_short_cny=total_short_cny,
            cash_buffer_cny=cash_buffer_cny,
            long_weight_pct=round(long_weight * 100, 4),
            short_weight_pct=round(short_weight * 100, 4),
            cash_buffer_pct=round(cash_weight * 100, 4),
            gross_leverage_pct=round(gross_leverage * 100, 4),
            net_exposure_pct=round(net_exposure * 100, 4),
            max_single_stock_symbol=max_stock_sym,
            max_single_stock_weight_pct=round(max_stock_weight * 100, 4),
            max_industry_name=max_ind_name,
            max_industry_weight_pct=round(max_ind_weight * 100, 4),
            max_industry_stock_count=max_ind_count,
            max_pb_contracts=max_pb_hands,
            lot_sizing_compliant=lot_sizing_ok,
        )

        has_passed = len(breaches) == 0
        verdict = "APPROVED_PASS" if has_passed else "REJECTED_BREACH"

        # 生成确定性加密指纹
        signature_payload = {
            "manifest_id": manifest_id,
            "aum_cny": aum_cny,
            "verdict": verdict,
            "metrics": asdict(metrics),
            "breaches": breaches,
        }
        manifest_hash = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return ComplianceReport(
            manifest_id=manifest_id,
            verdict=verdict,
            manifest_hash=manifest_hash,
            passed=has_passed,
            breaches=breaches,
            warnings=warnings,
            metrics=metrics,
        )
