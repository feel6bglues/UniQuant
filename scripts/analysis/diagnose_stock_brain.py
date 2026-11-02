#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 大脑多引擎综合诊断与仲裁工具 (Diagnose Stock Brain)
============================================================
核心职责:
1. 联动宏观安全阀 (Regime & MA120 迟滞带): 判定大势允许度;
2. 联动基本面法医排雷 (CAS 会计与 Q1 造血): 判定标的是否安全;
3. 联动技术面结构 (威科夫形态与技术指标): 识别右侧买卖时机;
4. 联动 FSM 仲裁中枢: 综合输出确定性动作 (BUY / HOLD / EXIT / VETO_CASH) 与单票 -8% 止损线。
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.uniquant.shared.logger_factory import get_logger

logger = get_logger("scripts.analysis.diagnose_stock_brain")


@dataclass
class BrainDiagnosisResult:
    """大脑多引擎诊断结果输出"""
    symbol: str
    as_of_date: str
    macro_regime: str           # 'BULL_OFFENSE' | 'CAUTION_DEFENSE' | 'BEAR_PANIC_CASH'
    macro_allowed: bool
    forensic_status: str        # 'SAFE_Q1' | 'ACCEPTABLE' | 'VETO_HIGH_RISK'
    forensic_safe: bool
    tech_phase: str             # 'PHASE_C_SPRING' | 'PHASE_D_BREAKOUT' | 'PHASE_E_MARKUP' | 'CONSOLIDATION' | 'DOWNTREND'
    tech_score: float           # 0.0 ~ 100.0
    final_action: str           # 'BUY_PROBE' | 'BUY_AGGRESSIVE' | 'HOLD' | 'EXIT_STOP_LOSS' | 'VETO_CASH'
    recommended_position_pct: float
    hard_stop_price: float
    decision_reasons: List[str]


