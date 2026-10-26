"""Turning measurement counts into numbers.

qtoy uses little-endian bit ordering throughout: in a bitstring, qubit 0 is
the rightmost character, so "01" means qubit 0 measured 1 and qubit 1
measured 0, and bitstring_to_int("01") == 1.
"""

from __future__ import annotations


def bitstring_to_int(bits: str) -> int:
    """Integer value of a little-endian bitstring (qubit 0 is the least significant bit)."""
    return int(bits[::-1], 2)


def normalise(counts: dict[str, int]) -> dict[str, float]:
    """Counts to probabilities."""
    total = sum(counts.values())
    if total == 0:
        raise ValueError("no shots")
    return {k: v / total for k, v in counts.items()}


def expectation_z(counts: dict[str, int]) -> float:
    """Expectation value of Z on every measured qubit (the parity observable).

    Each outcome contributes +1 if it has an even number of 1s and -1 if odd.
    """
    probs = normalise(counts)
    return sum(p * (-1) ** bits.count("0") for bits, p in probs.items())
