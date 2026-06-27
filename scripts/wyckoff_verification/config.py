"""Wyckoff verification framework — configuration."""

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"


@dataclass
class UniverseConfig:
    min_trading_days: int = 750
    min_trading_days_contiguous: int = 200
    min_avg_daily_turnover: float = 0.0
    train_end: str = "2021-12-31"
    test_end: str = "2026-06-18"
    ipo_seasoning_days: int = 250
    n_strata: int = 5
    bootstrap_iterations: int = 1000


@dataclass
class PatternTestConfig:
    spring_forward_days: list = field(default_factory=lambda: [5, 20, 60])
    upthrust_forward_days: list = field(default_factory=lambda: [5, 20, 60])
    spring_low_factor: float = 1.01
    spring_close_factor: float = 1.0
    upthrust_high_factor: float = 0.99
    upthrust_close_factor: float = 1.0
    min_event_distance: int = 10
    alpha: float = 0.05
    bh_fdr: float = 0.05
    bootstrap_iterations: int = 1000


@dataclass
class StrategyConfig:
    commission_pct: float = 0.0003
    stamp_duty_pct: float = 0.001
    slippage_pct: float = 0.001
    min_commission: float = 5.0
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    rr_take_partial: float = 3.0
    rr_take_full: float = 5.0


@dataclass
class FactorModelConfig:
    rebalance_months: int = 12
    n_portfolios: int = 5


@dataclass
class RegimeConfig:
    n_states: int = 2
    covariance_type: str = "full"
    n_iter: int = 1000


@dataclass
class VerifierConfig:
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    patterns: PatternTestConfig = field(default_factory=PatternTestConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    factor: FactorModelConfig = field(default_factory=FactorModelConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    n_jobs: int = 6
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "scripts" / "wyckoff_verification" / "output")
    seed: int = 42
