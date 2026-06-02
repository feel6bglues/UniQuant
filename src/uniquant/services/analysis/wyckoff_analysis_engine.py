from typing import Dict, Any, Optional
import pandas as pd

from ...shared.logger_factory import get_logger
from ...shared.constants import IndicatorThresholds

logger = get_logger(__name__)

WYCKOFF_RECOVERABLE_ERRORS = (
    AttributeError, ImportError, KeyError, ModuleNotFoundError,
    OSError, RuntimeError, TypeError, ValueError,
)


class WyckoffAnalysisEngine:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def run_wyckoff_analysis(self, symbol: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        try:
            cache_key = self.orchestrator._generate_cache_key("wyckoff_analysis", symbol=symbol)

            if df is None:
                cached_result = self.orchestrator._get_cached_result(cache_key, use_disk=True)
                if cached_result is not None:
                    return cached_result

            if df is None:
                df = self.orchestrator.data_service.lake.read_data(
                    symbol, data_type="stock", market="cn"
                )
                if df is None or df.empty:
                    return {"error": "数据不足", "status": "failed"}

            df = self.orchestrator._optimize_dataframe(df)
            df = self.orchestrator._sample_data(
                df, max_rows=IndicatorThresholds.SAMPLE_MAX_ROWS_WYCKOFF
            )

            try:
                from ...brain.wyckoff.engine import WyckoffEngine
                wyckoff_engine = WyckoffEngine()

                result = wyckoff_engine.analyze(df)

                result = {
                    "symbol": symbol,
                    "status": "success",
                    "phase": result.get("phase", "unknown"),
                    "confidence": result.get("confidence", 0.0),
                    "accumulation_score": result.get("accumulation_score", 0.0),
                    "distribution_score": result.get("distribution_score", 0.0),
                    "spring_detected": result.get("spring_detected", False),
                    "utad_detected": result.get("utad_detected", False),
                    "lps_detected": result.get("lps_detected", False),
                    "sow_detected": result.get("sow_detected", False),
                    "summary": f"Wyckoff分析完成，当前阶段: {result.get('phase', 'unknown')}",
                }

                result = self.orchestrator.ensure_precision_consistency(result)

                if df is None:
                    cache_key = self.orchestrator._generate_cache_key("wyckoff_analysis", symbol=symbol)
                    self.orchestrator._set_cached_result(
                        cache_key, result, use_disk=True,
                        ttl=IndicatorThresholds.CACHE_TTL_2HOURS,
                    )

                return result
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import WyckoffEngine: {e}")
                return self._fallback_wyckoff_analysis(symbol, df)
            except WYCKOFF_RECOVERABLE_ERRORS as e:
                logger.error(f"Wyckoff engine failed: {e}")
                return self._fallback_wyckoff_analysis(symbol, df)
        except WYCKOFF_RECOVERABLE_ERRORS as e:
            logger.error(f"Wyckoff analysis failed for {symbol}: {e}")
            return {"error": str(e), "status": "failed"}

    def _fallback_wyckoff_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        try:
            if "close" not in df.columns or "volume" not in df.columns:
                return {
                    "symbol": symbol, "status": "success",
                    "phase": "unknown", "confidence": 0.0,
                    "summary": "数据不足，无法进行Wyckoff分析",
                }

            prices = df["close"]
            volume = df["volume"]

            volume_sma = volume.rolling(window=20).mean()
            volume_ratio = (volume / volume_sma).fillna(1.0)

            price_sma20 = prices.rolling(window=20).mean()
            price_position = (prices - price_sma20) / price_sma20

            recent_vol_ratio = volume_ratio.iloc[-min(5, len(volume_ratio)):].mean()
            recent_price_pos = price_position.iloc[-1]

            is_accumulation = recent_vol_ratio > 1.2 and recent_price_pos < 0.05
            is_distribution = recent_vol_ratio > 1.2 and recent_price_pos > 0.05

            if is_accumulation:
                phase = "accumulation"
                confidence = min(recent_vol_ratio * 0.5, 0.9)
            elif is_distribution:
                phase = "distribution"
                confidence = min(recent_vol_ratio * 0.5, 0.9)
            else:
                phase = "markup" if recent_price_pos > 0.05 else "markdown"
                confidence = 0.3

            return {
                "symbol": symbol, "status": "success",
                "phase": phase, "confidence": confidence,
                "accumulation_score": recent_vol_ratio if is_accumulation else 0.0,
                "distribution_score": recent_vol_ratio if is_distribution else 0.0,
                "spring_detected": False, "utad_detected": False,
                "lps_detected": False, "sow_detected": False,
                "summary": f"使用基本成交量分析方法进行Wyckoff阶段识别，当前阶段: {phase}",
            }
        except WYCKOFF_RECOVERABLE_ERRORS as e:
            logger.error(f"Fallback Wyckoff analysis failed: {e}")
            return {
                "symbol": symbol, "status": "success",
                "phase": "unknown", "confidence": 0.0,
                "summary": "Wyckoff分析失败，使用默认结果",
            }

    def detect_spring(self, df: pd.DataFrame) -> Dict[str, Any]:
        if "close" not in df.columns or "low" not in df.columns or "volume" not in df.columns:
            return {"spring_detected": False, "confidence": 0.0}

        recent = df.tail(30)
        if len(recent) < 20:
            return {"spring_detected": False, "confidence": 0.0}

        support_level = recent["low"].iloc[:15].min()
        recent_lows = recent["low"].iloc[15:]
        spring_candidates = recent_lows[recent_lows < support_level * 0.98]

        if not spring_candidates.empty:
            spring_idx = spring_candidates.index[0]
            spring_volume = recent.loc[spring_idx, "volume"]
            avg_volume = recent["volume"].mean()
            volume_confirmation = spring_volume > avg_volume * 1.5
            if volume_confirmation:
                return {"spring_detected": True, "confidence": 0.7, "index": spring_idx}
        return {"spring_detected": False, "confidence": 0.0}

    def detect_utad(self, df: pd.DataFrame) -> Dict[str, Any]:
        if "close" not in df.columns or "volume" not in df.columns:
            return {"utad_detected": False, "confidence": 0.0}

        recent = df.tail(40)
        if len(recent) < 30:
            return {"utad_detected": False, "confidence": 0.0}

        price_up = recent["close"].pct_change(5).iloc[-1] > 0.02
        vol_ratio = recent["volume"].tail(5).mean() / recent["volume"].head(30).mean()
        price_range = (recent["high"].tail(5).max() - recent["low"].tail(5).min()) / recent["close"].mean()

        utad_signal = price_up and vol_ratio < 0.8 and price_range < 0.03
        if utad_signal:
            return {"utad_detected": True, "confidence": 0.65}
        return {"utad_detected": False, "confidence": 0.0}

    def detect_lps(self, df: pd.DataFrame) -> Dict[str, Any]:
        if "close" not in df.columns or "volume" not in df.columns:
            return {"lps_detected": False, "confidence": 0.0}

        recent = df.tail(30)
        if len(recent) < 20:
            return {"lps_detected": False, "confidence": 0.0}

        price_down = recent["close"].pct_change(5).iloc[-1] < -0.02
        vol_ratio = recent["volume"].tail(5).mean() / recent["volume"].head(20).mean()
        narrowing_range = (recent["high"].tail(5).max() - recent["low"].tail(5).min()) < \
                          (recent["high"].head(5).max() - recent["low"].head(5).min()) * 0.7

        lps_signal = price_down and vol_ratio < 0.7 and narrowing_range
        if lps_signal:
            return {"lps_detected": True, "confidence": 0.6}
        return {"lps_detected": False, "confidence": 0.0}

    def detect_sow(self, df: pd.DataFrame) -> Dict[str, Any]:
        if "close" not in df.columns or "volume" not in df.columns:
            return {"sow_detected": False, "confidence": 0.0}

        recent = df.tail(20)
        if len(recent) < 10:
            return {"sow_detected": False, "confidence": 0.0}

        price_spike = recent["close"].pct_change().abs().max() > 0.03
        vol_spike = (recent["volume"] / recent["volume"].shift(1)).max() > 2.0

        if price_spike and vol_spike:
            return {"sow_detected": True, "confidence": 0.55}
        return {"sow_detected": False, "confidence": 0.0}
