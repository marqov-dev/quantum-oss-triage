"""A toy local backend."""

from __future__ import annotations

import logging
import random

from qtoy.circuit import Circuit

log = logging.getLogger(__name__)


def _simulate(circuit: Circuit, shots: int, rng: random.Random) -> dict[str, int]:
    # A stand-in for a simulator: X gates flip bits, H gates randomise them.
    counts: dict[str, int] = {}
    for _ in range(shots):
        bits = [0] * circuit.num_qubits
        for op in circuit.ops:
            q = op.qubits[0]
            if op.name == "x":
                bits[q] ^= 1
            elif op.name == "h":
                bits[q] = rng.randint(0, 1)
            elif op.name == "reset":
                bits[q] = 0
        key = "".join(str(b) for b in reversed(bits))
        counts[key] = counts.get(key, 0) + 1
    return counts


def execute(circuit: Circuit, shots: int = 100, seed: int | None = None) -> dict[str, int]:
    """Run a circuit and return measurement counts keyed by little-endian bitstrings."""
    rng = random.Random(seed)
    try:
        return _simulate(circuit, shots, rng)
    except Exception:
        log.debug("simulation failed")
        return {}
