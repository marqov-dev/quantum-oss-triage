from harness.controller import merge


def cand(tool, line=10, area="correctness", title="sign error in parity", file="q.py", **kw):
    return {"title": title, "area": area, "file": file, "line_start": line, "line_end": line, "claim": title,
            "evidence": "", "why_it_matters": "", "proposed_severity": "high", "security_impact": False,
            "tool": tool, "skill": "review-correctness", **kw}


def v(verifier, verdict, independence="independent"):
    return {"verifier": verifier, "verdict": verdict, "reason": "", "independence": independence, "unit": ""}


def test_grouping_merges_nearby_same_family_and_keeps_distinct_files():
    gs = merge.group([cand("claude", 10), cand("codex", 11, area="quantum"), cand("claude", 10, file="other.py"),
                      cand("antigravity", 40)])
    sizes = sorted(len(g) for g in gs)
    assert sizes == [1, 1, 2]


def test_main_queue_rule():
    assert merge.queue_for("reproduced", ["claude"], [])[0] == "main"
    assert merge.queue_for("unvalidated", ["claude", "codex"], [])[0] == "main"
    assert merge.queue_for("unvalidated", ["claude"], [v("codex", "confirm")])[0] == "main"
    assert merge.queue_for("unvalidated", ["claude"], [v("codex", "confirm"), v("agy", "refute")])[0] == "main"
    assert merge.queue_for("unvalidated", ["claude"], [v("codex", "refute")])[0] == "low"
    # Security impact is always triaged, even when refuted.
    assert merge.queue_for("unvalidated", ["claude"], [v("codex", "refute")], sensitive=True)[0] == "main"
    # A model confirming its own claim is not corroboration.
    assert merge.queue_for("unvalidated", ["claude"], [v("claude", "confirm", "same_model")])[0] == "low"


def test_corroboration_statuses():
    assert merge.corroboration_status(["claude"], [v("codex", "confirm"), v("agy", "refute")]) == "disputed"
    assert merge.corroboration_status(["claude"], [v("codex", "refute")]) == "refuted"
    assert merge.corroboration_status(["claude", "codex"], []) == "independent_discovery"
    assert merge.corroboration_status(["claude"], [v("claude", "confirm", "same_model")]) == "single_source"


def test_sensitivity_is_independent_of_severity():
    low_sev_secret = [cand("gitleaks", area="security", proposed_severity="low")]
    assert merge.sensitivity_for(low_sev_secret, [])["sensitive"]
    model_flag = [cand("claude", security_impact=True)]
    assert merge.sensitivity_for(model_flag, [])["sensitive"]
    verifier_flag = merge.sensitivity_for([cand("claude")], [{**v("codex", "confirm"), "security_impact": True}])
    assert verifier_flag["sensitive"]
    assert not merge.sensitivity_for([cand("claude", proposed_severity="critical")], [])["sensitive"]


def test_categories():
    assert merge.category_for([cand("osv-scanner", known_advisory=True)], True, "maintenance") == "dependency_advisory"
    assert merge.category_for([cand("claude")], True, "security") == "security_vulnerability"
    assert merge.category_for([cand("claude")], False, "quantum") == "correctness"
    assert merge.category_for([cand("claude")], False, "docs") == "docs_tests_maintenance"


def test_fingerprint_ignores_whitespace_but_not_content():
    a = merge.fingerprint("correctness", "q.py", "x = a -  b")
    assert a == merge.fingerprint("quantum", "q.py", "x=a-b")
    assert a != merge.fingerprint("correctness", "q.py", "x = a + b")
    assert merge.stable_id("r", a) == merge.stable_id("r", a)


def test_claims_from_one_unit_are_never_merged():
    a = cand("claude", 10, title="calls a missing function", unit="r/review/review-docs/claude")
    b = cand("claude", 12, title="states the wrong default", unit="r/review/review-docs/claude")
    c = cand("claude", 11, title="calls a missing function", unit="r/review/review-correctness/claude")
    groups = merge.group([a, b, c])
    assert len(groups) == 2
    assert all(len({m["unit"] for m in g}) == len(g) for g in groups)
