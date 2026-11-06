"""The tiered report: which section each finding lands in, and what may appear."""

from harness.publish import tiered


def f(cat="correctness", **kw):
    base = {"id": "QOT-1", "category": cat, "title": "add subtracts", "area": "correctness", "file": "m.py",
            "line_start": 1, "line_end": 1, "claim": "c", "why_it_matters": "w", "prior_work": [],
            "detection": {"detections": [{"tool": "claude", "source": "model"}]},
            "corroboration": {"verifications": []},
            "severity": {"proposed": [{"by": "verify/codex", "value": "low"}, {"by": "verify/claude", "value": "high"}]}}
    return {**base, **kw}


PASSED = {"verdict": "passed"}


def fixes(*holds):
    return {"outcome": "confirmed", "attempts": [{"claim_holds": h, "status": "passes"} for h in holds]}


def test_sections_by_rule():
    s = tiered.section
    assert s(f(), PASSED, {"outcome": "upheld"}, fixes("yes", "yes")) == "likely"
    # One fixer doubting the claim moves it out of Likely, even though a fix passed.
    assert s(f(), PASSED, {"outcome": "upheld"}, fixes("yes", "no")) == "disagree"
    assert s(f(), PASSED, {"outcome": "refuted"}, fixes("yes")) == "disagree"
    assert s(f(), PASSED, {"outcome": "upheld"}, {"outcome": "not_confirmed", "attempts": []}) == "disagree"
    assert s(f(), PASSED, {"outcome": "refuted"}, {"outcome": "disputed", "attempts": []}) == "weak"
    assert s(f(), PASSED, {"outcome": "unsettled"}, fixes("yes")) == "disagree"
    assert s(f(), {"verdict": "no_evidence"}, None, None) == "untested"
    assert s(f(), {"verdict": "failed", "head": {"outcome": "passes"}}, None, None) == "fixed_upstream"
    assert s(f(), {"verdict": "failed", "head": {"outcome": "still_fails"}}, None, None) == "untested"
    assert s(f("security_vulnerability"), PASSED, None, None) == "security"
    assert s(f("dependency_advisory"), None, None, None) == "advisory"


def test_severity_proposals_are_shown_highest_first():
    assert [p["value"] for p in tiered.proposals(f())] == ["high", "low"]


def _manifest():
    return {"repo": {"name": "o/r", "commit": "a" * 40}, "started_at": "2026-11-05T00:00:00Z", "adapters": [],
            "scanners": [], "harness_revision": "h", "run_id": "r"}


def test_security_details_never_reach_the_report(tmp_path):
    sec = f("security_vulnerability", id="QOT-2", title="SECRET-TITLE", claim="SECRET-CLAIM", file="SECRET.py")
    r = tiered.build(_manifest(), [f(), sec], [], {"findings": [{"id": "QOT-1", "verdict": "no_evidence"}]},
                     {}, {}, tmp_path)
    md = tiered.to_markdown(r)
    assert r["security_count"] == 1 and "SECRET" not in md
    assert "Claims we could not test (1)" in md and "Your verdict" in md


def test_model_stats_count_each_stage():
    groups = [{"id": "QOT-1", "candidates": [{"tool": "claude"}, {"tool": "prior-work"}],
               "reproductions": [{"by": "codex"}]}]
    chal = {"QOT-1": {"author": "codex", "outcome": "upheld"}}
    fixg = {"QOT-1": {"attempts": [{"fixer": "claude", "status": "passes"}, {"fixer": "antigravity", "status": "still_fails"}]}}
    rows = {m["model"]: m for m in tiered.model_stats(groups, [f()], {"QOT-1": "likely"}, chal, fixg)}
    assert "prior-work" not in rows
    assert rows["claude"]["claims_likely"] == 1 and rows["claude"]["fixes_passed"] == 1
    assert rows["codex"]["tests_upheld"] == 1 and rows["antigravity"]["fixes_attempted"] == 1


def test_hand_review_notes_are_not_shown_as_the_claim():
    hand = f(claim="hunt3/notes.py | Issue first", detection={"detections": [{"tool": "prior-work", "source": "prior_work"}]},
             validation={"reproduction": {"claimed_failure": "returns 0.0, not 1.0.", "expected_behaviour_source": "the docstring"}})
    assert "hunt3" not in tiered.claim_text(hand) and "0.0" in tiered.claim_text(hand)
    assert tiered.claim_text(f(claim="model claim")) == "model claim"
    assert tiered._src("codex/review-correctness") == "codex" and tiered._src("prior-work") == "earlier hand review"


def test_publish_writes_report_and_evidence_without_security_details(tmp_path):
    import json
    from harness.publish.__main__ import publish_repo
    run = tmp_path / "run"
    repo = run / "o__r"
    att = repo / "evidence" / "repro" / "QOT-1" / "0"
    att.mkdir(parents=True)
    (att / "test_qot_repro.py").write_text("def test_r(): assert add(2, 3) == 5\n")
    (att / "test_qot_control.py").write_text("def test_c(): pass\n")
    sec = f("security_vulnerability", id="QOT-2", title="SECRET-TITLE", claim="SECRET-CLAIM-TEXT", file="s.py",
            sensitivity={"sensitive": True})
    adv = f("dependency_advisory", id="QOT-3", title="GHSA-xxxx in numpy", file="uv.lock",
            sensitivity={"sensitive": True})
    good = f(sensitivity={"sensitive": False})
    m = {**_manifest(), "status": "complete", "stages": {}, "tokens": {},
         "coverage": {"incomplete_checks": [], "reviewed": [], "not_reviewed": []}}
    for name, data in (("manifest.json", m), ("findings.json", [good, sec, adv]), ("groups.json", []),
                       ("gates.json", {"findings": [{"id": "QOT-1", "verdict": "passed", "evidence_ref": "o__r/evidence/repro/QOT-1/0"}]}),
                       ("challenge.json", {"findings": [{"id": "QOT-1", "outcome": "upheld", "reason": "r", "author": "codex", "challenges": []}]}),
                       ("fixgate.json", {"findings": [{"id": "QOT-1", "outcome": "confirmed", "reason": "r",
                                                       "attempts": [{"fixer": "claude", "claim_holds": "yes", "status": "passes"}]}]})):
        (repo / name).write_text(json.dumps(data))
    ok, res = publish_repo(run, repo, tmp_path / "outbox")
    assert ok, res
    out = tmp_path / "outbox" / "o__r"
    md, ev = (out / "report.md").read_text(), (out / "evidence.md").read_text()
    assert "Likely defects (1)" in md and "GHSA-xxxx in numpy" in md and "SECRET" not in md + ev
    assert "assert add(2, 3) == 5" in ev and [d.key for d in res["docs"]][-1] == "o/r:evidence"
