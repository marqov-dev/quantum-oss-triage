import copy

import pytest
from jsonschema import Draft202012Validator

from harness.controller import schema


@pytest.mark.parametrize("name", schema.NAMES)
def test_schema_is_valid_draft_2020_12(name):
    Draft202012Validator.check_schema(schema.load(name))


def _strict_ok(node, where="<root>"):
    """Codex --output-schema needs every property required and no extras."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False, where
            assert set(node["required"]) == set(node["properties"]), where
        for key, value in node.items():
            _strict_ok(value, f"{where}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _strict_ok(value, f"{where}/{i}")


@pytest.mark.parametrize("name", ["review-output", "verdict", "fix-output"])
def test_model_output_schemas_are_strict(name):
    _strict_ok(schema.load(name))


GOOD_REVIEW = {
    "findings": [
        {
            "title": "add() subtracts",
            "area": "correctness",
            "file": "m.py",
            "line_start": 1,
            "line_end": 1,
            "claim": "add returns a - b.",
            "evidence": "return a-b",
            "why_it_matters": "Callers get wrong sums.",
            "applies_because": None,
            "proposed_severity": "high",
            "security_impact": False,
            "confidence": "high",
            "suggested_check": "add(1, 1) returns 0, expected 2.",
        }
    ],
    "coverage": {"reviewed": ["m.py"], "not_reviewed": [], "notes": ""},
}


def test_good_review_output_validates():
    assert schema.validate("review-output", GOOD_REVIEW) == []


def test_review_output_rejects_unknown_area():
    bad = copy.deepcopy(GOOD_REVIEW)
    bad["findings"][0]["area"] = "vibes"
    assert schema.validate("review-output", bad)


def test_finding_record_requires_separate_evidence_fields(sample_finding):
    assert schema.validate("finding", sample_finding) == []
    for field in ("detection", "corroboration", "validation", "impact", "severity", "sensitivity", "disposition"):
        bad = copy.deepcopy(sample_finding)
        del bad[field]
        assert schema.validate("finding", bad), field
