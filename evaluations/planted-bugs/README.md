# qtoy

A tiny circuit toolkit.

## Quick start

```python
import qtoy

c = qtoy.Circuit(2).add("h", 0).add("cx", 0, 1)
counts = qtoy.run_circuit(c, seed=7)
print(qtoy.expectation_z(counts))
```

`execute` runs 1024 shots by default. Results use little-endian ordering
(qubit 0 is the rightmost bit).

See the [user guide](docs/guide.md) and the [API notes](docs/api.md).
