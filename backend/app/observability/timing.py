from contextlib import contextmanager
from time import perf_counter
from typing import Iterator


@contextmanager
def measured(timings: dict[str, int], stage: str) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        timings[stage] = max(0, round((perf_counter() - started) * 1000))

