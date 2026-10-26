from harness.adapters.antigravity import AntigravityAdapter
from harness.adapters.base import Adapter, AdapterResult
from harness.adapters.claude import ClaudeAdapter
from harness.adapters.codex import CodexAdapter

REGISTRY = {"claude": ClaudeAdapter, "codex": CodexAdapter, "antigravity": AntigravityAdapter}


def build(name: str, **config) -> Adapter:
    return REGISTRY[name](**config)


__all__ = ["Adapter", "AdapterResult", "REGISTRY", "build", "ClaudeAdapter", "CodexAdapter", "AntigravityAdapter"]
