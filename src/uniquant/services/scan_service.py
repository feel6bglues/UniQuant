"""
全市场扫描流水线服务
端到端编排：数据加载 → 因子计算 → IC/IR → 合成 → 扫描 → 输出
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from ..shared.time_provider import get_time_provider
from typing import Dict, List, Optional, Any

import pandas as pd

from ..brain.factors.financial_bridge import FinancialFactorBridge
from ..brain.factors.analyzer import FactorAnalyzer
from ..brain.factors.composer import FactorComposer
from ..brain.screener.screener import StockScreener, ScreenerConfig
from ..brain.indicators.indicators import Indicators
from ..data.lake.storage_manager import StorageManager
from ..shared.constants import ResultsConstants
from ..shared.error_handling import handle_errors
from ..shared.logger_factory import get_logger

logger = get_logger("ScanPipeline")

PARQUET_LOAD_ERRORS = (
    ImportError,
    OSError,
    TypeError,
    ValueError,
)


def get_default_scan_output_dir() -> str:
    """返回统一的扫描报告输出目录。"""
    return str(
        Path(".")
        / ResultsConstants.HANDS_DIR_NAME
        / ResultsConstants.REPORTS_DIR_NAME
    )


@dataclass
class ScanConfig:
    """扫描配置
    注意: exclude_delisted 默认为 False，即包含退市股票。
    历史研究和回测必须包含退市股票以消除幸存者偏差，确保点时间精度准确。
    实盘交易时可设为 True 排除已退市股票。
    """
    top_n: int = 50
    bottom_n: int = 50
    min_data_points: int = 60
    holding_periods: List[int] = None
    factor_cols: List[str] = None
    weight_method: str = "ic_weighted"
    lightweight: bool = False
    exclude_delisted: bool = False
    batch_size: int = 500
    financial_subdir: str = "financial"
    max_workers: int = 4
    checkpoint_enabled: bool = False
    checkpoint_dir: Optional[str] = None
    
    def __post_init__(self):
        if self.holding_periods is None:
            self.holding_periods = [1, 5, 20]
        if self.factor_cols is None:
            self.factor_cols = [
                "momentum_20d", "momentum_60d",
                "volatility_20d", "volatility_60d",
                "ma_ratio_5_20", "ma_ratio_10_60",
                "volume_ratio_5_20", "rsi_14",
                "price_position_20d",
                "turnover_momentum_20d",
            ]


class ScanPipeline:
    """
    全市场扫描流水线
    
    功能:
    1. 从 StorageManager 批量加载日线 + 财务 Parquet
    2. 调用 FinancialFactorBridge 计算财务因子
    3. 构建动量/价值/质量/低波动等因子
    4. 调用 FactorAnalyzer 计算 IC/IR
    5. 调用 FactorComposer 生成合成评分
    6. 调用 StockScreener 输出报告
    """
    
    def __init__(
        self,
        data_dir: str = "./data",
        config: Optional[ScanConfig] = None
    ):
        self.config = config or ScanConfig()
        
        self.storage = StorageManager(data_dir)
        self.financial_bridge = FinancialFactorBridge()
        self.factor_analyzer = FactorAnalyzer()
        self.factor_composer = FactorComposer()
        self.screener = StockScreener(ScreenerConfig(
            top_n=self.config.top_n,
            bottom_n=self.config.bottom_n,
            min_data_points=self.config.min_data_points
        ))
        self.indicators = Indicators()
        
        self.daily_data: Dict[str, pd.DataFrame] = {}
        self.financial_data: Dict[str, pd.DataFrame] = {}
        self.combined_df: pd.DataFrame = pd.DataFrame()
        
        cp_dir = self.config.checkpoint_dir
        self._checkpoint_dir = Path(cp_dir) if cp_dir else Path(data_dir) / ".scan_cache"
        self._max_workers = self.config.max_workers
        
        logger.info(f"ScanPipeline initialized with top_n={self.config.top_n}, "
                     f"max_workers={self._max_workers}, "
                     f"checkpoint_enabled={self.config.checkpoint_enabled}")
    
    def _checkpoint_path(self, name: str) -> Path:
        return self._checkpoint_dir / f"{name}.json"

    def _save_checkpoint(self, name: str, data: Any) -> None:
        if not self.config.checkpoint_enabled:
            return
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path(name).write_text(json.dumps(data, ensure_ascii=False))

    def _load_checkpoint(self, name: str) -> Optional[Any]:
        if not self.config.checkpoint_enabled:
            return None
        path = self._checkpoint_path(name)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _clear_checkpoints(self) -> None:
        if self._checkpoint_dir.exists():
            for f in self._checkpoint_dir.glob("*.json"):
                f.unlink()

    def _load_financial_data_batch(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        financial_dir = self.storage.lake_dir / self.config.financial_subdir
        parquet_paths: Dict[str, Path] = {}
        for symbol in symbols:
            fin_path = financial_dir / f"{symbol}.parquet"
            if fin_path.exists():
                parquet_paths[symbol] = fin_path

        if not parquet_paths:
            logger.info("No financial parquet files found")
            return {}

        loaded_symbols: set = set()
        if self.config.checkpoint_enabled:
            cached = self._load_checkpoint("financial_loaded")
            if cached:
                loaded_symbols = set(cached)
                loaded_count = len(loaded_symbols & parquet_paths.keys())
                if loaded_count:
                    logger.info(f"Checkpoint: {loaded_count} financial datasets already loaded, skipping")
                    for sym in list(parquet_paths.keys()):
                        if sym in loaded_symbols:
                            del parquet_paths[sym]

        if not parquet_paths:
            logger.info("All financial data already loaded per checkpoint")
            return self.financial_data

        results: Dict[str, pd.DataFrame] = {}
        logger.info(f"Loading {len(parquet_paths)} financial datasets with {self._max_workers} workers...")
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_sym = {
                executor.submit(pd.read_parquet, str(path)): sym
                for sym, path in parquet_paths.items()
            }
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    results[sym] = future.result()
                except PARQUET_LOAD_ERRORS as e:
                    logger.warning(f"Failed to load financial data for {sym}: {e}")

        logger.info(f"Loaded {len(results)} financial datasets")
        return results

    def load_data(self, symbols: Optional[List[str]] = None) -> None:
        """
        加载日线和财务数据
        
        Args:
            symbols: 股票代码列表 (默认加载全部)
        """
        if symbols is None:
            symbols = self.storage.get_symbols()
        
        if not symbols:
            logger.warning("No symbols found in data lake")
            return
        
        logger.info(f"Loading data for {len(symbols)} symbols...")
        
        self.daily_data = self.storage.batch_read_data(symbols, data_type="daily")
        
        if self.config.lightweight:
            logger.info("Lightweight mode: skipping financial data loading")
        else:
            self.financial_data = self._load_financial_data_batch(symbols)
        
        if self.config.checkpoint_enabled:
            all_loaded = list(self.daily_data.keys())
            self._save_checkpoint("daily_symbols", all_loaded)
            fin_loaded = list(self.financial_data.keys())
            self._save_checkpoint("financial_loaded", fin_loaded)
        
        logger.info(f"Loaded {len(self.daily_data)} daily and {len(self.financial_data)} financial datasets")
    
    def build_factors(self):
        """使用新的 FactorComposer 计算所有因子"""
        logger.info("开始计算所有注册因子...")
        
        # 合并日线数据到 combined_df
        if not self.daily_data:
            logger.error("No daily data loaded")
            return
        
        logger.info(f"合并 {len(self.daily_data)} 个股票的日线数据...")
        dfs = []
        for symbol, df in self.daily_data.items():
            if df.empty:
                continue
            df = df.copy()
            df['code'] = symbol
            dfs.append(df)
        
        if not dfs:
            logger.error("No valid data to combine")
            return
        
        self.combined_df = pd.concat(dfs, ignore_index=True)
        logger.info(f"合并完成，共 {len(self.combined_df)} 条记录")

        if self.financial_data:
            self.combined_df = self._merge_financial_metrics(self.combined_df)
        
        composer = FactorComposer()
        
        # 计算所有因子
        factor_df = composer.compute_all_factors(self.combined_df)
        
        # 合并因子到 combined_df
        if not factor_df.empty:
            self.combined_df = pd.concat([self.combined_df, factor_df], axis=1)
        
        # 保存到 self
        self.factor_df = factor_df
        
        logger.info(f"成功计算 {len(factor_df.columns)} 个因子")

    def _merge_financial_metrics(self, combined_df: pd.DataFrame) -> pd.DataFrame:
        """将财务因子桥接到日线主表（并行合并）"""
        groups = list(combined_df.groupby("code", sort=False))

        if not groups:
            return combined_df

        merged_symbols: set = set()
        if self.config.checkpoint_enabled:
            cached = self._load_checkpoint("merged_symbols")
            if cached:
                merged_symbols = set(cached)

        def merge_one(symbol: str, daily_df: pd.DataFrame) -> Optional[pd.DataFrame]:
            fin_df = self.financial_data.get(symbol)
            if fin_df is None or fin_df.empty:
                return daily_df.copy()
            try:
                merged = self.financial_bridge.process(daily_df.copy(), fin_df.copy(), price_col="close")
                return merged if not merged.empty else daily_df.copy()
            except Exception as e:
                logger.warning(f"Merge failed for {symbol}: {e}")
                return daily_df.copy()

        result_frames: List[pd.DataFrame] = []
        pending_groups = [(s, df) for s, df in groups if s not in merged_symbols]

        if merged_symbols:
            loaded_count = len(merged_symbols)
            logger.info(f"Checkpoint: {loaded_count} symbols already merged, skipping")

        if not pending_groups:
            logger.info("All financial metrics already merged per checkpoint")
            return combined_df

        logger.info(f"Merging financial metrics for {len(pending_groups)} symbols with {self._max_workers} workers...")
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(merge_one, sym, df): sym
                for sym, df in pending_groups
            }
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        result_frames.append(result)
                except Exception as e:
                    logger.warning(f"Unexpected merge error for {sym}: {e}")
                    groups_dict = dict(pending_groups)
                    result_frames.append(groups_dict[sym].copy())

        if merged_symbols:
            for s, df in groups:
                if s in merged_symbols:
                    result_frames.append(df.copy())

        if not result_frames:
            return combined_df

        merged_df = pd.concat(result_frames, ignore_index=True)

        if self.config.checkpoint_enabled:
            all_merged = list(set(s for s, _ in groups))
            self._save_checkpoint("merged_symbols", all_merged)

        logger.info(f"财务因子合并完成，共 {len(merged_df)} 条记录")
        return merged_df
    
    def analyze_factors(self) -> Dict[str, Any]:
        """
        分析因子有效性
        
        Returns:
            因子分析结果
        """
        if self.combined_df.empty:
            logger.error("No combined data. Call build_factors() first.")
            return {}
        
        logger.info(f"Starting analyze_factors with {len(self.combined_df)} records, lightweight={self.config.lightweight}")
        
        available_factors = [
            col for col in self.config.factor_cols
            if col in self.combined_df.columns
        ]
        
        if not available_factors:
            logger.warning("No factor columns available for analysis")
            return {}
        
        if self.config.lightweight:
            logger.info(f"Lightweight mode: skipping IC/IR analysis for {len(available_factors)} factors")
            return {"lightweight_mode": True, "factors": available_factors}
        
        logger.info(f"Analyzing {len(available_factors)} factors...")
        
        ic_results = self.factor_analyzer.compute_ic_ir(
            self.combined_df,
            factor_cols=available_factors,
            holding_periods=self.config.holding_periods
        )
        
        report = self.factor_analyzer.generate_report(ic_results)
        
        logger.info(f"Factor analysis complete: {len(ic_results)} factors analyzed")
        return report
    
    def compose_scores(self) -> pd.DataFrame:
        """
        合成多因子得分
        
        Returns:
            包含 composite_score 的 DataFrame
        """
        if self.combined_df.empty:
            logger.error("No combined data. Call build_factors() first.")
            return pd.DataFrame()
        
        logger.info(f"Starting compose_scores with {len(self.combined_df)} records, lightweight={self.config.lightweight}")
        
        available_factors = [
            col for col in self.config.factor_cols
            if col in self.combined_df.columns
        ]
        
        if not available_factors:
            logger.warning("No factor columns available for composition")
            return pd.DataFrame()
        
        if self.config.lightweight:
            logger.info(f"Lightweight mode: using equal weights for {len(available_factors)} factors")
            weights = {col: 1.0 / len(available_factors) for col in available_factors}
            self.combined_df = self._compute_composite_score(self.combined_df, available_factors, weights)
            logger.info(f"Composed scores with equal weights: {weights}")
            return self.combined_df
        
        ic_results = self.factor_analyzer.results
        
        self.combined_df, weights = self.factor_composer.process(
            self.combined_df,
            factor_cols=available_factors,
            ic_results=ic_results
        )
        
        logger.info(f"Composed scores with weights: {weights}")
        return self.combined_df
    
    def _compute_composite_score(self, df: pd.DataFrame, factor_cols: List[str], weights: Dict[str, float]) -> pd.DataFrame:
        """计算合成得分（轻量模式）"""
        df = df.copy()
        for col in factor_cols:
            if col not in df.columns:
                continue
            rank_col = f"{col}_rank"
            df[rank_col] = df.groupby("date")[col].rank(pct=True, method="average")
        rank_cols = [f"{col}_rank" for col in factor_cols if f"{col}_rank" in df.columns]
        if rank_cols:
            df["composite_score"] = df[rank_cols].mean(axis=1)
        return df
    
    def generate_report(self, output_dir: str = get_default_scan_output_dir()) -> Dict[str, str]:
        """
        生成扫描报告
        
        Args:
            output_dir: 输出目录
            
        Returns:
            生成的文件路径字典
        """
        if self.combined_df.empty:
            logger.error("No combined data. Run the pipeline first.")
            return {}
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = get_time_provider().now().strftime("%Y%m%d_%H%M%S")
        
        top_df, bottom_df = self.screener.generate_top_bottom(self.combined_df)
        
        top_with_tech = self.screener.generate_tech_signals(top_df, self.daily_data)
        bottom_with_tech = self.screener.generate_tech_signals(bottom_df, self.daily_data)
        
        risk_summary = self.screener.generate_market_risk_summary(self.daily_data)
        
        files = {}
        
        top_table = self.screener.format_top_table(top_with_tech)
        top_file = output_path / f"top_stocks_{timestamp}.md"
        with open(top_file, "w", encoding="utf-8") as f:
            f.write(f"# Top {self.config.top_n} Stocks\n\n")
            f.write(f"Generated at: {get_time_provider().now().isoformat()}\n\n")
            f.write(top_table)
        files["top_stocks"] = str(top_file)
        
        bottom_table = self.screener.format_top_table(bottom_with_tech)
        bottom_file = output_path / f"bottom_stocks_{timestamp}.md"
        with open(bottom_file, "w", encoding="utf-8") as f:
            f.write(f"# Bottom {self.config.bottom_n} Stocks\n\n")
            f.write(f"Generated at: {get_time_provider().now().isoformat()}\n\n")
            f.write(bottom_table)
        files["bottom_stocks"] = str(bottom_file)
        
        risk_table = self.screener.format_risk_summary_table(risk_summary)
        risk_file = output_path / f"market_risk_{timestamp}.md"
        with open(risk_file, "w", encoding="utf-8") as f:
            f.write("# Market Risk Summary\n\n")
            f.write(f"Generated at: {get_time_provider().now().isoformat()}\n\n")
            f.write(risk_table)
        files["market_risk"] = str(risk_file)
        
        sector_top_df = self.screener.generate_sector_top(self.combined_df)
        if not sector_top_df.empty:
            sector_file = output_path / f"sector_top_{timestamp}.md"
            with open(sector_file, "w", encoding="utf-8") as f:
                f.write("# Sector Top Stocks\n\n")
                f.write(f"Generated at: {get_time_provider().now().isoformat()}\n\n")
                
                for sector in sector_top_df["sector"].unique() if "sector" in sector_top_df.columns else []:
                    sector_data = sector_top_df[sector_top_df["sector"] == sector]
                    f.write(f"## {sector}\n\n")
                    f.write("| Rank | Code | Score |\n")
                    f.write("|------|------|-------|\n")
                    for row in sector_data.itertuples(index=False):
                        f.write(f"| {getattr(row, '_sector_rank', '')} | {getattr(row, 'code', '')} | {getattr(row, 'composite_score', 0):.4f} |\n")
                    f.write("\n")
            files["sector_top"] = str(sector_file)
        
        factor_report = self.analyze_factors()
        if factor_report:
            factor_file = output_path / f"factor_analysis_{timestamp}.md"
            with open(factor_file, "w", encoding="utf-8") as f:
                f.write("# Factor Analysis Report\n\n")
                f.write(f"Generated at: {get_time_provider().now().isoformat()}\n\n")
                
                if "summary" in factor_report:
                    f.write("## Summary\n\n")
                    for k, v in factor_report["summary"].items():
                        f.write(f"- **{k}**: {v}\n")
                    f.write("\n")
                
                if "by_factor" in factor_report:
                    f.write("## Factor Details\n\n")
                    for factor, details in factor_report["by_factor"].items():
                        f.write(f"### {factor}\n\n")
                        f.write(f"- Best Period: {details.get('best_period', 'N/A')}\n")
                        f.write(f"- Avg IC: {details.get('avg_ic') or 0:.4f}\n")
                        f.write(f"- Avg ICIR: {details.get('avg_icir') or 0:.4f}\n\n")
            files["factor_analysis"] = str(factor_file)
        
        tech_signals_file = output_path / f"tech_signals_top20_{timestamp}.md"
        with open(tech_signals_file, "w", encoding="utf-8") as f:
            f.write("# TOP 20 Technical Signals Report\n\n")
            f.write(f"Generated at: {get_time_provider().now().isoformat()}\n\n")
            f.write("> **独立技术信号扫描表** - 便于人工执行参考\n\n")

            # Cache top 20 to avoid repeated iterations
            top_20 = top_with_tech.head(20)
            top_20_records = top_20.to_dict('records')

            f.write("## MA Signal Summary\n\n")
            f.write("| Code | MA Signal | Trend |\n")
            f.write("|------|-----------|-------|\n")
            for row in top_20_records:
                code = row.get("code", "N/A")
                ma_signal = row.get("ma_signal", "N/A")
                trend = row.get("trend", "N/A")
                f.write(f"| {code} | {ma_signal} | {trend} |\n")
            f.write("\n")

            f.write("## RSI State Summary\n\n")
            f.write("| Code | RSI State | RSI Value |\n")
            f.write("|------|-----------|----------|\n")
            for row in top_20_records:
                code = row.get("code", "N/A")
                rsi_state = row.get("rsi_state", "N/A")
                rsi_val = row.get("rsi_14", 0)
                if isinstance(rsi_val, (int, float)) and not pd.isna(rsi_val):
                    f.write(f"| {code} | {rsi_state} | {rsi_val:.2f} |\n")
                else:
                    f.write(f"| {code} | {rsi_state} | N/A |\n")
            f.write("\n")

            f.write("## MACD Signal Summary\n\n")
            f.write("| Code | MACD Signal | MACD | Signal Line |\n")
            f.write("|------|-------------|------|-------------|\n")
            for row in top_20_records:
                code = row.get("code", "N/A")
                macd_signal = row.get("macd_signal", "N/A")
                macd_val = row.get("macd", 0)
                signal_val = row.get("macd_signal_val", 0)
                if isinstance(macd_val, (int, float)) and not pd.isna(macd_val):
                    f.write(f"| {code} | {macd_signal} | {macd_val:.4f} | {signal_val:.4f} |\n")
                else:
                    f.write(f"| {code} | {macd_signal} | N/A | N/A |\n")
            f.write("\n")

            f.write("## Actionable Signals\n\n")
            f.write("### Potential Buy Candidates\n\n")
            f.write("| Rank | Code | Score | MA Signal | RSI | MACD |\n")
            f.write("|------|------|-------|-----------|-----|------|\n")
            buy_candidates = [
                row for row in top_20_records
                if row.get("ma_signal") in ("金叉", "多头排列")
            ]
            for i, row in enumerate(buy_candidates, 1):
                f.write(f"| {i} | {row.get('code', 'N/A')} | {row.get('composite_score', 0):.2f} | {row.get('ma_signal', 'N/A')} | {row.get('rsi_state', 'N/A')} | {row.get('macd_signal', 'N/A')} |\n")
            f.write("\n")

            f.write("### Risk Alerts\n\n")
            f.write("| Rank | Code | Score | Risk Signal |\n")
            f.write("|------|------|-------|-------------|\n")
            risk_alerts = [
                row for row in top_20_records
                if row.get("rsi_state") == "超买" or row.get("macd_signal") == "死叉"
            ]
            for i, row in enumerate(risk_alerts, 1):
                risk_signal = []
                if row.get("rsi_state") == "超买":
                    risk_signal.append("RSI超买")
                if row.get("macd_signal") == "死叉":
                    risk_signal.append("MACD死叉")
                f.write(f"| {i} | {row.get('code', 'N/A')} | {row.get('composite_score', 0):.2f} | {', '.join(risk_signal)} |\n")
            f.write("\n")
            
        files["tech_signals_top20"] = str(tech_signals_file)
        
        logger.info(f"Generated {len(files)} report files in {output_dir}")
        return files
    
    @handle_errors(ValueError, KeyError, TypeError, RuntimeError, default_return={}, log_level=logging.ERROR)
    def run(self, output_dir: str = get_default_scan_output_dir(), symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        执行完整扫描流水线
        
        Args:
            output_dir: 输出目录
            symbols: 股票代码列表 (默认加载全部)
            
        Returns:
            执行结果字典
        """
        start_time = get_time_provider().now()
        
        logger.info("=" * 60)
        logger.info("Starting Market Scan Pipeline")
        logger.info("=" * 60)
        
        self.load_data(symbols)
        
        self.build_factors()
        
        self.analyze_factors()
        
        self.compose_scores()
        
        files = self.generate_report(output_dir)
        
        end_time = get_time_provider().now()
        duration = (end_time - start_time).total_seconds()
        
        result = {
            "status": "success",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "stocks_scanned": len(self.daily_data),
            "records_processed": len(self.combined_df),
            "report_files": files,
        }
        
        logger.info("=" * 60)
        logger.info(f"Pipeline completed in {duration:.2f} seconds")
        logger.info(f"Scanned {result['stocks_scanned']} stocks, {result['records_processed']} records")
        logger.info("=" * 60)
        
        return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Full Market Scan Service")
    parser.add_argument("--full", action="store_true", help="Run full market scan")
    parser.add_argument("--output", type=str, default=get_default_scan_output_dir(), help="Output directory for reports")
    parser.add_argument("--data-dir", type=str, default="./data", help="Data directory path")
    parser.add_argument("--top-n", type=int, default=50, help="Number of top stocks to report")
    parser.add_argument("--bottom-n", type=int, default=50, help="Number of bottom stocks to report")
    parser.add_argument("--lightweight", type=lambda x: x.lower() == 'true', default=False, help="Skip IC/IR analysis to save memory (default: false)")
    
    args = parser.parse_args()
    
    config = ScanConfig(
        top_n=args.top_n,
        bottom_n=args.bottom_n,
        lightweight=args.lightweight
    )
    
    pipeline = ScanPipeline(data_dir=args.data_dir, config=config)
    result = pipeline.run(output_dir=args.output)
    
    if result["status"] == "success":
        print("\nScan completed successfully!")
        print(f"Duration: {result['duration_seconds']:.2f} seconds")
        print(f"Stocks scanned: {result['stocks_scanned']}")
        print(f"Records processed: {result['records_processed']}")
        print("\nReport files generated:")
        for name, path in result["report_files"].items():
            print(f"  - {name}: {path}")
    else:
        print("\nScan failed!")
        print(f"Error: {result.get('error', 'Unknown error')}")
