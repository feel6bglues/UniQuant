"""Wyckoff event sequence scoring (WSO + WSS).

WSOScorer  —  rule-based score using empirical per-event f6 weights.
WSSScorer  —  statistical score from pre-trained sequence → weight lookup.
WyckoffScorer —  unified scorer that blends WSO and WSS.

Usage:
    from uniquant.brain.wyckoff.sequence import WyckoffScorer

    # WSS mode: load pre-trained lookup
    scorer = WyckoffScorer(wss_lookup={...})
    score, signal = scorer.score_sequence(['SC', 'AR'], has_spring=True)

    # WSO-only mode
    scorer = WyckoffScorer()
    score, signal = scorer.score_sequence(['SOS'])
"""

from typing import Dict, List, Optional, Tuple
import json


class WSOScorer:
    """Wyckoff Score Oscillator — rule-based scoring.

    Empirical weights derived from 22,148 observations × 500 A-share stocks.
    """

    EMA_SPAN: int = 5

    def __init__(self) -> None:
        self._last_score: float = 0.0
        self._is_warm: bool = False

    EVENT_WEIGHTS: Dict[str, float] = {
        'PS':  0.0105,
        'SC':  0.0094,
        'AR':  0.0083,
        'ST':  0.0052,
        'SOS': -0.0137,
        'LPS': 0.0,
        'JAC': -0.0048,
    }

    SEQUENCE_BONUS: Dict[str, float] = {
        'SC>AR':       0.030,
        'PS>SC>AR':    0.028,
        'SC>AR>ST':    0.020,
    }

    SOS_ALONE_PENALTY: float = -0.040
    SPRING_STANDALONE_BOOST: float = 0.025

    BUY_THRESHOLD: float = 0.04
    SELL_THRESHOLD: float = -0.03

    def score_events(
        self,
        event_types: List[str],
        has_spring: bool = False,
        spring_event_count: int = 0,
    ) -> float:
        if not event_types:
            return 0.0

        type_set = set(event_types)
        seq_key = '>'.join(event_types)
        base = sum(self.EVENT_WEIGHTS.get(et, 0.0) for et in event_types)

        seq_bonus = 0.0
        for pattern_str, bonus in self.SEQUENCE_BONUS.items():
            if pattern_str in seq_key:
                seq_bonus = max(seq_bonus, bonus)

        sos_penalty = 0.0
        if type_set == {'SOS'}:
            sos_penalty = self.SOS_ALONE_PENALTY

        spring_adj = 0.0
        if has_spring and spring_event_count <= 1:
            spring_adj = self.SPRING_STANDALONE_BOOST

        raw = base + seq_bonus + sos_penalty + spring_adj
        raw = max(-1.0, min(1.0, raw))

        if not self._is_warm:
            self._last_score = raw
            self._is_warm = True
            return raw
        alpha = 2.0 / (self.EMA_SPAN + 1)
        smoothed = raw * alpha + self._last_score * (1.0 - alpha)
        self._last_score = smoothed
        return smoothed

    @classmethod
    def signal(cls, score: float) -> str:
        if score >= cls.BUY_THRESHOLD:
            return 'buy'
        elif score <= cls.SELL_THRESHOLD:
            return 'sell'
        return 'hold'


class WSSScorer:
    """Wyckoff Statistical Score — data-driven lookup from pre-trained weights.

    The lookup table maps event sequence keys (e.g. 'SC>SC>AR') to a WSS score
    derived from their empirical forward-return distribution.

    Training script: scripts/wyckoff_multitf/phase6_wss_scoring.py
    """

    def __init__(self, lookup: Optional[Dict[str, float]] = None):
        self.lookup: Dict[str, float] = lookup or {}

    @classmethod
    def from_json(cls, path: str) -> 'WSSScorer':
        with open(path) as f:
            raw = json.load(f)
        lookup = {k: v['wss'] if isinstance(v, dict) else v for k, v in raw.items()}
        return cls(lookup)

    def score(self, seq_key: str, fallback: float = 0.0) -> float:
        return self.lookup.get(seq_key, fallback)

    @property
    def is_loaded(self) -> bool:
        return len(self.lookup) > 0


class WyckoffScorer:
    """Unified scorer that blends WSO (rule) and WSS (statistical).

    Scoring hierarchy:
        1. If WSS lookup is loaded and sequence exists → WSS score
        2. Else → WSO score (per-event weights + bonuses)
        3. Blend: final = α * wso + β * wss  (default α=0.3, β=0.7 when wss available)
    """

    def __init__(
        self,
        wss_lookup: Optional[Dict[str, float]] = None,
        wss_path: Optional[str] = None,
        alpha: float = 0.3,
        beta: float = 0.7,
    ):
        self.wso = WSOScorer()
        self.wss = WSSScorer(wss_lookup or {})
        if wss_path:
            loaded = WSSScorer.from_json(wss_path)
            self.wss.lookup.update(loaded.lookup)
        self.alpha = alpha
        self.beta = beta

    def score_sequence(
        self,
        event_types: List[str],
        seq_key: str = '',
        has_spring: bool = False,
        spring_event_count: int = 0,
    ) -> Tuple[float, str]:
        wso_score = self.wso.score_events(event_types, has_spring, spring_event_count)

        if self.wss.is_loaded and seq_key and seq_key in self.wss.lookup:
            wss_score = self.wss.score(seq_key)
            blended = self.alpha * wso_score + self.beta * wss_score
        else:
            blended = wso_score

        signal = self.wso.signal(blended)
        return round(blended, 6), signal


def event_sequence_score(
    event_types: List[str],
    has_spring: bool = False,
    spring_event_count: int = 0,
    wss_lookup: Optional[Dict[str, float]] = None,
) -> Tuple[float, str]:
    """Convenience wrapper using WyckoffScorer."""
    scorer = WyckoffScorer(wss_lookup=wss_lookup)
    seq_key = '>'.join(event_types)
    return scorer.score_sequence(event_types, seq_key, has_spring, spring_event_count)


__all__ = [
    'WSOScorer',
    'WSSScorer',
    'WyckoffScorer',
    'event_sequence_score',
]
