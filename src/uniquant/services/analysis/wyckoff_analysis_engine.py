from typing import Dict, Any, Optional
import pandas as pd

from ...shared.logger_factory import get_logger
from ...shared.constants import IndicatorThresholds
from ...shared.interfaces import WyckoffOutput

logger = get_logger(__name__)

WYCKOFF_RECOVERABLE_ERRORS = (
    AttributeError, ImportError, KeyError, ModuleNotFoundError,
    OSError, RuntimeError, TypeError, ValueError,
)

_CONFIDENCE_TO_FLOAT = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}


class WyckoffAnalysisEngine:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def _extract_from_report(self, result: Any, price: float) -> WyckoffOutput:
        phase = "unknown"
        confidence = 0.0
        spring = False
        utad = False
        rr_ratio = 0.0
        bypassed = False

        if hasattr(result, "structure") and result.structure is not None:
            p = getattr(result.structure, "phase", None)
            if p is not None:
                phase = str(p.value) if hasattr(p, "value") else str(p)

        if hasattr(result, "signal") and result.signal is not None:
            sig = result.signal
            sig_type = getattr(sig, "signal_type", "")
            if "spring" in str(sig_type).lower():
                spring = True
            if "utad" in str(sig_type).lower():
                utad = True
            conf = getattr(sig, "confidence", None)
            if conf is not None:
                conf_str = str(conf.value) if hasattr(conf, "value") else str(conf)
                confidence = _CONFIDENCE_TO_FLOAT.get(conf_str, 0.3)

        if hasattr(result, "risk_reward") and result.risk_reward is not None:
            rr = getattr(result.risk_reward, "reward_risk_ratio", 0.0)
            rr_ratio = float(rr) if rr else 0.0

        if hasattr(result, "trading_plan") and result.trading_plan is not None:
            tp = result.trading_plan
            tp_conf = getattr(tp, "confidence", None)
            if tp_conf is not None:
                conf_str = str(tp_conf.value) if hasattr(tp_conf, "value") else str(tp_conf)
                confidence = _CONFIDENCE_TO_FLOAT.get(conf_str, confidence)

        pnf_phase_hint = "neutral"
        pnf_breakout = False
        pnf_count_target = 0.0
        regime_phase: Optional[str] = None
        vshape_detected = False

        if hasattr(result, "pnf_analysis") and result.pnf_analysis is not None:
            pnf = result.pnf_analysis
            if isinstance(pnf, dict):
                pnf_phase_hint = str(pnf.get("phase_hint", "neutral"))
                pnf_breakout = bool(pnf.get("breakout", False))
                pnf_count_target = float(pnf.get("count_target", 0.0))
            elif isinstance(pnf, str):
                pnf_phase_hint = pnf

        if hasattr(result, "regime_phase") and result.regime_phase is not None:
            regime_phase = str(result.regime_phase)

        if hasattr(result, "vshape_detected") and result.vshape_detected:
            vshape_detected = bool(result.vshape_detected)

        adjustment_status = "unknown"
        if hasattr(result, "adjustment_status"):
            adjustment_status = str(result.adjustment_status)

        structural_score = 0.0
        if hasattr(result, "structural_score"):
            structural_score = float(result.structural_score)

        relative_strength = None
        if hasattr(result, "relative_strength") and result.relative_strength:
            relative_strength = str(result.relative_strength)

        return WyckoffOutput(
            phase=phase, confidence=confidence,
            spring=spring, utad=utad,
            price=price, rr_ratio=rr_ratio,
            bypassed=bypassed,
            pnf_phase_hint=pnf_phase_hint,
            pnf_breakout=pnf_breakout,
            pnf_count_target=pnf_count_target,
            regime_phase=regime_phase,
            vshape_detected=vshape_detected,
            adjustment_status=adjustment_status,
            structural_score=structural_score,
            relative_strength=relative_strength,
        )

    def run_wyckoff_analysis(self, symbol: str, df: Optional[pd.DataFrame] = None) -> "WyckoffOutput":
        try:
            cache_key = self.orchestrator._generate_cache_key("wyckoff_analysis", symbol=symbol)

            if df is None:
                cached_result = self.orchestrator._get_cached_result(cache_key, use_disk=True)
                if cached_result is not None:
                    if isinstance(cached_result, dict):
                        return WyckoffOutput.from_dict(cached_result)
                    return cached_result

            if df is None:
                df = self.orchestrator.data_service.lake.read_data(
                    symbol, data_type="stock", market="cn"
                )
                if df is None or df.empty:
                    return WyckoffOutput(phase="unknown")

            df = self.orchestrator._optimize_dataframe(df)
            df = self.orchestrator._sample_data(
                df, max_rows=IndicatorThresholds.SAMPLE_MAX_ROWS_WYCKOFF
            )

            try:
                from ...brain.wyckoff.engine import WyckoffEngine
                wyckoff_engine = WyckoffEngine()

                result = wyckoff_engine.analyze(df, multi_timeframe=True)
                price = float(df["close"].iloc[-1]) if "close" in df.columns else 0.0

                return self._extract_from_report(result, price)
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import WyckoffEngine: {e}")
                return self._fallback_wyckoff_analysis(symbol, df)
            except WYCKOFF_RECOVERABLE_ERRORS as e:
                logger.error(f"Wyckoff engine failed: {e}")
                return self._fallback_wyckoff_analysis(symbol, df)
        except WYCKOFF_RECOVERABLE_ERRORS as e:
            logger.error(f"Wyckoff analysis failed for {symbol}: {e}")
            return WyckoffOutput(phase="unknown")

    def _fallback_wyckoff_analysis(self, symbol: str, df: pd.DataFrame) -> "WyckoffOutput":
        try:
            if "close" not in df.columns or "volume" not in df.columns:
                return WyckoffOutput(phase="unknown")

            prices = df["close"]
            volume = df["volume"]
            price = float(prices.iloc[-1])

            volume_sma = volume.shift(1).rolling(window=20).mean()
            volume_ratio = (volume / volume_sma).fillna(1.0)

            price_sma20 = prices.shift(1).rolling(window=20).mean()
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

            return WyckoffOutput(
                phase=phase,
                confidence=confidence,
                spring=False,
                utad=False,
                price=price,
            )
        except WYCKOFF_RECOVERABLE_ERRORS as e:
            logger.error(f"Fallback Wyckoff analysis failed: {e}")
            return WyckoffOutput(phase="unknown")

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

        price_up = recent["close"].shift(1).pct_change(5).iloc[-1] > 0.02
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

        price_down = recent["close"].shift(1).pct_change(5).iloc[-1] < -0.02
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
