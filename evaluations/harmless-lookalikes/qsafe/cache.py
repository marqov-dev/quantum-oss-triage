"""An in-memory cache of compiled circuits."""

from __future__ import annotations

import hashlib
import pickle


class CircuitCache:
    def __init__(self):
        self._store: dict[str, object] = {}

    @staticmethod
    def key(circuit_text: str) -> str:
        # A cache key, not a security boundary.
        return hashlib.md5(circuit_text.encode(), usedforsecurity=False).hexdigest()

    def put(self, circuit_text: str, compiled: object) -> None:
        self._store[self.key(circuit_text)] = compiled

    def get_copy(self, circuit_text: str) -> object | None:
        """Return an independent deep copy, so callers cannot mutate the cache.

        The bytes come from pickle.dumps of an object this process created
        itself, in the same call; nothing external is ever unpickled here.
        """
        obj = self._store.get(self.key(circuit_text))
        if obj is None:
            return None
        return pickle.loads(pickle.dumps(obj))
