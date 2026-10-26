"""Bitstrings and probabilities.

qsafe uses big-endian bit ordering: qubit 0 is the leftmost character of a
bitstring and the most significant bit, so bitstring_to_int("10") == 2 means
qubit 0 measured 1. (Qiskit uses the opposite convention; qsafe does not.)
"""

from __future__ import annotations

import random


class CircuitError(ValueError):
    pass


def bitstring_to_int(bits: str) -> int:
    """Integer value of a big-endian bitstring (qubit 0 is the most significant bit)."""
    if not bits or set(bits) - {"0", "1"}:
        raise CircuitError(f"not a bitstring: {bits!r}")
    try:
        return int(bits, 2)
    except ValueError as e:  # unreachable after the check; kept as a guard
        raise CircuitError(f"not a bitstring: {bits!r}") from e


def probabilities(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    if total == 0:
        raise CircuitError("no shots recorded")
    probs = {}
    for bits, n in counts.items():
        p = n / total
        # Exact zero is intended: p is a ratio of integer counts, so it is
        # 0.0 exactly when the count is 0.
        if p == 0.0:
            continue
        probs[bits] = p
    return probs


def retry_delay(attempt: int) -> float:
    """Back-off delay before retrying a network call.

    The jitter is deliberately random and not reproducible; it only spreads
    out retries and never affects results.
    """
    return min(2 ** attempt, 30) * (0.5 + random.random() / 2)
