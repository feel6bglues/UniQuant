from typing import Dict, Any
import pandas as pd
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

REGIME_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

class RegimeAnalysisEngine:
    """市场状态(Regime)检测引擎"""
    
    def __init__(self, orchestrator):
        """
        Args:
            orchestrator: AnalysisService instance that provides shared context
        """
        self.orchestrator = orchestrator

    def run_regime_detection(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run regime detection for market state analysis

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            Regime detection results
        """
        try:
            from ...brain.regime.regime_detector import RegimeDetector
            regime_detector = RegimeDetector()
            regime_result = regime_detector.detect(symbol)
            return {
                "symbol": symbol,
                "status": "success",
                "regime": regime_result.get("regime", "NORMAL"),
            }
        except REGIME_RECOVERABLE_ERRORS as e:
            logger.warning(f"RegimeDetector 分析失败: {e}")
            return {
                "symbol": symbol,
                "status": "failed",
                "regime": "NORMAL",
                "error": str(e),
            }

    def _run_regime_detection(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """
        运行 RegimeDetector 分析（带市场级缓存）
        
        市场状态是全市场共享的，只需计算一次
        """
        try:
            # 使用沪深300作为市场基准
            market_benchmark = "000300.SH" 
            
            # 检查内存缓存
            regime = self.orchestrator._market_cache.get('regime')
            if regime is not None:
                data_pack['regime'] = {'status': 'success', 'regime': regime}
                return
                
            # 检查磁盘缓存
            cache_key = self.orchestrator._generate_cache_key("market_regime", date=self.orchestrator._market_cache_date)
            cached_result = self.orchestrator._get_cached_result(cache_key, use_disk=True)
            
            if cached_result is not None:
                self.orchestrator._market_cache['regime'] = cached_result
                data_pack['regime'] = {'status': 'success', 'regime': cached_result}
                return
                
            self.orchestrator._market_cache['regime'] = "NORMAL"
                
            # 执行实际计算
            logger.info("执行全市场状态计算...")
            result = self.run_regime_detection(market_benchmark)
            
            if result.get("status") == "success":
                # 保存到缓存
                self.orchestrator._market_cache['regime'] = result.get("regime", "NORMAL")
                data_pack['regime'] = result
                
                # 设置磁盘缓存
                self.orchestrator._set_cached_result(
                    cache_key, 
                    result.get("regime", "NORMAL"), 
                    use_disk=True, 
                    ttl=24*3600  # 缓存一天
                )
        except REGIME_RECOVERABLE_ERRORS as e:
            logger.error(f"RegimeDetector integration failed: {e}")
