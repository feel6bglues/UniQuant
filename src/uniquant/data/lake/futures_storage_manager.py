#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中金所股指期货合约链与高频动态基差曲面数据湖 (FuturesStorageManager)

核心职责：
1. 管理中金所股指期货合约链：
   - IF (沪深300股指期货, 乘数 300, 保证金率 12%, 标的 000300.SH, 最小变动价位 0.2)
   - IC (中证500股指期货, 乘数 200, 保证金率 12%, 标的 000905.SH, 最小变动价位 0.2)
   - IM (中证1000股指期货, 乘数 200, 保证金率 15%, 标的 000852.SH, 最小变动价位 0.2)
   - IH (上证50股指期货, 乘数 300, 保证金率 12%, 标的 000016.SH, 最小变动价位 0.2)
2. 构建全合约期限结构动态基差曲面湖 (Dynamic Basis Surface Lake)：
   - 即期基差: Basis_t(T) = F_t(T) - S_t
   - 基差率: BasisRate_t(T) = (F_t(T) - S_t) / S_t * 100%
   - ACT/365 自然日年化贴水率: Carry_t(T) = ((F_t(T) - S_t) / S_t) * (365 / DTE)
   - 期限结构斜率: S_term = d(Basis) / dT
3. MLSI (Multi-Level Spread Indicator) 动态对冲防线接口：
   - 计算动态对冲比率 beta*(t) = beta_portfolio * phi(MLSI_t)
   - 展期最优目标权重 (Roll Target Weights)，彻底废除静态 -2.50% 贴水粗暴假设。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger("FuturesStorageManager")

# 标的现货与中金所期货品种映射
UNDERLYING_MAP: Dict[str, Dict[str, Any]] = {
    "000300.SH": {
        "variety": "IF",
        "name": "沪深300股指期货",
        "multiplier": 300.0,
        "margin_ratio": 0.12,
        "tick_size": 0.2,
    },
    "000905.SH": {
        "variety": "IC",
        "name": "中证500股指期货",
        "multiplier": 200.0,
        "margin_ratio": 0.12,
        "tick_size": 0.2,
    },
    "000852.SH": {
        "variety": "IM",
        "name": "中证1000股指期货",
        "multiplier": 200.0,
        "margin_ratio": 0.15,
        "tick_size": 0.2,
    },
    "000016.SH": {
        "variety": "IH",
        "name": "上证50股指期货",
        "multiplier": 300.0,
        "margin_ratio": 0.12,
        "tick_size": 0.2,
    },
}

VARIETY_TO_UNDERLYING: Dict[str, str] = {
    v["variety"]: k for k, v in UNDERLYING_MAP.items()
}


@dataclass
class FuturesContract:
    """股指期货合约静态元数据契约"""
    symbol: str             # 如 "IF2406", "IF2406.CFX"
    underlying: str         # 对应标的现货代码 "000300.SH"
    multiplier: float       # 合约乘数 (点/元)
    margin_ratio: float     # 最低保证金比例 (如 0.12)
    expiry_date: pd.Timestamp  # 最后交易日/到期交割日
    tick_size: float = 0.2     # 最小变动价位

    @property
    def clean_symbol(self) -> str:
        """纯净合约代码 (剔除 .CFX 后缀)"""
        return self.symbol.split(".")[0].upper()

    @property
    def variety(self) -> str:
        """品种代码 (IF, IC, IM, IH)"""
        return re.match(r"^([A-Z]+)", self.clean_symbol).group(1)

    @property
    def delivery_month(self) -> str:
        """4位交割年月 (如 '2406')"""
        m = re.search(r"(\d{4})", self.clean_symbol)
        return m.group(1) if m else ""


def calculate_third_friday(year: int, month: int) -> pd.Timestamp:
    """计算指定年月的第三个星期五 (中金所股指期货交割日基准)。"""
    # 找到当月第1天
    first_day = pd.Timestamp(year=year, month=month, day=1)
    # 星期五是 weekday == 4 (0=周一, 4=周五)
    first_friday_day = 1 + (4 - first_day.weekday()) % 7
    third_friday_day = first_friday_day + 14
    return pd.Timestamp(year=year, month=month, day=third_friday_day)


