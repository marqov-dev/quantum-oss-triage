"""In-process fake adapters for pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

from harness.adapters.base import Adapter, AdapterResult
from harness.controller import skills


def finding(**kw):
    base = {"title": "add() subtracts", "area": "correctness", "file": "m.py", "line_start": 1, "line_end": 1,
            "claim": "add returns a - b.", "evidence": "return a - b", "why_it_matters": "Wrong sums.",
            "applies_because": None, "proposed_severity": "high", "security_impact": False, "confidence": "high",
            "suggested_check": "add(2, 3) == 5"}
    return {**base, **kw}


class FakeAdapter(Adapter):
    """Returns canned replies. `reviews` maps skill name -> list of findings."""

    def __init__(self, name: str, reviews: dict | None = None, verdict: str = "confirm", reproduction=None,
                 limit_after: int | None = None, fix_edits: list | None = None):
        super().__init__()
        self.name = name
        self.reviews = reviews or {}
        self.verdict = verdict
        self.reproduction = reproduction
        self.limit_after = limit_after
        self.fix_edits = fix_edits
        self.calls: list[tuple[str, str]] = []

    def available(self):
        return True, "fake"

    def version(self):
        return f"{self.name}-fake 1.0"

    def run(self, prompt, system, schema_name, cwd: Path, timeout_s=0):
        self.calls.append((schema_name, prompt[:80]))
        if self.limit_after is not None and len(self.calls) > self.limit_after:
            return AdapterResult(False, None, "usage limit reached", None, error="usage limit", usage_limited=True)
        tokens = {"input": 10, "output": 5}
        if schema_name == "review-output":
            name = next((s for s in self.reviews if prompt.startswith(skills.load(s).body[:60])), None)
            data = {"findings": self.reviews.get(name, []), "coverage": {"reviewed": ["m.py"], "not_reviewed": [], "notes": ""}}
        elif schema_name == "verdict":
            kind = "fix" if "## The proposed diff" in prompt else "finding"
            data = {"kind": kind, "verdict": self.verdict, "reason": "read it", "lines_read": [{"file": "m.py", "line_start": 1, "line_end": 2}],
                    "security_impact": False, "proposed_severity": "high",
                    "reproduction": self.reproduction if kind == "finding" else None,
                    "fix_assessment": {"fixes_cause": "yes", "keeps_behaviour": "yes", "regression_risk": "low"} if kind == "fix" else None}
        else:
            data = {"feasible": bool(self.fix_edits), "edits": self.fix_edits or [], "summary": "fix", "notes": ""}
        return AdapterResult(True, data, json.dumps(data), f"{self.name}-model-1", tokens, attempts=1)
