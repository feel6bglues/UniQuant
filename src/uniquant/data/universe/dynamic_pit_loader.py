#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态点在时 (Dynamic PIT) 高性能全截面数据装载与关联引擎
=============================================================================
核心职责:
1. 利用 DuckDB 向量化多线程读取 data/lake/financial/*.parquet 中全市场 5,211+ 标的财报数据;
2. 利用 Polars 内存引擎实现超高速跨截面因果法医指标衍生计算 (CFO造血率、CIP在建工程占比、ROE、应收占比);
3. 动态提取跨年度点在时 (PIT) 调仓日真实行情与 60 日残差动量基准;
4. 毫秒级完成全市场 4,643+ 标的在各调仓截面的三步法纯因果筛选 (Q4资本抽水机过滤 -> Z_CNMM排雷 -> Alpha动量评分)。
=============================================================================
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import duckdb
import polars as pl
import pandas as pd

from uniquant.shared.constants.path import PROJECT_ROOT
from uniquant.shared.logger_factory import get_logger

logger = get_logger("data.universe.dynamic_pit_loader")


class CrossSectionalPITDataLoader:
    """
    全市场点在时跨截面数据加速装载与关联引擎 (DuckDB + Polars 架构)
    """

    def __init__(
        self,
        lake_root: Optional[Path | str] = None,
        db_connection: Optional[duckdb.DuckDBPyConnection] = None,
    ):
        self.lake_root = Path(lake_root or PROJECT_ROOT / "data" / "lake")
        self.quotes_dir = self.lake_root / "quotes" / "daily"
        self.financial_dir = self.lake_root / "financial"
        self.panel_100_path = PROJECT_ROOT / "data" / "backtest" / "large_sample_100_panel_processed.csv"
        self.bal_100_path = PROJECT_ROOT / "data" / "backtest" / "large_sample_100_balance_raw.csv"

        self.con = db_connection or duckdb.connect()
        self._df_financial: Optional[pl.DataFrame] = None

    def _normalize_symbol(self, raw_code: str) -> str:
        """归一化股票代码格式为 XXXXXX.SH / XXXXXX.SZ"""
        s = str(raw_code).strip()
        if "." in s:
            parts = s.split(".")
            if parts[0].lower() in ["sh", "sz"]:
                return f"{parts[1].zfill(6)}.{parts[0].upper()}"
            elif parts[1].lower() in ["sh", "sz"]:
                return f"{parts[0].zfill(6)}.{parts[1].upper()}"
            return f"{parts[0].zfill(6)}.{parts[1].upper()}"
        code_digits = "".join(ch for ch in s if ch.isdigit()).zfill(6)
        if code_digits.startswith("920") or code_digits.startswith(("4", "8")):
            return f"{code_digits}.BJ"
        elif code_digits.startswith(("6", "9")):
            return f"{code_digits}.SH"
        elif code_digits.startswith(("0", "2", "3")):
            return f"{code_digits}.SZ"
        return f"{code_digits}.SH"

    def load_all_financial_reports(self, force_reload: bool = False) -> pl.DataFrame:
        """
        利用 DuckDB 扫描 5,211+ 只标的年度财报，并通过 Polars 构建全景衍生指标
        """
        if self._df_financial is not None and not force_reload:
            return self._df_financial

        t0 = time.time()
        logger.info("[DuckDB] 启动全市场 5,211 份财报 Parquet 向量化极速并行扫描...")

        fin_glob = str(self.financial_dir / "*.parquet")
        query = f"""
            SELECT 
                code,
                SPLIT_PART(code, '.', 1) as stock_code,
                CAST(report_date // 10000 AS INTEGER) as year,
                report_date,
                COALESCE("经营活动产生的现金流量净额", 0.0) / 100000000.0 as cfo_yi,
                COALESCE("资产总计", 1.0) / 100000000.0 as total_assets_yi,
                COALESCE("在建工程", 0.0) / 100000000.0 as cip_yi,
                COALESCE("其他应收款", 0.0) / 100000000.0 as oth_rec_yi,
                COALESCE("归属于母公司所有者的净利润", "净利润", 0.0) / 100000000.0 as net_profit_yi,
                COALESCE("所有者权益（或股东权益）合计", 1.0) / 100000000.0 as equity_yi
            FROM read_parquet('{fin_glob}')
            WHERE report_date % 10000 = 1231
        """
        arrow_table = self.con.execute(query).arrow()
        df_lake = pl.from_arrow(arrow_table)
        t1 = time.time()
        logger.info(f"[DuckDB] 财报数据湖读取完毕 (耗时: {t1 - t0:.2f}s, 提取记录: {len(df_lake)} 条)")

        # 关联补充 2000-2015 历史代表性面板财报 (保障 2000-2025 全周期连续性)
        df_hist = self._load_pre_2016_panel_fundamentals()
        if df_hist is not None and len(df_hist) > 0:
            df_merged = pl.concat([df_hist, df_lake], how="diagonal_relaxed").unique(
                subset=["code", "year"], keep="last"
            )
        else:
            df_merged = df_lake

        # Polars 极速向量化衍生指标计算
        df_fin = df_merged.with_columns([
            (pl.col("cip_yi") / pl.col("total_assets_yi").clip(lower_bound=0.01)).alias("cip_ratio"),
            (pl.col("oth_rec_yi") / pl.col("total_assets_yi").clip(lower_bound=0.01)).alias("oth_rec_ratio"),
            (pl.col("net_profit_yi") / pl.col("equity_yi").clip(lower_bound=0.01)).alias("roe"),
            (pl.col("cfo_yi") / pl.col("total_assets_yi").clip(lower_bound=0.01)).alias("cfo_ratio"),
        ])
        df_fin = df_fin.with_columns(pl.col("cfo_ratio").alias("cfo_proxy"))

        t2 = time.time()
        logger.info(f"[Polars] 全景因果财务法医指标构建完成 (衍生耗时: {t2 - t1:.4f}s, 汇总总行数: {len(df_fin)})")
        self._df_financial = df_fin
        return self._df_financial

    def _load_pre_2016_panel_fundamentals(self) -> Optional[pl.DataFrame]:
        """加载 2000-2015 代表性面板数据以无缝衔接前期历史回测"""
        if not self.panel_100_path.exists():
            return None
        try:
            df_p = pd.read_csv(self.panel_100_path)
            df_p["stock_code"] = df_p["stock_code"].astype(str).str.zfill(6)
            df_p["code"] = df_p["stock_code"].apply(self._normalize_symbol)
            df_p["report_date"] = pd.to_datetime(df_p["report_date"])
            df_p["year"] = df_p["report_date"].dt.year
            df_p["month"] = df_p["report_date"].dt.month

            ann = df_p[(df_p["month"] == 12) & (df_p["year"] < 2016)].copy()
            if ann.empty:
                return None

            records = []
            for _, r in ann.iterrows():
                records.append({
                    "code": str(r["code"]),
                    "stock_code": str(r["stock_code"]),
                    "year": int(r["year"]),
                    "report_date": int(r["year"] * 10000 + 1231),
                    "cfo_yi": float(r.get("cfo_yi", 0.0) or 0.0),
                    "total_assets_yi": float(r.get("total_assets_yi", 1.0) or 1.0),
                    "cip_yi": float(r.get("cip_yi", 0.0) or 0.0),
                    "oth_rec_yi": float(r.get("oth_rec_yi", 0.0) or 0.0),
                    "net_profit_yi": float(r.get("net_profit_yi", 0.0) or 0.0),
                    "equity_yi": float(r.get("equity_yi", 1.0) or 1.0),
                })
            return pl.DataFrame(records)
        except (IOError, ValueError, KeyError) as e:
            logger.warning("加载历史面板财报补充失败: %s", e)
            return None

    def load_cross_section_prices(self, dates: List[str]) -> pl.DataFrame:
        """
        利用 DuckDB 极速提取指定调仓日和动量对比日的价格截面
        """
        t0 = time.time()
        logger.info(f"[DuckDB] 启动对 {len(dates)} 个关键截面日的日频 Parquet 向量化过滤扫描...")

        quotes_glob = str(self.quotes_dir / "*.parquet")
        dates_sql = ", ".join([f"'{d}'" for d in sorted(list(set(dates)))])
        query = f"""
            SELECT 
                code,
                SPLIT_PART(code, '.', 1) as stock_code,
                CAST(date AS VARCHAR)[:10] as trade_date,
                close,
                open,
                amount,
                volume
            FROM read_parquet('{quotes_glob}')
            WHERE CAST(date AS VARCHAR)[:10] IN ({dates_sql})
        """
        arrow_table = self.con.execute(query).arrow()
        df_prices = pl.from_arrow(arrow_table)
        t1 = time.time()
        logger.info(
            f"[DuckDB] 行情截面扫描完成 (耗时: {t1 - t0:.2f}s, 提取跨截面行情记录: {len(df_prices)} 条)"
        )
        return df_prices

    def screen_and_score_cross_section(
        self,
        as_of_date: str,
        fiscal_year: int,
        eligible_symbols: List[str],
        df_prices: pl.DataFrame,
        prior_60_date: str,
        next_rebalance_date: Optional[str] = None,
        top_n: int = 40,
    ) -> Dict[str, Any]:
        """
        在单一调仓截面上执行 Polars 极速纯因果 Alpha 筛选与组合构建
        """
        t_start = time.time()

        # 1. 过滤当前截面基础财报数据 (fiscal_year)
        df_fin = self.load_all_financial_reports()
        fin_sub = df_fin.filter(
            (pl.col("year") == fiscal_year) & (pl.col("code").is_in(eligible_symbols))
        )

        # 2. 提取 as_of_date (p0) 与 prior_60_date (p_prior) 行情
        p0_sub = df_prices.filter(pl.col("trade_date") == as_of_date).select([
            pl.col("code"),
            pl.col("close").alias("p0"),
            pl.col("amount").alias("amount_p0"),
        ])
        p_prior_sub = df_prices.filter(pl.col("trade_date") == prior_60_date).select([
            pl.col("code"),
            pl.col("close").alias("p_prior"),
        ])

        # 3. Polars 跨表极速关联
        joined = (
            fin_sub.join(p0_sub, on="code", how="inner")
            .join(p_prior_sub, on="code", how="left")
            .filter(pl.col("p0") > 0)
        )

        # 计算 60 日残差动量
        joined = joined.with_columns([
            ((pl.col("p0") / pl.col("p_prior").clip(lower_bound=0.01)) - 1.0)
            .fill_null(0.0)
            .alias("mom_60")
        ])

        total_eligible_in_lake = len(joined)
        if total_eligible_in_lake == 0:
            return {"selected_symbols": [], "diagnostics": {"eligible": 0}}

        # 4. 策略 3 (CDE-EX): 剔除第四象限 Q4 资本抽水机
        s3 = joined.filter(
            ~(
                (pl.col("roe") < -0.02)
                | ((pl.col("net_profit_yi") < 0) & (pl.col("cip_ratio") > 0.12))
            )
        )
        s3_count = len(s3)

        # 5. 策略 6 (CNMM-QAR): Z_CNMM 复合排雷 (CIP 异动 Z-Score + 亏损标记前 25% 截断)
        s6 = self._apply_z_cnmm_filter(s3)
        s6_safe_count = len(s6)

        # 6. 标准化截面因果 Alpha 打分 (0.5 * Mom_Z + 0.5 * CFO_Z)
        s6_scored = self._calculate_causal_alpha_scores(s6)

        # 7. 排序并优选前 Top N
        s6_sorted = s6_scored.sort("alpha_score", descending=True)
        final_top = min(top_n, max(10, int(len(s6_sorted) * 0.6)))
        selected_df = s6_sorted.head(final_top)
        selected_symbols = selected_df["code"].to_list()

        # 8. 若提供了下期调仓日，计算持有期实际回报率
        period_rets: Dict[str, float] = {}
        if next_rebalance_date:
            p1_sub = df_prices.filter(pl.col("trade_date") == next_rebalance_date).select([
                pl.col("code"),
                pl.col("close").alias("p1"),
            ])
            eval_df = joined.join(p1_sub, on="code", how="left").with_columns([
                ((pl.col("p1") / pl.col("p0")) - 1.0).alias("ret")
            ])
            for row in eval_df.iter_rows(named=True):
                code = row["code"]
                ret_val = row["ret"]
                period_rets[code] = float(ret_val) if ret_val is not None else -1.0

        t_end = time.time()
        diagnostics = {
            "as_of_date": as_of_date,
            "fiscal_year": fiscal_year,
            "eligible_pit_candidates": len(eligible_symbols),
            "joined_with_lake_quotes": total_eligible_in_lake,
            "s3_cde_survivors": s3_count,
            "s6_cnmm_safe_candidates": s6_safe_count,
            "selected_portfolio_size": len(selected_symbols),
            "screening_latency_ms": round((t_end - t_start) * 1000.0, 2),
        }

        return {
            "selected_symbols": selected_symbols,
            "selected_df": selected_df.to_pandas(),
            "period_returns": period_rets,
            "diagnostics": diagnostics,
        }

    def _apply_z_cnmm_filter(self, df_s3: pl.DataFrame) -> pl.DataFrame:
        """应用 Z_CNMM 复合排雷过滤器"""
        if len(df_s3) < 10:
            return df_s3

        mean_cip = float(df_s3["cip_ratio"].mean() or 0.0)
        std_cip = float(df_s3["cip_ratio"].std() or 1.0)
        std_cip = std_cip if std_cip > 1e-8 else 1.0

        df_calc = df_s3.with_columns([
            ((pl.col("cip_ratio") - mean_cip) / std_cip).alias("cip_z"),
            (pl.col("net_profit_yi") < 0).cast(pl.Float64).alias("loss_flag"),
        ])
        df_calc = df_calc.with_columns([
            (0.6 * pl.col("cip_z") + 0.4 * pl.col("loss_flag")).alias("z_score")
        ])

        cut_75 = float(df_calc["z_score"].quantile(0.75) or 0.0)
        return df_calc.filter(pl.col("z_score") <= cut_75)

    def _calculate_causal_alpha_scores(self, df_cand: pl.DataFrame) -> pl.DataFrame:
        """截面因果标准化 Alpha 打分"""
        if len(df_cand) == 0:
            return df_cand

        m_mean = float(df_cand["mom_60"].mean() or 0.0)
        m_std = float(df_cand["mom_60"].std() or 1.0)
        m_std = m_std if m_std > 1e-8 else 1.0

        cfo_mean = float(df_cand["cfo_proxy"].mean() or 0.0)
        cfo_std = float(df_cand["cfo_proxy"].std() or 1.0)
        cfo_std = cfo_std if cfo_std > 1e-8 else 1.0

        return df_cand.with_columns([
            ((pl.col("mom_60") - m_mean) / m_std).alias("mom_z"),
            ((pl.col("cfo_proxy") - cfo_mean) / cfo_std).alias("cfo_z"),
        ]).with_columns([
            (0.5 * pl.col("mom_z") + 0.5 * pl.col("cfo_z")).alias("alpha_score")
        ])
