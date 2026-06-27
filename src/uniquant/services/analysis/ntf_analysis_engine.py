from typing import Dict, Any
import pandas as pd
from ...shared.interfaces import NtfOutput
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

NTF_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

class NtfAnalysisEngine:
    """国家队干预(NTF)检测引擎"""
    
    def __init__(self, orchestrator):
        """
        Args:
            orchestrator: AnalysisService instance that provides shared context
        """
        self.orchestrator = orchestrator

    def run_ntf_detection(self, symbol: str, df: pd.DataFrame = None) -> "NtfOutput":
        """
        Run NTF (National Team Fund) detection for policy intervention analysis

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            NTF detection results
        """
        try:
            from ...brain.ntf.ntf_engine import NTFEngine
            ntf_engine = NTFEngine()
            ntf_result = ntf_engine.detect_intervention(symbol)
            return NtfOutput(
                side=str(ntf_result.get("side", "NONE")),
                intensity=float(ntf_result.get("intensity", 0.0)),
            )
        except NTF_RECOVERABLE_ERRORS as e:
            logger.warning(f"NTFEngine 分析失败: {e}")
            return NtfOutput(side="NONE")

    def _run_ntf_detection(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """
        运行 NTFEngine 分析（带市场级缓存）
        
        国家队干预信号是全市场共享的，只需计算一次
        """
        try:
            # 使用国家队监测ETF (例如：上证50或沪深300 ETF)
            ntf_proxy = "510300.SH" 
            
            # 检查内存缓存
            ntf_signals = self.orchestrator._market_cache.get('ntf_signals')
            if ntf_signals is not None:
                data_pack['ntf'] = ntf_signals
                return
                
            # 检查磁盘缓存
            cache_key = self.orchestrator._generate_cache_key("market_ntf", date=self.orchestrator._market_cache_date)
            cached_result = self.orchestrator._get_cached_result(cache_key, use_disk=True)
            
            if cached_result is not None:
                self.orchestrator._market_cache['ntf_signals'] = cached_result
                data_pack['ntf'] = cached_result
                return
                
            self.orchestrator._market_cache['ntf_signals'] = None
                
            # 执行实际计算
            logger.info("执行国家队干预监测计算...")
            result = self.run_ntf_detection(ntf_proxy)
            
            ntf_data = {
                "side": result.side,
                "intensity": result.intensity,
            }
            self.orchestrator._market_cache['ntf_signals'] = ntf_data
            data_pack['ntf'] = ntf_data

            self.orchestrator._set_cached_result(
                cache_key, 
                ntf_data, 
                use_disk=True, 
                ttl=24*3600,  
            )
        except NTF_RECOVERABLE_ERRORS as e:
            logger.error(f"NTFEngine integration failed: {e}")
