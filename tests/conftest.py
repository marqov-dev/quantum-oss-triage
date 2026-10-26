import pytest


@pytest.fixture
def sample_finding():
    return {
        "id": "QOT-0123456789",
        "repo": "eval/planted-bugs",
        "commit": "0" * 40,
        "title": "add() subtracts",
        "area": "correctness",
        "category": "correctness",
        "file": "m.py",
        "line_start": 1,
        "line_end": 1,
        "fingerprint": "correctness:m.py:abc",
        "claim": "add returns a - b.",
        "evidence": "return a-b",
        "why_it_matters": "Wrong sums.",
        "applies_because": None,
        "detection": {
            "detections": [
                {"source": "model", "tool": "claude", "model_id": "claude-x", "skill": "review-correctness",
                 "unit": "r/review/review-correctness/claude", "title": "add() subtracts"}
            ],
            "detected_by": ["claude"],
        },
        "corroboration": {"independent_models": ["claude"], "verifications": [], "status": "single_source"},
        "validation": {"status": "unvalidated", "method": None, "notes": ""},
        "impact": {"statement": "Wrong sums.", "security_impact": False},
        "severity": {"proposed": [{"by": "claude", "value": "high"}], "final": None, "set_by": None},
        "sensitivity": {"sensitive": False, "reasons": [], "removal_reason": None},
        "disposition": {"queue": "low", "decision": "pending", "decided_by": None, "decided_at": None, "note": ""},
    }
