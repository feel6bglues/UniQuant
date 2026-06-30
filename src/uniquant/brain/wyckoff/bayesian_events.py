"""Lightweight Bayesian probability cloud model for Wyckoff event detection.

Wraps the 8 existing detectors with online Beta posterior updates.
Each observation updates a Beta(alpha, beta) posterior for that event type.
The posterior mean represents accumulated evidence — "probability cloud collapse"
occurs when posterior mean exceeds a threshold.

Usage:
    from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
    from uniquant.brain.wyckoff.events import detect_all_events

    detector = BayesianEventDetector(prior_alpha=1.0, prior_beta=1.0)
    events = detect_all_events(df)
    detector.update_from_events(events)
    collapsed, mean = detector.collapse_probability("PS", threshold=0.8)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import beta as beta_dist

_MAX_RAW_SCORE = 8.0


@dataclass
class BayesianEventState:
    """Posterior state for one event type.

    Attributes:
        alpha: Beta posterior alpha (positive evidence count).
        beta: Beta posterior beta (negative evidence count).
        last_score: Most recent normalized score observation.
        n_observations: Total number of observations received.
    """

    alpha: float = 1.0
    beta: float = 1.0
    last_score: float = 0.0
    n_observations: int = 0


class BayesianEventDetector:
    """Online Bayesian posterior overlay over Wyckoff event detectors.

    Each event detection is treated as a Bernoulli trial whose success
    probability equals the confidence score. The Beta distribution is the
    conjugate prior for a Bernoulli likelihood, giving closed-form posterior
    updates.

    "Probability cloud collapse" refers to the posterior mean exceeding a
    threshold, signalling accumulated evidence for a given event type.
    """

    def __init__(self, prior_alpha: float = 1.0, prior_beta: float = 1.0):
        """Initialise with Beta prior parameters.

        Args:
            prior_alpha: Beta prior alpha (default 1.0 = uniform).
            prior_beta: Beta prior beta (default 1.0 = uniform).
        """
        self._prior_alpha = prior_alpha
        self._prior_beta = prior_beta
        self._posteriors: Dict[str, BayesianEventState] = {}

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(self, event_type: str, score: float, confidence: float) -> None:
        """Online posterior update from one event observation.

        Args:
            event_type: Event type key (e.g. 'PS', 'SC', 'SOS').
            score: Normalised score in [-1, 1]. Positive confirms the event,
                negative rejects it.
            confidence: Detection confidence in [0, 1] (sigmoid output from
                the detector).
        """
        if event_type not in self._posteriors:
            self._posteriors[event_type] = BayesianEventState(
                alpha=self._prior_alpha,
                beta=self._prior_beta,
            )
        state = self._posteriors[event_type]

        pseudo_count = max(1.0, confidence * 10.0)

        obs_success = max(0.0, score) * pseudo_count
        obs_failure = max(0.0, -score) * pseudo_count

        state.alpha += obs_success
        state.beta += obs_failure
        state.last_score = score
        state.n_observations += 1

    def update_from_events(self, events: List) -> None:
        """Update posteriors from a list of WyckoffEvent objects.

        Extracts the raw integer score from ``event.features['score']`` and
        normalises it to the [-1, 1] range expected by :meth:`update`.
        """
        for ev in events:
            raw = ev.features.get("score", 0)
            norm = np.clip(raw / _MAX_RAW_SCORE, -1.0, 1.0)
            self.update(ev.event_type, norm, ev.confidence)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def posterior_mean(self, event_type: str) -> float:
        """Current posterior mean for an event type.

        Equivalent to the expected value of the Beta distribution,
        alpha / (alpha + beta).
        """
        state = self._posteriors.get(event_type)
        if state is None:
            return 0.0
        total = state.alpha + state.beta
        return state.alpha / total if total > 0 else 0.0

    def collapse_probability(self, event_type: str, threshold: float = 0.8) -> Tuple[bool, float]:
        """Probability cloud collapse decision.

        Collapse occurs when the posterior mean exceeds *threshold*.

        Returns:
            Tuple of (is_collapsed, posterior_mean).
        """
        mean = self.posterior_mean(event_type)
        return mean >= threshold, mean

    def evidence_ratio(self, event_type: str) -> float:
        """Ratio of positive to total evidence — same as posterior_mean()."""
        return self.posterior_mean(event_type)

    def credible_interval(
        self, event_type: str, alpha: float = 0.05
    ) -> Tuple[float, float]:
        """Credible interval for the posterior probability.

        Args:
            event_type: Event type key.
            alpha: Significance level (default 0.05 → 95 % interval).

        Returns:
            Tuple of (lower_bound, upper_bound).
        """
        state = self._posteriors.get(event_type)
        if state is None:
            return (0.0, 0.0)
        return (
            float(beta_dist.ppf(alpha / 2.0, state.alpha, state.beta)),
            float(beta_dist.ppf(1.0 - alpha / 2.0, state.alpha, state.beta)),
        )

    def posterior_std(self, event_type: str) -> float:
        """Standard deviation of the posterior Beta distribution."""
        state = self._posteriors.get(event_type)
        if state is None:
            return 0.0
        total = state.alpha + state.beta
        if total <= 0:
            return 0.0
        return float(
            np.sqrt(
                (state.alpha * state.beta)
                / (total * total * (total + 1.0))
            )
        )

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def reset(self, event_type: Optional[str] = None) -> None:
        """Reset posterior(s) to prior.

        Args:
            event_type: If provided, reset only that event type; otherwise
                reset all posteriors.
        """
        if event_type is not None:
            self._posteriors.pop(event_type, None)
        else:
            self._posteriors.clear()

    def get_adjustment(self, event_type: str) -> float:
        """Posterior-derived score adjustment in [-0.1, +0.1].

        Maps posterior mean from [0, 1] to [-0.1, +0.1]: mean 0.5 → 0,
        mean 1.0 → +0.1, mean 0.0 → -0.1.
        """
        return (self.posterior_mean(event_type) - 0.5) * 0.2

    def get_all_posteriors(self) -> Dict[str, Dict]:
        """Return all current posteriors as a serialisable dictionary."""
        result: Dict[str, Dict] = {}
        for etype, state in self._posteriors.items():
            total = state.alpha + state.beta
            result[etype] = {
                "alpha": state.alpha,
                "beta": state.beta,
                "mean": state.alpha / total if total > 0 else 0.0,
                "n_obs": state.n_observations,
                "last_score": state.last_score,
            }
        return result

    # ------------------------------------------------------------------
    # Batch update
    # ------------------------------------------------------------------

    def update_batch(
        self,
        observations: List[Tuple[str, float, float]],
    ) -> None:
        """Update posteriors from a list of (event_type, score, confidence) tuples."""
        for event_type, score, confidence in observations:
            self.update(event_type, score, confidence)


__all__ = [
    "BayesianEventState",
    "BayesianEventDetector",
]
