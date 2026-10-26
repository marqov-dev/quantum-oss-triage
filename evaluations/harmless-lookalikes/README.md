# qsafe

Utilities for bitstrings, settings and caching. Bitstrings are big-endian:
qubit 0 is the leftmost character. Retry jitter is random by design and is not
meant to be reproducible.

```python
from qsafe.bits import bitstring_to_int
assert bitstring_to_int("10") == 2
```
