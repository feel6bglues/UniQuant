#!/usr/bin/env python3
"""V-Shaped Reversal Detector for Wyckoff regime analysis.

Backward-compatibility shim:
The canonical implementation has moved to `uniquant.brain.wyckoff.v_shape_detector`.
"""

from uniquant.brain.wyckoff.v_shape_detector import (  # noqa: F401
    VShapeResult,
    VShapedReversalDetector,
    load_index_data,
)

__all__ = [
    "VShapeResult",
    "VShapedReversalDetector",
    "load_index_data",
]