class FuturesStorageManager:
    """中金所股指期货合约链与高频动态基差曲面数据湖管理器"""

    def __init__(
        self,
        lake_dir: Union[str, Path] = "data/lake/futures",
        quotes_dir: Union[str, Path] = "data/lake/quotes",
        trade_calendar_path: Union[str, Path] = "data/trade_calendar.csv",
    ):
        self.lake_dir = Path(lake_dir)
        self.quotes_dir = Path(quotes_dir)
        self.trade_calendar_path = Path(trade_calendar_path)

        self._contract_cache: Dict[str, FuturesContract] = {}
        self._data_cache: Dict[str, pd.DataFrame] = {}
        self._trade_calendar: Optional[pd.DataFrame] = None

        logger.info(f"FuturesStorageManager 初始化完成: lake_dir={self.lake_dir}")

    # =========================================================================
    # 1. 合约元数据与合约链管理
    # =========================================================================

    def get_contract(self, symbol: str) -> Optional[FuturesContract]:
        """获取指定合约的静态规范元数据。"""
        clean_sym = symbol.split(".")[0].upper()
        if clean_sym in self._contract_cache:
            return self._contract_cache[clean_sym]

        m = re.match(r"^([A-Z]+)(\d{4})$", clean_sym)
        if not m:
            # 连续合约如 IF0, IC0, IM0
            m_cont = re.match(r"^([A-Z]+)0$", clean_sym)
            if m_cont:
                variety = m_cont.group(1)
                underlying = VARIETY_TO_UNDERLYING.get(variety)
                if underlying:
                    info = UNDERLYING_MAP[underlying]
                    contract = FuturesContract(
                        symbol=clean_sym,
                        underlying=underlying,
                        multiplier=info["multiplier"],
                        margin_ratio=info["margin_ratio"],
                        expiry_date=pd.Timestamp("2099-12-31"),
                        tick_size=info["tick_size"],
                    )
                    self._contract_cache[clean_sym] = contract
                    return contract
            return None

        variety, yymm = m.group(1), m.group(2)
        underlying = VARIETY_TO_UNDERLYING.get(variety)
        if not underlying:
            return None

        info = UNDERLYING_MAP[underlying]
        year = 2000 + int(yymm[:2])
        month = int(yymm[2:])
        base_expiry = calculate_third_friday(year, month)

        # 结合交易日历微调可能遇节假日顺延的真实交割日
        adjusted_expiry = self._adjust_expiry_by_calendar(base_expiry)

        contract = FuturesContract(
            symbol=clean_sym,
            underlying=underlying,
            multiplier=info["multiplier"],
            margin_ratio=info["margin_ratio"],
            expiry_date=adjusted_expiry,
            tick_size=info["tick_size"],
        )
        self._contract_cache[clean_sym] = contract
        return contract

    def _adjust_expiry_by_calendar(self, dt: pd.Timestamp) -> pd.Timestamp:
        """如果交割日不是交易日，顺延至下一个交易日。"""
        cal = self._get_trade_calendar()
        if cal is None or cal.empty:
            return dt
        dt_str = dt.strftime("%Y-%m-%d")
        valid_dates = cal[cal["trade_date"] >= dt_str]["trade_date"].tolist()
        if valid_dates:
            return pd.Timestamp(valid_dates[0])
        return dt

    def _get_trade_calendar(self) -> Optional[pd.DataFrame]:
        if self._trade_calendar is None and self.trade_calendar_path.exists():
            try:
                self._trade_calendar = pd.read_csv(self.trade_calendar_path)
            except Exception as e:
                logger.warning(f"读取交易日历失败: {e}")
        return self._trade_calendar

    def get_contract_chain(
        self, underlying: str, date: pd.Timestamp
    ) -> List[FuturesContract]:
        """
        获取指定日期指定标的所有存续活跃的期货合约列表（按到期日升序排列）。
        """
        variety = UNDERLYING_MAP.get(underlying, {}).get("variety")
        if not variety:
            return []

        cur_date = pd.Timestamp(date).normalize()
        active_contracts: List[FuturesContract] = []

        # 扫描现有 parquet 文件
        for p in self.lake_dir.glob(f"{variety}*.parquet"):
            sym = p.stem.upper()
            if sym.endswith("0"):  # 排除连续合约
                continue
            contract = self.get_contract(sym)
            if contract and contract.expiry_date >= cur_date:
                # 检查当日是否已上市且有数据
                df = self.read_futures_daily(sym)
                if not df.empty and cur_date in df["date"].values:
                    active_contracts.append(contract)

        active_contracts.sort(key=lambda c: c.expiry_date)
        return active_contracts

    def get_dominant_contract(
        self, underlying: str, date: pd.Timestamp
    ) -> Optional[str]:
        """
        获取指定日期流动性最大（成交量与持仓量综合）的主力合约代码。
        """
        chain = self.get_contract_chain(underlying, date)
        if not chain:
            return None

        cur_date = pd.Timestamp(date).normalize()
        best_symbol = None
        max_score = -1.0

        for contract in chain:
            df = self.read_futures_daily(contract.clean_symbol)
            sub = df[df["date"] == cur_date]
            if not sub.empty:
                vol = float(sub["volume"].iloc[0])
                hold = float(sub["hold"].iloc[0])
                # 主力判断权重: 持仓量 60% + 成交量 40%
                score = hold * 0.6 + vol * 0.4
                if score > max_score:
                    max_score = score
                    best_symbol = contract.clean_symbol

        return best_symbol

    # =========================================================================
    # 2. 动态基差曲面湖与 ACT/365 年化贴水率计算
    # =========================================================================

    def read_futures_daily(self, symbol: str) -> pd.DataFrame:
        """读取单期货合约日线 Parquet 数据（具备进程内缓存）。"""
        clean_sym = symbol.split(".")[0].upper()
        if clean_sym in self._data_cache:
            return self._data_cache[clean_sym]

        path = self.lake_dir / f"{clean_sym}.parquet"
        if not path.exists():
            return pd.DataFrame()

        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            self._data_cache[clean_sym] = df
            return df
        except Exception as e:
            logger.error(f"读取期货日线失败 {path}: {e}")
            return pd.DataFrame()

    def read_spot_daily(self, underlying: str) -> pd.DataFrame:
        """读取现货指数日线数据。"""
        cache_key = f"SPOT_{underlying}"
        if cache_key in self._data_cache:
            return self._data_cache[cache_key]

        path = self.quotes_dir / "index" / f"{underlying}.parquet"
        if not path.exists():
            path = self.quotes_dir / "daily" / f"{underlying}.parquet"
        if not path.exists():
            logger.error(f"现货指数文件不存在: {path}")
            return pd.DataFrame()

        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            self._data_cache[cache_key] = df
            return df
        except Exception as e:
            logger.error(f"读取现货指数失败 {path}: {e}")
            return pd.DataFrame()

    def get_dynamic_basis_surface(
        self, underlying: str, date: pd.Timestamp
    ) -> Dict[str, Any]:
        """
        获取指定日期全合约链的动态基差曲面与年化贴水率。
        
        返回数据规约：
        {
            "date": Timestamp,
            "underlying": str,
            "spot_close": float,
            "dominant_symbol": str,
            "dominant_basis": float,
            "dominant_carry": float,
            "term_slope": float,  # 基差对到期年限的期限斜率 d(Basis)/dT
            "contracts": [
                {
                    "symbol": "IM2406",
                    "contract_month": "quarter",
                    "futures_close": 5440.0,
                    "futures_settle": 5406.8,
                    "dte": 45,  # 自然日到期天数
                    "basis": -70.0,
                    "basis_rate_pct": -1.27,
                    "annualized_carry": -10.31,  # ACT/365 自然日年化贴水率
                    "open_interest": 150000,
                    "volume": 85000,
                }, ...
            ]
        }
        """
        cur_date = pd.Timestamp(date).normalize()
        spot_df = self.read_spot_daily(underlying)
        if spot_df.empty:
            raise ValueError(f"无法读取标的 {underlying} 的现货行情")

        spot_sub = spot_df[spot_df["date"] == cur_date]
        if spot_sub.empty:
            raise ValueError(f"标的 {underlying} 在日期 {cur_date.date()} 无现货数据")

        spot_close = float(spot_sub["close"].iloc[0])
        if not np.isfinite(spot_close):
            # §7.4 #2: 非有限现货价 = 无可用数据，与「无现货行」同类处理（响亮失败），
            # 禁止把 NaN 静默扩散进基差/斜率进而落湖。
            raise ValueError(f"标的 {underlying} 在日期 {cur_date.date()} 现货收盘价非有限值")
        chain = self.get_contract_chain(underlying, cur_date)

        contracts_data: List[Dict[str, Any]] = []
        dtes: List[float] = []
        bases: List[float] = []

        dominant_sym = self.get_dominant_contract(underlying, cur_date)
        dominant_basis = 0.0
        dominant_carry = 0.0

        month_labels = ["current", "next", "quarter", "next_quarter", "far_quarter"]

        for idx, contract in enumerate(chain):
            f_df = self.read_futures_daily(contract.clean_symbol)
            f_sub = f_df[f_df["date"] == cur_date]
            if f_sub.empty:
                continue

            f_close = float(f_sub["close"].iloc[0])
            if not np.isfinite(f_close):
                # §7.4 #2: 非有限收盘价 = 该合约当日无可用数据，与「该合约无当日行」
                # 同类跳过；否则 basis=NaN 会经 polyfit 产出 NaN term_slope 落湖。
                logger.warning(
                    f"跳过非有限收盘价合约 {contract.clean_symbol} @ {cur_date.date()}"
                )
                continue
            f_settle = float(f_sub["settle"].iloc[0]) if "settle" in f_sub.columns else f_close
            f_vol = int(f_sub["volume"].iloc[0])
            f_hold = int(f_sub["hold"].iloc[0])

            # ACT/365 自然日 DTE 计算
            dte = max((contract.expiry_date - cur_date).days, 0)
            basis = f_close - spot_close
            basis_rate_pct = (basis / spot_close) * 100.0 if spot_close > 0 else 0.0

            # ACT/365 年化贴水率: ((F - S) / S) * (365 / max(dte, 1))
            annualized_carry = (
                (basis / spot_close) * (365.0 / max(dte, 1)) if spot_close > 0 else 0.0
            )

            c_label = month_labels[idx] if idx < len(month_labels) else f"term_{idx+1}"

            item = {
                "symbol": contract.clean_symbol,
                "contract_month": c_label,
                "futures_close": f_close,
                "futures_settle": f_settle,
                "dte": dte,
                "basis": basis,
                "basis_rate_pct": basis_rate_pct,
                "annualized_carry": annualized_carry,
                "open_interest": f_hold,
                "volume": f_vol,
            }
            contracts_data.append(item)
            dtes.append(dte / 365.0)
            bases.append(basis)

            if contract.clean_symbol == dominant_sym:
                dominant_basis = basis
                dominant_carry = annualized_carry

        # 计算期限结构斜率 S_term = d(Basis) / dT
        term_slope = 0.0
        if len(dtes) >= 2:
            try:
                # 拟合 Basis = intercept + slope * (DTE/365)
                slope, _ = np.polyfit(dtes, bases, 1)
                # §7.4 #2: polyfit 对退化/非有限输入不保证抛异常（可返回 NaN），
                # 故 try/except 之外还需显式有限性检查，保证落湖的 term_slope 恒有限。
                term_slope = float(slope) if np.isfinite(slope) else 0.0
            except Exception:
                term_slope = 0.0

        return {
            "date": cur_date,
            "underlying": underlying,
            "spot_close": spot_close,
            "dominant_symbol": dominant_sym or "",
            "dominant_basis": dominant_basis,
            "dominant_carry": dominant_carry,
            "term_slope": term_slope,
            "contracts": contracts_data,
        }

    # =========================================================================
    # 3. MLSI (Multi-Level Spread Indicator) 动态对冲防线
    # =========================================================================

    def compute_mlsi_hedge_ratio(
        self,
        underlying: str,
        portfolio_beta: float,
        date: pd.Timestamp,
    ) -> Tuple[float, Dict[str, float]]:
        """
        基于中金所高频动态基差曲面湖与 MLSI (Multi-Level Spread Indicator)
        计算动态对冲防线比率 beta* = beta * phi(MLSI) 及展期最优目标权重。
        
        设计机理：
        1. 监控主力合约 ACT/365 年化贴水率 Carry 及期限斜率 S_term；
        2. 极度深贴水（Carry < -20%）：市场处于流动性挤兑，空头移仓磨损巨大，
           触发动态防御调降对冲比例 (phi in [0.75, 1.0])；
        3. 升水或平水态（Carry > 0%）：空头享受展期正收益，适度强化对冲 (phi in [1.0, 1.15])；
        4. 正常贴水态（Carry in [-12%, -4%]）：维持标称对冲 (phi = 1.0)；
        5. 最优目标权重：优先将持仓向年化贴水损耗最小（或升水最高）的合约倾斜。
        """
        surface = self.get_dynamic_basis_surface(underlying, date)
        dom_carry = surface["dominant_carry"]
        term_slope = surface["term_slope"]
        contracts = surface["contracts"]

        # phi(MLSI) 动态系数 (结合主力年化贴水率与期限结构斜率)
        # term_slope < -150 表示远月贴水剧烈加深 (远月结构性折价严重)
        slope_adj = -0.05 if term_slope < -150.0 else (0.03 if term_slope > 50.0 else 0.0)

        if dom_carry < -0.25:
            # 深贴水惩罚函数：平滑下调至最低 0.75
            phi = max(0.75, 1.0 + (dom_carry + 0.12) * 1.5 + slope_adj)
        elif dom_carry > 0.02:
            # 升水激励函数：最高提升至 1.15
            phi = min(1.15, 1.0 + dom_carry * 1.5 + slope_adj)
        else:
            phi = max(0.75, min(1.15, 1.0 + slope_adj))

        adjusted_beta = float(portfolio_beta * phi)

        # 展期合约权重优化: 根据 annualized_carry 对 short hedger 的收益排序
        # short hedger 收益率 = -Carry (即贴水越浅/升水越高越有利)
        target_weights: Dict[str, float] = {}
        if contracts:
            # 挑选最优合约与次优合约进行分层权重分配
            sorted_contracts = sorted(
                contracts, key=lambda c: c["annualized_carry"], reverse=True
            )
            if len(sorted_contracts) == 1:
                target_weights[sorted_contracts[0]["symbol"]] = 1.0
            else:
                # 70% 权重配置于最优到期合约，30% 配置于主力/次优合约保持流动性
                target_weights[sorted_contracts[0]["symbol"]] = 0.70
                target_weights[sorted_contracts[1]["symbol"]] = 0.30

        return adjusted_beta, target_weights

    # =========================================================================
    # 4. 基差曲面湖批量构建与持久化
    # =========================================================================

    def build_basis_surface_lake(
        self,
        start_date: Optional[str] = "2024-01-01",
        end_date: Optional[str] = "2026-09-23",
        underlyings: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        全量提取并构建动态基差曲面日表，原子落盘至
        data/lake/futures/basis_surface/basis_surface_daily.parquet
        """
        if underlyings is None:
            underlyings = list(UNDERLYING_MAP.keys())

        cal = self._get_trade_calendar()
        if cal is None:
            raise RuntimeError("缺失交易日历，无法构建曲面")

        mask = pd.Series(True, index=cal.index)
        if start_date:
            mask &= cal["trade_date"] >= start_date
        if end_date:
            mask &= cal["trade_date"] <= end_date

        trade_dates = cal[mask]["trade_date"].tolist()
        surface_rows: List[Dict[str, Any]] = []

        logger.info(
            f"开始构建动态基差曲面湖 ({len(trade_dates)} 天 x {len(underlyings)} 标的)..."
        )

        for u in underlyings:
            for d_str in trade_dates:
                dt = pd.Timestamp(d_str)
                try:
                    s = self.get_dynamic_basis_surface(u, dt)
                    for c in s["contracts"]:
                        surface_rows.append({
                            "date": dt,
                            "underlying": u,
                            "contract_symbol": c["symbol"],
                            "contract_month": c["contract_month"],
                            "spot_close": s["spot_close"],
                            "futures_close": c["futures_close"],
                            "futures_settle": c["futures_settle"],
                            "dte": c["dte"],
                            "basis": c["basis"],
                            "basis_rate_pct": c["basis_rate_pct"],
                            "annualized_carry": c["annualized_carry"],
                            "open_interest": c["open_interest"],
                            "volume": c["volume"],
                            "term_slope": s["term_slope"],
                        })
                except Exception:
                    continue

        if not surface_rows:
            logger.warning("未生成任何基差曲面记录")
            return pd.DataFrame()

        df_surface = pd.DataFrame(surface_rows).sort_values(
            ["date", "underlying", "dte"]
        ).reset_index(drop=True)

        out_dir = self.lake_dir / "basis_surface"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "basis_surface_daily.parquet"
        tmp_file = out_file.with_suffix(".parquet.tmp")
        df_surface.to_parquet(tmp_file, index=False, compression="snappy")
        os.replace(tmp_file, out_file)

        logger.info(
            f"动态基差曲面湖落盘成功: {len(df_surface):,} 行 "
            f"({df_surface['date'].min().date()} -> {df_surface['date'].max().date()}) "
            f"=> {out_file}"
        )
        return df_surface