class StockBrainDiagnoser:
    """个股多大脑联动诊断器"""

    def __init__(self, lake_root: Optional[Path | str] = None) -> None:
        self.root = Path(lake_root or (PROJECT_ROOT / "data" / "lake"))

    def _load_daily_quote(self, symbol: str) -> Optional[pd.DataFrame]:
        """从数据湖加载日线数据"""
        p_daily = self.root / "quotes" / "daily" / f"{symbol}.parquet"
        p_idx = self.root / "quotes" / "index" / f"{symbol}.parquet"
        target = p_daily if p_daily.exists() else p_idx
        if not target.exists():
            return None
        df = pd.read_parquet(target)
        date_col = "trade_date" if "trade_date" in df.columns else "date"
        df = df.rename(columns={date_col: "trade_date"}).sort_values("trade_date")
        df["trade_date"] = df["trade_date"].astype(str)
        return df

    def diagnose_stock(
        self,
        symbol: str,
        as_of_date: Optional[str] = None,
        cost_price: Optional[float] = None,
    ) -> BrainDiagnosisResult:
        """端到端调用大脑各模块执行综合诊断"""
        # 1. 宏观水温检查 (以 000300.SH 为基准)
        df_bm = self._load_daily_quote("000300.SH")
        macro_regime = "CAUTION_DEFENSE"
        macro_allowed = True
        reasons = []

        if df_bm is not None and len(df_bm) >= 120:
            sub_bm = df_bm[df_bm["trade_date"] <= as_of_date] if as_of_date else df_bm
            if len(sub_bm) >= 120:
                p_bm = float(sub_bm["close"].iloc[-1])
                ma120_bm = float(sub_bm["close"].rolling(120).mean().iloc[-1])
                if p_bm > ma120_bm * 1.015:
                    macro_regime = "BULL_OFFENSE"
                    reasons.append("基准指数稳居半年线上方，宏观处于进攻通道")
                elif p_bm < ma120_bm * 0.985:
                    macro_regime = "BEAR_PANIC_CASH"
                    macro_allowed = False
                    reasons.append("基准指数跌破半年线迟滞下轨，宏观触发空仓避险")
                else:
                    reasons.append("基准指数在半年线迟滞带震荡，宏观处于谨慎半仓态")

        # 2. 个股日线与技术指标评估
        df_stock = self._load_daily_quote(symbol)
        if df_stock is None or len(df_stock) < 30:
            cur_price = cost_price or 100.0
            cur_date = as_of_date or "LATEST"
            return BrainDiagnosisResult(
                symbol=symbol,
                as_of_date=cur_date,
                macro_regime=macro_regime,
                macro_allowed=macro_allowed,
                forensic_status="ACCEPTABLE",
                forensic_safe=True,
                tech_phase="CONSOLIDATION",
                tech_score=50.0,
                final_action="VETO_CASH" if not macro_allowed else "HOLD",
                recommended_position_pct=0.0 if not macro_allowed else 5.0,
                hard_stop_price=round(cur_price * 0.92, 2),
                decision_reasons=reasons + ["个股历史日线数据不足，保持防御观望"],
            )

        sub_stock = df_stock[df_stock["trade_date"] <= as_of_date] if as_of_date else df_stock
        cur_row = sub_stock.iloc[-1]
        cur_date = str(cur_row["trade_date"])
        cur_price = float(cur_row["close"])

        # 技术面指标快速计算
        ma20 = float(sub_stock["close"].rolling(20).mean().iloc[-1]) if len(sub_stock) >= 20 else cur_price
        ma60 = float(sub_stock["close"].rolling(60).mean().iloc[-1]) if len(sub_stock) >= 60 else cur_price

        # 3. 威科夫形态模拟判定
        tech_score = 50.0
        if cur_price > ma20 and ma20 > ma60:
            tech_phase = "PHASE_D_BREAKOUT"
            tech_score = 80.0
            reasons.append("均线多头排列 (收盘 > MA20 > MA60)，呈现威科夫 Phase D 突破特征")
        elif cur_price < ma20 and cur_price < ma60:
            tech_phase = "DOWNTREND"
            tech_score = 25.0
            reasons.append("个股处于均线下方空头下行通道，未见企稳信号")
        else:
            tech_phase = "CONSOLIDATION"
            tech_score = 55.0
            reasons.append("个股处于区间震荡整理中")

        # 4. 法医安全判定 (预检财务湖)
        fin_path = self.root / "financial" / f"{symbol}.parquet"
        forensic_safe = True
        forensic_status = "SAFE_Q1"

        if fin_path.exists():
            try:
                df_fin = pd.read_parquet(fin_path)
                if not df_fin.empty:
                    last_fin = df_fin.iloc[-1]
                    roe = float(last_fin.get("净资产收益率", 0.10) or 0.10)
                    if roe < 0.0:
                        forensic_safe = False
                        forensic_status = "VETO_HIGH_RISK"
                        reasons.append(f"最新财报 ROE 为负 ({roe:.2%})，触发法医一票否决")
                    elif roe >= 0.12:
                        forensic_status = "SAFE_Q1"
                        reasons.append(f"最新财报 ROE 达标 ({roe:.2%})，归属于优质 Q1 特许造血池")
                    else:
                        forensic_status = "ACCEPTABLE"
            except Exception:
                pass

        # 5. FSM 综合仲裁
        hard_stop = round((cost_price or cur_price) * 0.92, 2)
        if cost_price and cur_price <= cost_price * 0.92:
            final_action = "EXIT_STOP_LOSS"
            rec_pos = 0.0
            reasons.append(f"【硬止损触发】当前价格 ({cur_price:.2f}) 较买入成本 ({cost_price:.2f}) 跌超 -8.0%，强制剥离清仓！")
        elif not macro_allowed:
            final_action = "VETO_CASH"
            rec_pos = 0.0
            reasons.append("【宏观否决】宏观安全阀处于熊市空仓态，严禁买入，资金结转为 100% 现金")
        elif not forensic_safe:
            final_action = "VETO_CASH"
            rec_pos = 0.0
            reasons.append("【法医否决】标的财务排雷不通过，严禁建仓")
        elif tech_phase == "PHASE_D_BREAKOUT" and tech_score >= 75.0:
            final_action = "BUY_PROBE"
            rec_pos = 8.0 if macro_regime == "BULL_OFFENSE" else 4.0
            reasons.append(f"【建议建仓】宏观与技术面共振，建议建仓 {rec_pos:.1f}% 仓位，止损位设在 {hard_stop:.2f}")
        else:
            final_action = "HOLD"
            rec_pos = 5.0
            reasons.append("【持股待涨】当前标的状态平稳，维持现有观察底仓")

        return BrainDiagnosisResult(
            symbol=symbol,
            as_of_date=cur_date,
            macro_regime=macro_regime,
            macro_allowed=macro_allowed,
            forensic_status=forensic_status,
            forensic_safe=forensic_safe,
            tech_phase=tech_phase,
            tech_score=tech_score,
            final_action=final_action,
            recommended_position_pct=rec_pos,
            hard_stop_price=hard_stop,
            decision_reasons=reasons,
        )


def main() -> int:
    """CLI 诊断入口"""
    parser = argparse.ArgumentParser(description="UniQuant 大脑多引擎综合诊断器")
    parser.add_argument("symbol", type=str, help="股票代码 (如 600519.SH)")
    parser.add_argument("--date", type=str, default="", help="指定评估日期 YYYY-MM-DD")
    parser.add_argument("--cost", type=float, default=None, help="持仓买入成本价")
    args = parser.parse_args()

    diagnoser = StockBrainDiagnoser()
    result = diagnoser.diagnose_stock(symbol=args.symbol, as_of_date=args.date or None, cost_price=args.cost)
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
