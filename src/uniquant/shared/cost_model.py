"""Unified cost model — single truth source for all trading costs.

All backtest engines, simulators, and strategies MUST import from here
rather than defining their own cost constants.

Canonical values (A-share, 2024+):
- Commission: 0.03% (万3)
- Stamp tax: 0.05% (万5, sell-side only)
- Min commission: 5 CNY per trade
- Slippage: 0.05% (万5) — average A-share market impact
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Module-level constants (backward-compatible) ──────────────────────────

COMMISSION_PCT: float = 0.0003            # 万3
STAMP_TAX_PCT: float = 0.0005             # 万5 (2024+)
STAMP_TAX_PCT_OLD: float = 0.001          # 千1 (pre-2024)
MIN_COMMISSION: float = 5.0               # 单笔最低5元
SLIPPAGE_PCT: float = 0.0005              # 万5

COST_BUY = COMMISSION_PCT
COST_SELL = COMMISSION_PCT + STAMP_TAX_PCT  # 0.08%


# ── Config dataclass (for dependency injection) ───────────────────────────

@dataclass
class CostConfig:
    buy_fee_pct: float = COMMISSION_PCT
    sell_fee_pct: float = COMMISSION_PCT
    stamp_tax_pct: float = STAMP_TAX_PCT
    slippage_pct: float = SLIPPAGE_PCT
    min_commission: float = MIN_COMMISSION

    @classmethod
    def from_env(cls) -> "CostConfig":
        """Override individual fields via LPPL_COST_* environment variables."""
        overrides = {}
        for var, key in [
            ("LPPL_COST_BUY_FEE", "buy_fee_pct"),
            ("LPPL_COST_SELL_FEE", "sell_fee_pct"),
            ("LPPL_COST_STAMP_TAX", "stamp_tax_pct"),
            ("LPPL_COST_SLIPPAGE", "slippage_pct"),
            ("LPPL_COST_MIN_COMMISSION", "min_commission"),
        ]:
            val = os.environ.get(var)
            if val is not None:
                try:
                    overrides[key] = float(val)
                except ValueError:
                    logger.warning("Invalid %s=%r, ignoring", var, val)
        if overrides:
            merged = cls(**overrides)
            logger.info("CostConfig overridden from env: %s", overrides)
            return merged
        return cls()

    @classmethod
    def from_yaml(cls, yaml_path: Optional[str] = None) -> "CostConfig":
        """Load from trading.yaml execution section.

        The yaml stores slippage_pct as a percentage (e.g. 0.1 for 0.1%).
        """
        if yaml_path is None:
            yaml_path = str(Path(__file__).resolve().parents[2] / "config" / "trading.yaml")
        try:
            with open(yaml_path) as f:
                import yaml as _yaml
                cfg = _yaml.safe_load(f)
            exec_cfg = cfg.get("execution", {}) if cfg else {}
            buy_fee = float(exec_cfg.get("buy_fee_pct", COMMISSION_PCT))
            sell_fee = float(exec_cfg.get("sell_fee_pct", COMMISSION_PCT))
            slippage_pct = float(exec_cfg.get("slippage_pct", SLIPPAGE_PCT * 100)) / 100
            min_comm = float(exec_cfg.get("min_commission", MIN_COMMISSION))
            return cls(buy_fee_pct=buy_fee, sell_fee_pct=sell_fee,
                       slippage_pct=slippage_pct, min_commission=min_comm)
        except Exception as e:
            logger.warning("Failed to load cost config from %s: %s", yaml_path, e)
            return cls()

    @property
    def cost_buy(self) -> float:
        return self.buy_fee_pct

    @property
    def cost_sell(self) -> float:
        return self.sell_fee_pct + self.stamp_tax_pct
