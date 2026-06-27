"""Wyckoff Multi-Timeframe Verification — Config."""

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"


@dataclass
class TfParams:
    lookback: int          # bars for phase detection
    spring_low_factor: float
    min_bars: int
    atr_period: int


@dataclass
class SignalLevelDef:
    min_monthly_phase: str = ""
    min_weekly_phase: str = ""
    require_weekly_spring: bool = False
    require_daily_spring: bool = False
    max_weekly_conf: str = "D"
    weight: float = 0.0

    def __post_init__(self):
        self._phase_order = {"accumulation": 0, "markup": 1, "distribution": 2, "markdown": 3, "unknown": 4}
        self._conf_order = {"A": 0, "B": 1, "C": 2, "D": 3}

    def matches(self, mp: str, wp: str, ws: bool, ds: bool, wc: str) -> bool:
        mo = self._phase_order.get(mp, 4)
        wo = self._phase_order.get(wp, 4)
        m_min = self._phase_order.get(self.min_monthly_phase, 4)
        w_min = self._phase_order.get(self.min_weekly_phase, 4)
        wc_max = self._conf_order.get(wc, 3)
        wc_allow = self._conf_order.get(self.max_weekly_conf, 3)
        if mo > m_min:
            return False
        if wo > w_min:
            return False
        if self.require_weekly_spring and not ws:
            return False
        if self.require_daily_spring and not ds:
            return False
        if wc_max > wc_allow:
            return False
        return True


@dataclass
class VerifierConfig:
    n_jobs: int = _DEFAULT_N_JOBS

    # Multi-timeframe parameters (adapted for A-shares)
    daily_params: TfParams = field(default_factory=lambda: TfParams(120, 1.01, 120, 14))
    weekly_params: TfParams = field(default_factory=lambda: TfParams(24, 1.03, 12, 6))
    monthly_params: TfParams = field(default_factory=lambda: TfParams(6, 1.05, 6, 3))

    # Universe
    min_listing_days: int = 750
    ipo_seasoning: int = 250
    max_stocks: int = 1000
    n_strata: int = 5
    seed: int = 42

    # Testing
    n_bootstrap: int = 1000
    alpha: float = 0.05
    bh_fdr: float = 0.05

    # Data
    data_lake: Path = DATA_LAKE
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output")
