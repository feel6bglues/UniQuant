import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import pandas as pd
from ...shared.logger_factory import get_logger
from ...shared.error_handling import handle_errors, validate_inputs
from ...shared.exceptions import AnalysisError, ServiceError

logger = get_logger(__name__)

REPORT_GENERATION_ERRORS = (
    AttributeError,
    KeyError,
    OSError,
    TypeError,
    ValueError,
)

class ReportGeneratorEngine:
    """研究报告生成与读取引擎"""
    
    def __init__(self, orchestrator=None, data_service=None):
        """
        Args:
            orchestrator: AnalysisService instance that provides shared context
            data_service: DataService instance (optional, for compatibility with factory)
        """
        self.orchestrator = orchestrator
        self._data_service = data_service

    def _generate_analysis_report(
        self, ticker: str, data_pack: Dict[str, Any],
        decision_result: Dict[str, Any], filepath: Optional[str]
    ) -> bool:
        """生成分析报告"""
        try:
            stock_name = self.orchestrator.data_service.get_stock_name(ticker)
            
            indicators = data_pack.get("indicators", {})
            if not indicators:
                indicators = {
                    "ma20": data_pack.get("ma20", 0.0),
                    "ma60": data_pack.get("ma60", 0.0),
                    "ema20": data_pack.get("ema20", 0.0),
                    "rsi": data_pack.get("rsi", 50.0),
                    "macd": data_pack.get("macd", 0.0),
                    "macd_signal": data_pack.get("macd_signal", 0.0),
                    "macd_hist": data_pack.get("macd_hist", 0.0),
                    "atr": data_pack.get("atr", 0.0),
                    "bollinger_upper": data_pack.get("bollinger_upper", 0.0),
                    "bollinger_middle": data_pack.get("bollinger_middle", 0.0),
                    "bollinger_lower": data_pack.get("bollinger_lower", 0.0),
                    "vol_ratio": data_pack.get("vol_ratio", 1.0),
                    "market_entropy": data_pack.get("market_entropy", 0.0),
                    "turnover_z": data_pack.get("turnover_z", 0.0),
                }
            
            context = {
                "symbol": ticker,
                "name": stock_name,
                "decision_packet": decision_result,
                "current_price": data_pack["stock"].iloc[-1]["close"],
                "indicators": indicators,
            }

            if filepath:
                context["result_file"] = filepath

            if self.orchestrator.reporter:
                return self.orchestrator.reporter.generate_research_report(context)
            else:
                logger.warning("Reporter not available, skipping report generation")
                return True
        except REPORT_GENERATION_ERRORS as e:
            logger.error(f"{ticker} 报告生成失败: {e}")
            return False

    def list_reports(self) -> List[Dict[str, Any]]:
        """List all generated research reports."""
        reports = []
        for p in self.orchestrator.report_root.rglob("*.md"):
            stat = p.stat()
            reports.append(
                {
                    "Filename": p.name,
                    "Created": pd.to_datetime(stat.st_mtime, unit="s").strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "Size (KB)": round(stat.st_size / 1024, 2),
                    "Path": str(p),
                }
            )
        return reports

    def read_report(self, file_path: str) -> str:
        """
        Read content of a report for preview.
        """
        try:
            # Validate input
            if not file_path or not isinstance(file_path, str):
                raise ValueError("File path must be a non-empty string")

            p = Path(file_path)
            if p.exists():
                return p.read_text(encoding="utf-8")
            return "Report not found."
        except ValueError as e:
            logger.error(f"Invalid input for read_report: {e}")
            return f"Error reading report: {e}"
        except (IOError, OSError) as e:
            logger.error(f"File system error reading report: {e}")
            return f"Error reading report: {e}"
        except (TypeError, UnicodeError, ValueError) as e:
            logger.critical(f"Unexpected error reading report: {e}", exc_info=True)
            return f"Error reading report: {e}"

    @handle_errors(
        AnalysisError,
        ServiceError,
        ValueError,
        TypeError,
        default_return=False,
        log_level=logging.ERROR,
        error_type="report_generation",
    )
    @validate_inputs(
        ticker=lambda x: isinstance(x, str) and bool(x.strip()),
    )
    def generate_report(self, ticker: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        生成个股研究报告
        """
        return self.orchestrator.analyze_ticker(ticker)

    def generate_reports_from_results(
        self,
        symbols: Optional[List[str]] = None,
        date: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, bool]:
        """
        从计算结果批量生成报告（快速模式）

        此方法跳过计算阶段，直接从已保存的结果文件生成报告。
        适用于：
        - 计算已完成，只需重新生成报告
        - 报告模板更新后批量重新生成

        Args:
            symbols: 股票代码列表，None 表示全部
            date: 日期过滤，格式 'YYYYMMDD'
            force: 是否强制重新生成（即使报告已存在）

        Returns:
            股票代码 -> 是否成功的映射
        """
        try:
            from ...hands.results_manager import ResultsManager

            manager = ResultsManager()
            results = manager.generate_reports_from_results(
                symbols=symbols, date=date, force=force
            )

            success_count = sum(1 for v in results.values() if v)
            logger.info(f"批量生成报告完成: {success_count}/{len(results)} 成功")

            return results
        except ImportError as e:
            logger.error(f"导入 ResultsManager 失败: {e}")
            return {}
        except REPORT_GENERATION_ERRORS as e:
            logger.error(f"批量生成报告失败: {e}")
            return {}

    def list_available_results(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出可用的计算结果文件

        Args:
            symbol: 股票代码过滤

        Returns:
            结果文件信息列表
        """
        try:
            from ...hands.results_manager import ResultsManager

            manager = ResultsManager()
            return manager.list_results(symbol=symbol)
        except ImportError as e:
            logger.error(f"导入 ResultsManager 失败: {e}")
            return []
        except REPORT_GENERATION_ERRORS as e:
            logger.error(f"列出结果文件失败: {e}")
            return []
