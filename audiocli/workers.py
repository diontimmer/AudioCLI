"""Worker-count and simple parallel mapping helpers."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")
U = TypeVar("U")


def default_workers() -> int:
    """Default worker count: ``min(8, os.cpu_count() or 1)``."""
    return min(8, os.cpu_count() or 1)


def resolve_worker_count(workers: int | None) -> int:
    """Resolve ``None`` or non-positive worker counts to the project default."""
    return workers if workers is not None and workers > 0 else default_workers()


def parallel_map(
    items: Iterable[T],
    fn: Callable[[T], U],
    *,
    workers: int | None = None,
    ordered: bool = False,
) -> list[U]:
    """Run ``fn`` over ``items`` in a thread pool.

    Exceptions raised by ``fn`` are re-raised from the corresponding future.
    Callers that want per-item failures should catch inside ``fn`` and return
    an explicit result value.
    """
    item_list = list(items)
    if not item_list:
        return []

    results: list[tuple[int, U]] = []
    with ThreadPoolExecutor(max_workers=resolve_worker_count(workers)) as pool:
        future_to_index = {pool.submit(fn, item): i for i, item in enumerate(item_list)}
        for fut in as_completed(future_to_index):
            results.append((future_to_index[fut], fut.result()))

    if ordered:
        results.sort(key=lambda item: item[0])
    return [result for _, result in results]


__all__ = ["default_workers", "parallel_map", "resolve_worker_count"]
