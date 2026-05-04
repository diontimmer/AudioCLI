from __future__ import annotations

import pytest

from audiocli.workers import parallel_map, resolve_worker_count


def test_resolve_worker_count_uses_default_for_zero_or_none() -> None:
    assert resolve_worker_count(None) >= 1
    assert resolve_worker_count(0) >= 1


def test_resolve_worker_count_accepts_positive_value() -> None:
    assert resolve_worker_count(3) == 3


def test_parallel_map_can_preserve_input_order() -> None:
    items = [3, 2, 1]

    assert parallel_map(items, lambda value: value * 10, workers=2, ordered=True) == [30, 20, 10]


def test_parallel_map_reraises_worker_exceptions() -> None:
    def explode(_value: int) -> int:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        parallel_map([1], explode, workers=1)
