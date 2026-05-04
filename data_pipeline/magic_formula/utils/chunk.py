from __future__ import annotations

from typing import Iterator, Sequence, TypeVar

T = TypeVar("T")


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Yield slices of *items* at most *size* large."""
    if size <= 0:
        raise ValueError("chunk size must be positive")

    for start in range(0, len(items), size):
        yield items[start : start + size]
