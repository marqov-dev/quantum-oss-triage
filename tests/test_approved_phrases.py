"""Approved phrases: a person-approved exact sentence passes the exploit-wording check, nothing else does."""

from pathlib import Path

from harness.publish import redact

PHRASE = "JSON payload schema handling"


def test_unapproved_word_still_blocks():
    assert redact.check(f"Reviewed: {PHRASE}.", []) == ["exploit wording: 'payload'"]


def test_approved_phrase_passes():
    assert redact.check(f"Reviewed: {PHRASE}.", [], approved_phrases=(PHRASE,)) == []


def test_same_word_elsewhere_still_blocks():
    text = f"Reviewed: {PHRASE}. A crafted payload reaches the parser."
    assert redact.check(text, [], approved_phrases=(PHRASE,)) == ["exploit wording: 'payload'"]


def test_approval_does_not_hide_sensitive_finding():
    f = {"id": "F1", "title": PHRASE, "claim": "x", "file": "a.rs", "line_start": 3}
    problems = redact.check(f"Reviewed: {PHRASE}.", [f], approved_phrases=(PHRASE,))
    assert problems == ["F1: sensitive title appears in shared output"]


def test_used_lists_only_phrases_present():
    assert redact.approved_used(f"x {PHRASE} y", (PHRASE, "other text")) == [PHRASE]


def test_load_approvals_by_repo(tmp_path: Path):
    (tmp_path / "publish-approvals.yaml").write_text(
        "approvals:\n"
        "  - repo: qiskit-community/qrmi\n"
        f"    phrase: {PHRASE}\n"
        "    approved_by: David Ryan\n"
        "    approved_on: 2026-11-12\n"
        "    reason: API message body\n")
    assert redact.load_approvals(tmp_path, "qiskit-community/qrmi") == (PHRASE,)
    assert redact.load_approvals(tmp_path, "zxcalc/pyzx") == ()
    assert redact.load_approvals(tmp_path / "missing", "zxcalc/pyzx") == ()


def test_approval_without_approver_is_refused(tmp_path: Path):
    (tmp_path / "publish-approvals.yaml").write_text(
        f"approvals:\n  - repo: a/b\n    phrase: {PHRASE}\n")
    try:
        redact.load_approvals(tmp_path, "a/b")
    except ValueError as e:
        assert "approved_by" in str(e)
    else:
        raise AssertionError("an approval with no approver must not load")
