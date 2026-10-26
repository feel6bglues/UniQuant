"""A-share market constraint wrappers for Wyckoff research pipeline.

Backward-compatibility shim:
The canonical implementation has moved to `uniquant.brain.wyckoff.ashare_constraints`.
"""

from uniquant.brain.wyckoff.ashare_constraints import (  # noqa: F401
    AShareConstraints,
    _get_limit_pct,
    filter_tradeable_universe,
)

__all__ = [
    "AShareConstraints",
    "_get_limit_pct",
    "filter_tradeable_universe",
]
