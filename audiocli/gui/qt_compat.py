"""Small Qt compatibility helpers that do not import PySide6 eagerly."""

from __future__ import annotations

CHECKED_STATE_VALUE = 2


def is_checked_state(state: object) -> bool:
    """Return True for checked QCheckBox states across PySide6 enum/int variants.

    Older PySide6 releases commonly deliver ``stateChanged`` as ``int``. Newer
    versions can deliver a ``Qt.CheckState`` enum instance, where ``int(enum)`` is
    not portable. Qt's checked value is stable at 2.
    """

    value = getattr(state, "value", state)
    return value == CHECKED_STATE_VALUE


__all__ = ["CHECKED_STATE_VALUE", "is_checked_state"]
