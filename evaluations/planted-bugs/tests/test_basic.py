from qtoy import Circuit, execute, normalise


def test_normalise_sums_to_one():
    probs = normalise({"00": 30, "11": 70})
    assert abs(sum(probs.values()) - 1.0) < 1e-12


def test_x_gate_flips_qubit_zero():
    counts = execute(Circuit(2).add("x", 0), shots=10, seed=1)
    assert counts == {"01": 10}
