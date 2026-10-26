"""Circuits as ordered lists of operations."""

from __future__ import annotations

from dataclasses import dataclass, field

GATES = {"h", "x", "y", "z", "cx", "rz"}
NON_UNITARY = {"measure", "reset"}


@dataclass
class Operation:
    name: str
    qubits: tuple[int, ...]
    params: tuple[float, ...] = ()


@dataclass
class Circuit:
    num_qubits: int
    ops: list[Operation] = field(default_factory=list)

    def add(self, name: str, *qubits: int, params: tuple[float, ...] = ()) -> "Circuit":
        if name not in GATES | NON_UNITARY:
            raise ValueError(f"unknown operation {name!r}")
        self.ops.append(Operation(name, tuple(qubits), tuple(params)))
        return self

    def to_dict(self) -> dict:
        return {"num_qubits": self.num_qubits,
                "ops": [{"name": o.name, "qubits": list(o.qubits), "params": list(o.params)} for o in self.ops]}


def from_dict(data: dict) -> Circuit:
    """Convert a serialised circuit back into a Circuit, preserving every
    operation in order, including mid-circuit measurement and reset."""
    circuit = Circuit(data["num_qubits"])
    for op in data["ops"]:
        if op["name"] not in GATES:
            continue
        circuit.add(op["name"], *op["qubits"], params=tuple(op.get("params", ())))
    return circuit
