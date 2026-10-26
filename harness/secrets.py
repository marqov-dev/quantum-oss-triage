"""Secret-like value patterns, shared by the scanners (to redact before
storing) and the publisher (to block before sharing)."""

from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[a-z]{2,6}_(?:live|prod|test)_[A-Za-z0-9]{16,}\b"),
]
# key = "value" assignments: the value is replaced, the name kept.
_ASSIGNMENT = re.compile(r"(?i)\b((?:api[_-]?key|token|secret|passw(?:or)?d)\w*\b\s*[:=]\s*)(['\"])([^'\"\s]{8,})\2")
# Bandit's "Possible hardcoded password: '<value>'"
_QUOTED_AFTER_COLON = re.compile(r"(?i)(hardcoded password(?: string)?:?\s*)(['\"])(.+?)\2")


def find(text: str) -> list[str]:
    hits = [m.group(0) for pat in SECRET_PATTERNS for m in pat.finditer(text or "")]
    hits += [m.group(3) for m in _ASSIGNMENT.finditer(text or "") if len(m.group(3)) >= 12]
    return hits


def redact(text: str) -> str:
    if not text:
        return text
    for pat in SECRET_PATTERNS:
        text = pat.sub("REDACTED", text)
    text = _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}REDACTED{m.group(2)}", text)
    return _QUOTED_AFTER_COLON.sub(lambda m: f"{m.group(1)}{m.group(2)}REDACTED{m.group(2)}", text)


def redact_obj(obj):
    """Redact every string inside a JSON-like value (before serialising, so
    escaping cannot be broken)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    return obj
