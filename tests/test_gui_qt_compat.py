"""Qt compatibility helper tests that do not require PySide6."""

from __future__ import annotations

from dataclasses import dataclass

from audiocli.gui.qt_compat import is_checked_state


@dataclass(frozen=True)
class FakeQtEnum:
    value: int


def test_is_checked_state_accepts_legacy_int_values() -> None:
    assert is_checked_state(2) is True
    assert is_checked_state(0) is False
    assert is_checked_state(1) is False


def test_is_checked_state_accepts_modern_enum_value_objects() -> None:
    assert is_checked_state(FakeQtEnum(2)) is True
    assert is_checked_state(FakeQtEnum(0)) is False
    assert is_checked_state(FakeQtEnum(1)) is False


def test_is_checked_state_does_not_cast_enum_with_unsupported_int_conversion() -> None:
    class IntHostileEnum:
        value = 2

        def __int__(self) -> int:  # pragma: no cover - should never be called
            raise TypeError("int conversion not supported")

    assert is_checked_state(IntHostileEnum()) is True
