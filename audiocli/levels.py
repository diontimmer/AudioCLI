"""Audio level helpers shared by analysis and silence policies."""

from __future__ import annotations

import math

DB_FLOOR = -200.0


def to_dbfs(linear: float) -> float:
    """Convert a linear amplitude to dBFS, clamped to :data:`DB_FLOOR`."""
    if linear <= 0.0:
        return DB_FLOOR
    return max(DB_FLOOR, 20.0 * math.log10(linear))


__all__ = ["DB_FLOOR", "to_dbfs"]
