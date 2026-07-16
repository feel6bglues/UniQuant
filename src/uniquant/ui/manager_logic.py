import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from ..services.analysis_service_v2 import AnalysisService
from ..shared.kill_switch import get_kill_switch
from ..shared.time_provider import get_time_provider

# Import New Services
from ..services.data_service import DataService
from ..services.portfolio_service import PortfolioService
from ..shared.constants import NetworkConstants, ResultsConstants, TimeWindows
from ..shared.logger_factory import get_logger
from .manager_portfolio_analytics_service import ManagerPortfolioAnalyticsService
from .manager_report_service import ManagerReportService

logger = get_logger("AssetManager")


@dataclass
class FSMStateInfo:
    """FSM状态信息数据类"""
    current_state: str
    state_desc: str
    transition_reason: str
    ma_status: str
    timestamp: datetime.datetime


@dataclass
class Bi:
    dt: datetime.datetime
    price: float
    direction: int


class AssetManager:
    """
    Facade for Alpha-Tactician Pro Logic.
    Delegates to DataService, AnalysisService, and PortfolioService.
    Preserves public API for Dashboard compatibility.
    """

    def __init__(self):
        # Initialize Services
        self.data_service = DataService()
        self.analysis_service = AnalysisService(data_service=self.data_service)
        self.portfolio_service = PortfolioService()
        self.portfolio_analytics_service = ManagerPortfolioAnalyticsService(self)
        self.report_service = ManagerReportService(read_report=self.read_report)

        # Backward compatibility properties (proxies)

    # --- Properties Proxies ---
    @property
    def stock_map(self) -> Dict[str, str]:
        return self.data_service.stock_map

    @property
    def etf_list(self) -> List[str]:
        return self.data_service.etf_list

    @property
    def lake_root(self) -> str:
        return self.data_service.lake_root

    @property
    def report_root(self) -> Any:
        from ..shared.config_loader import get_config
        return get_config().ROOT_DIR / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.REPORTS_DIR_NAME

    # --- Compatibility Properties for V9.0 ---
    @property
    def data_svc(self) -> DataService:
        return self.data_service

    # --- Data Methods ---
    def refresh_stock_map(self) -> None:
        self.data_service.refresh_stock_map()

    def get_stock_name(self, symbol: str) -> str:
        return self.data_service.get_stock_name(symbol)

    def list_data_files(self) -> List[str]:
        return self.data_service.list_data_files()

    def delete_file(self, file_path: str) -> bool:
        return self.data_service.delete_file(file_path)

    def download_stock(self, symbol: str) -> bool:
        return self.data_service.download_stock(symbol)

    def download_etf_sector_data(self) -> bool:
        return self.data_service.download_etf_sector_data()

    def get_real_kline_data(
        self, ticker: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        # Delegate to DataService
        return self.data_service.get_real_kline_data(ticker, start_date, end_date)

    def query_data_lake(self, sql_condition: str) -> pd.DataFrame:
        """Scan local parquet lake via Service and enrich with metrics (Facade Logic)."""
        try:
            # 1. Raw Data Scan
            df_raw = self.data_service.query_lake(sql_condition)
            if df_raw.empty:
                return pd.DataFrame()

            return self.enrich_lake_data(df_raw)
        except (ValueError, TypeError) as e:
            logger.error("Invalid input or data format: %s", e)
            return pd.DataFrame()
        except (RuntimeError, IOError, KeyError, NotImplementedError) as e:
            logger.critical("Unexpected error in query_data_lake: %s", e, exc_info=True)
            return pd.DataFrame()

    # --- Analysis Methods ---
    def analyze_macro_health(self, mock: bool = True) -> Dict[str, Any]:
        return self.analysis_service.analyze_macro_health(mock)

    def get_structural_risks(self) -> Dict[str, float]:
        return self.portfolio_service.get_structural_risks()

    def get_macro_returns(self, window: int = TimeWindows.MACRO_WINDOW) -> pd.Series:
        return self.analysis_service.macro_engine.get_macro_returns(window=window)

    def scan_etfs(self) -> pd.DataFrame:
        try:
            etfs = self.data_service.etf_list
            if not etfs:
                return pd.DataFrame()
            etf_data = []
            for etf in etfs:
                df = self.data_service.get_real_kline_data(etf, "20240101", "20241231")
                if df is not None and not df.empty:
                    etf_data.append({"code": etf, "close": df.iloc[-1]["close"], "volume": df.iloc[-1]["volume"], "date": str(df.iloc[-1]["date"])})
            return pd.DataFrame(etf_data)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
            logger.error(f"ETF扫描失败: {e}")
            return pd.DataFrame()

    def enrich_lake_data(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        if df_raw is None or df_raw.empty:
            return pd.DataFrame()
        df = df_raw.copy()
        import numpy as np
        if "code" not in df.columns and "symbol" in df.columns:
            df["code"] = df["symbol"]
        if "code" in df.columns:
            df["name"] = df["code"].apply(lambda c: self.data_service.get_stock_name(c))
        else:
            df["name"] = "未知"
        if "close" in df.columns and "open" in df.columns:
            df["signal"] = np.where(df["close"] > df["open"], "BUY", "WAIT")
        else:
            df["signal"] = "UNKNOWN"
        if "pct_change" in df.columns:
            df["strength"] = (df["pct_change"] / 100.0).round(4)
        elif "close" in df.columns and "open" in df.columns:
            df["strength"] = ((df["close"] - df["open"]) / df["open"].replace(0, np.nan)).round(4)
        else:
            df["strength"] = 0.0
        if "close" in df.columns and "high" in df.columns:
            df["czsc_stat"] = np.where(df["close"] > df["high"] * 0.9, "3rd_BUY", "None")
        else:
            df["czsc_stat"] = "None"
        required = ["code", "name", "signal", "strength", "czsc_stat", "close", "volume", "date"]
        available = [c for c in required if c in df.columns]
        if not available:
            return pd.DataFrame()
        final = df[available]
        rename = {"code": "Code", "name": "Name", "signal": "Signal", "strength": "Strength", "czsc_stat": "CZSC", "close": "Price", "volume": "Volume", "date": "Date"}
        final_rename = {k: v for k, v in rename.items() if k in final.columns}
        return final.rename(columns=final_rename)

    def _get_report_engine(self):
        if hasattr(self.analysis_service, '_factory') and self.analysis_service._factory is not None:
            return self.analysis_service._factory.report
        return None

    def list_reports(self) -> List[Dict[str, Any]]:
        engine = self._get_report_engine()
        if engine:
            return engine.list_reports()
        return []

    def read_report(self, file_path: str) -> str:
        engine = self._get_report_engine()
        if engine:
            return engine.read_report(file_path=file_path)
        return ""

    def generate_report(self, ticker: str, data: Dict[str, Any] = None) -> bool:
        engine = self._get_report_engine()
        if engine:
            return engine.generate_report(ticker=ticker, data=data)
        return False

    # --- Portfolio Methods ---
    def calculate_position_size(
        self,
        price: float,
        stop_loss: float,
        risk_pct: float,
        capital: float,
        market: str = "CN",
        czsc_bottom: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self.portfolio_service.calculate_position_size(
            price, stop_loss, risk_pct, capital, market, czsc_bottom
        )

    def get_portfolio(self) -> pd.DataFrame:
        return self.portfolio_service.get_portfolio()

    def add_position(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        shares: int,
    ) -> None:
        self.portfolio_service.add_position(
            symbol, entry_price, current_price, stop_loss, shares
        )

    def remove_position(self, symbol: str) -> None:
        self.portfolio_service.remove_position(symbol)

    # --- V9.0 New Methods ---
    def get_macro_environment(self) -> Dict[str, Any]:
        """获取宏观环境数据"""
        try:
            # 尝试获取结构风险数据
            structural_risks = self.get_structural_risks()

            # 尝试获取宏观健康数据（带超时保护）
            macro_health = self._fetch_macro_health_safe()

            # 构建符合V9.0标准的返回结构
            return {
                "structural_risks": structural_risks,
                "market_regime": macro_health.get("regime", "未知"),
                "ntf_signal": macro_health.get("ntf_signal", "中性"),
                "summary_text": macro_health.get("summary", "宏观环境分析完成"),
            }
        except (RuntimeError, IOError, KeyError) as e:
            logger.critical("获取宏观环境失败: %s", e, exc_info=True)
            return self._get_default_macro_env()

    def _fetch_macro_health_safe(self) -> Dict[str, Any]:
        """安全获取宏观健康数据（带超时和异常处理）"""
        default_health = {
            "regime": "NORMAL",
            "ntf_signal": "中性",
            "summary": "宏观环境分析完成",
        }

        try:
            import time

            start_time = time.time()

            macro_health = self.analyze_macro_health(mock=True)

            if time.time() - start_time > NetworkConstants.SHORT_TIMEOUT:
                raise TimeoutError("宏观数据获取超时")

            return macro_health

        except (TimeoutError, ValueError, TypeError) as e:
            logger.warning("获取宏观健康数据异常 (%s): %s", type(e).__name__, e)
            return default_health
        except (RuntimeError, IOError, KeyError) as e:
            logger.warning("获取宏观健康数据失败: %s", e)
            return default_health

    def _get_default_macro_env(self) -> Dict[str, Any]:
        """获取默认宏观环境数据"""
        return {
            "structural_risks": {},
            "market_regime": "未知",
            "ntf_signal": "中性",
            "summary_text": "宏观环境分析失败",
        }

    def run_analysis(self, ticker: str) -> bool:
        """运行个股分析"""
        try:
            # 调用现有的generate_report方法
            return self.generate_report(ticker)
        except (ValueError, TypeError) as e:
            logger.error("Invalid input or data format: %s", e)
            return False
        except (RuntimeError, IOError, KeyError) as e:
            logger.critical("Unexpected error in run_analysis: %s", e, exc_info=True)
            return False

    # --- FSM State Methods ---
    def get_fsm_state(self, ticker: str) -> Optional[FSMStateInfo]:
        """
        获取指定股票的FSM状态信息

        Args:
            ticker: 股票代码

        Returns:
            FSMStateInfo对象，包含当前状态、状态描述、转换原因等信息
        """
        try:
            from ...brain.fsm import FSM

            # 获取股票数据
            end_date = get_time_provider().now().strftime("%Y-%m-%d")
            start_date = (get_time_provider().now() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
            df = self.get_real_kline_data(ticker, start_date, end_date)

            if df is None or df.empty:
                logger.warning("无法获取 %s 的数据用于FSM状态分析", ticker)
                return None

            # 创建FSM实例并推断状态
            fsm = FSM()
            state_result = fsm.infer_state(df)

            return FSMStateInfo(
                current_state=state_result.get("state_name", "IDLE"),
                state_desc=state_result.get("state_desc", ""),
                transition_reason=state_result.get("transition_reason", ""),
                ma_status=state_result.get("ma_status", "N/A"),
                timestamp=get_time_provider().now()
            )

        except (ValueError, TypeError) as e:
            logger.error("FSM状态分析输入错误 (%s): %s", ticker, e)
            return None
        except (RuntimeError, IOError, KeyError) as e:
            logger.error("FSM状态分析失败 (%s): %s", ticker, e)
            return None
        except Exception as e:
            logger.critical("FSM状态分析异常 (%s): %s", ticker, e, exc_info=True)
            return None

    def get_fsm_next_states(self, current_state: str) -> List[str]:
        """
        获取从当前状态可能的下一个状态

        Args:
            current_state: 当前FSM状态

        Returns:
            可能的下一个状态列表
        """

        # 定义状态转换图
        transitions = {
            "IDLE": ["SIGNAL"],
            "SIGNAL": ["PROBE", "IDLE"],
            "PROBE": ["MONITOR", "EXIT"],
            "MONITOR": ["PYRAMID", "EXIT"],
            "PYRAMID": ["MONITOR", "EXIT"],
            "EXIT": ["IDLE", "SIGNAL"],
            "CIRCUIT_BREAK": ["IDLE"],
        }

        return transitions.get(current_state, ["IDLE"])

    # --- Scan Pipeline Methods ---
    def run_market_scan(
        self,
        scan_mode: str = "quick",
        holding_period: int = 5,
        max_stocks: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        运行全市场扫描

        Args:
            scan_mode: 扫描模式 (quick/fast/full)
            holding_period: 持仓周期 (1/5/10/20天)
            max_stocks: 最大扫描股票数 (None表示全部)

        Returns:
            扫描结果字典，包含Top/Bottom榜单、IC/IR分析、技术信号等
        """
        try:
            from ...services.scan_service import ScanPipeline, ScanConfig

            # 根据扫描模式配置参数
            config_map = {
                "quick": {"top_n": 20, "bottom_n": 20, "min_data_points": 30},
                "fast": {"top_n": 50, "bottom_n": 50, "min_data_points": 60},
                "full": {"top_n": 100, "bottom_n": 100, "min_data_points": 120},
            }

            scan_params = config_map.get(scan_mode, config_map["fast"])

            config = ScanConfig(
                top_n=scan_params["top_n"],
                bottom_n=scan_params["bottom_n"],
                min_data_points=scan_params["min_data_points"],
                holding_periods=[holding_period],
            )

            pipeline = ScanPipeline(config=config)

            # 获取股票列表
            symbols = list(self.stock_map.keys())
            if max_stocks and len(symbols) > max_stocks:
                symbols = symbols[:max_stocks]

            logger.info("开始全市场扫描，模式: %s, 股票数: %d", scan_mode, len(symbols))

            # 执行扫描
            result = pipeline.run(
                output_dir=f"./{ResultsConstants.HANDS_DIR_NAME}/{ResultsConstants.REPORTS_DIR_NAME}",
                symbols=symbols
            )

            # 提取关键结果
            scan_result = {
                "status": result.get("status", "error"),
                "duration_seconds": result.get("duration_seconds", 0),
                "stocks_scanned": result.get("stocks_scanned", 0),
                "records_processed": result.get("records_processed", 0),
                "top_stocks": self._extract_top_stocks(pipeline),
                "bottom_stocks": self._extract_bottom_stocks(pipeline),
                "ic_ir_analysis": self._extract_ic_ir_analysis(pipeline),
                "tech_signals": self._extract_tech_signals(pipeline),
                "report_files": result.get("report_files", {}),
            }

            return scan_result

        except (ValueError, TypeError) as e:
            logger.error("市场扫描输入错误: %s", e)
            return {"status": "error", "message": str(e)}
        except (RuntimeError, IOError, KeyError) as e:
            logger.error("市场扫描执行失败: %s", e)
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.critical("市场扫描异常: %s", e, exc_info=True)
            return {"status": "error", "message": str(e)}

    def _extract_top_stocks(self, pipeline) -> pd.DataFrame:
        """从pipeline提取Top股票"""
        try:
            if hasattr(pipeline, 'screener') and hasattr(pipeline.screener, 'top_stocks'):
                return pipeline.screener.top_stocks
            return pd.DataFrame()
        except Exception as e:
            logger.warning("提取Top股票失败: %s", e)
            return pd.DataFrame()

    def _extract_bottom_stocks(self, pipeline) -> pd.DataFrame:
        """从pipeline提取Bottom股票"""
        try:
            if hasattr(pipeline, 'screener') and hasattr(pipeline.screener, 'bottom_stocks'):
                return pipeline.screener.bottom_stocks
            return pd.DataFrame()
        except Exception as e:
            logger.warning("提取Bottom股票失败: %s", e)
            return pd.DataFrame()

    def _extract_ic_ir_analysis(self, pipeline) -> Dict[str, Any]:
        """从pipeline提取IC/IR分析结果"""
        try:
            if hasattr(pipeline, 'factor_analyzer') and hasattr(pipeline.factor_analyzer, 'results'):
                return pipeline.factor_analyzer.results
            return {}
        except Exception as e:
            logger.warning("提取IC/IR分析失败: %s", e)
            return {}

    def _extract_tech_signals(self, pipeline) -> pd.DataFrame:
        """从pipeline提取技术信号"""
        try:
            if hasattr(pipeline, 'screener') and hasattr(pipeline.screener, 'tech_signals'):
                return pipeline.screener.tech_signals
            return pd.DataFrame()
        except Exception as e:
            logger.warning("提取技术信号失败: %s", e)
            return pd.DataFrame()

    # --- Risk Management Methods ---
    def calculate_portfolio_risk_metrics(
        self,
        symbols: List[str],
        lookback_days: int = 252
    ) -> Dict[str, Any]:
        return self.portfolio_analytics_service.calculate_portfolio_risk_metrics(
            symbols, lookback_days
        )

    def optimize_portfolio(
        self,
        symbols: List[str],
        method: str = "risk_parity",
        lookback_days: int = 252
    ) -> Dict[str, Any]:
        return self.portfolio_analytics_service.optimize_portfolio(
            symbols, method, lookback_days
        )

    def run_stress_test(
        self,
        symbols: List[str],
        scenarios: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        return self.portfolio_analytics_service.run_stress_test(symbols, scenarios)

    # --- Research Report Enhancement Methods ---
    def get_report_html_preview(self, file_path: str) -> str:
        return self.report_service.get_report_html_preview(file_path)

    def export_report_to_pdf(self, file_path: str, output_path: Optional[str] = None) -> str:
        return self.report_service.export_report_to_pdf(file_path, output_path)

    def is_trading_enabled(self) -> bool:
        try:
            from ..shared.config_loader import get_config
            return get_config().get("execution.trading_enabled", True)
        except Exception:
            return True

    def stop_trading(self, reason: str = "manual_override") -> None:
        get_kill_switch().kill(reason)
        from ..shared.config_loader import get_config
        get_config().set("execution.trading_enabled", False)
        get_config().set("execution.kill_switch_reason", reason)
        logger.warning("TRADING STOPPED via kill switch: %s", reason)

    def resume_trading(self) -> None:
        get_kill_switch().reset()
        from ..shared.config_loader import get_config
        get_config().set("execution.trading_enabled", True)
        get_config().set("execution.kill_switch_reason", "")
        logger.info("Trading resumed after kill switch reset")

    def compare_reports(self, file_path1: str, file_path2: str) -> Dict[str, Any]:
        return self.report_service.compare_reports(file_path1, file_path2)

    def get_report_metadata(self, file_path: str) -> Dict[str, Any]:
        return self.report_service.get_report_metadata(file_path)
