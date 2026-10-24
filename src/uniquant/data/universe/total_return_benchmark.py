"""
全收益基准对齐引擎与股息剪刀差消除适配器 (Total Return Benchmark Adapter)
=============================================================================
核心职责:
1. 解决传统 A 股多空对冲回测中“多头享受股票分红、空头基准扣除分红”导致的股息剪刀差 (Dividend Leakage);
2. 消费沪深 300 价格指数 (000300.SH)，结合历年股息率生成标准全收益指数 (000300TR.SH);
3. 消费上证 50 价格指数 (000016.SH)，生成上证 50 全收益指数 (000016TR.SH);
4. 严格按照 UniQuant 数据湖 9 列物理 Parquet 契约持久化落盘至 data/lake/quotes/index/;
5. 提供对账方法量化股息剪刀差对长期 CAGR 的影响。
=============================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd

from uniquant.shared.constants.path import PROJECT_ROOT
from uniquant.shared.logger_factory import get_logger

logger = get_logger("data.universe.total_return_benchmark")


class TotalReturnBenchmarkAdapter:
    """
    全收益指数基准生成与分红剪刀差适配器
    """

    DEFAULT_ANNUAL_DIVIDEND_YIELD = 0.0215  # 沪深300历史平均年化股息率 ~2.15%

    def __init__(
        self,
        index_dir: Optional[str | Path] = None,
        annual_div_yield: float = DEFAULT_ANNUAL_DIVIDEND_YIELD,
    ):
        self.index_dir = Path(index_dir) if index_dir else PROJECT_ROOT / "data" / "lake" / "quotes" / "index"
        self.annual_div_yield = float(annual_div_yield)
        self.daily_div_yield = self.annual_div_yield / 252.0

    def generate_total_return_series(
        self,
        base_symbol: str = "000300.SH",
        tr_symbol: Optional[str] = None,
        persist: bool = True,
    ) -> pd.DataFrame:
        """
        从价格指数生成全收益指数日线数据 (分红再投资)
        
        Args:
            base_symbol: 原始价格指数文件名 (如 000300.SH)
            tr_symbol: 目标全收益指数文件名 (如 000300TR.SH)
            persist: 是否落盘至 data/lake/quotes/index/
            
        Returns:
            pd.DataFrame: 包含 9 列标准 Parquet 契约的全收益指数时序
        """
        in_path = self.index_dir / f"{base_symbol}.parquet"
        if not in_path.exists():
            raise FileNotFoundError(f"基准价格指数文件不存在: {in_path}")

        df_base = pd.read_parquet(in_path)
        if df_base.empty or "close" not in df_base.columns:
            raise ValueError(f"价格指数数据格式异常: {in_path}")

        df_base = df_base.sort_values("date").reset_index(drop=True)
        # 计算价格收益率
        pr_rets = df_base["close"].pct_change().fillna(0.0)
        
        # 全收益率 = 价格收益率 + 每日分红收益 (Reinvestment Rate)
        tr_rets = pr_rets + self.daily_div_yield
        # 首日不计息
        tr_rets.iloc[0] = 0.0

        # 全收益净值序列 (以首日 close 为基数)
        base_p0 = float(df_base["close"].iloc[0])
        tr_close = base_p0 * (1.0 + tr_rets).cumprod()

        # 按比例缩放 open, high, low
        ratio = tr_close / df_base["close"]
        tr_open = df_base["open"] * ratio
        tr_high = df_base["high"] * ratio
        tr_low = df_base["low"] * ratio

        target_sym = tr_symbol or base_symbol.replace(".SH", "TR.SH").replace(".SZ", "TR.SZ")
        df_tr = pd.DataFrame({
            "date": pd.to_datetime(df_base["date"]),
            "open": tr_open.round(2),
            "high": tr_high.round(2),
            "low": tr_low.round(2),
            "close": tr_close.round(2),
            "amount": df_base["amount"],
            "volume": df_base["volume"],
            "reserved": df_base["reserved"],
            "code": target_sym,
        })

        if persist:
            out_path = self.index_dir / f"{target_sym}.parquet"
            df_tr.to_parquet(out_path, index=False)
            logger.info(f"全收益指数已成功生成并落盘至: {out_path} (共 {len(df_tr)} 行)")

        return df_tr

    def calculate_dividend_leakage_spread(
        self,
        base_symbol: str = "000300.SH",
        tr_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        精算价格指数与全收益指数之间的长期分红剪刀差
        """
        target_sym = tr_symbol or base_symbol.replace(".SH", "TR.SH").replace(".SZ", "TR.SZ")
        p_base = self.index_dir / f"{base_symbol}.parquet"
        p_tr = self.index_dir / f"{target_sym}.parquet"

        if not p_tr.exists():
            df_tr = self.generate_total_return_series(base_symbol=base_symbol, tr_symbol=target_sym, persist=True)
        else:
            df_tr = pd.read_parquet(p_tr)

        df_base = pd.read_parquet(p_base)

        years = (df_base["date"].max() - df_base["date"].min()).days / 365.25
        base_mult = float(df_base["close"].iloc[-1] / df_base["close"].iloc[0])
        tr_mult = float(df_tr["close"].iloc[-1] / df_tr["close"].iloc[0])

        base_cagr = (base_mult ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0
        tr_cagr = (tr_mult ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0
        div_leakage_cagr = tr_cagr - base_cagr

        return {
            "base_symbol": base_symbol,
            "total_return_symbol": target_sym,
            "years": round(years, 2),
            "price_index_cagr_pct": round(base_cagr, 2),
            "total_return_cagr_pct": round(tr_cagr, 2),
            "dividend_leakage_annual_pct": round(div_leakage_cagr, 2),
            "cumulative_wealth_spread_multiplier": round(tr_mult / base_mult, 2),
        }
