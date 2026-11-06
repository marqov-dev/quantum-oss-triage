"""The per-repository report, sorted by the strength of each finding's evidence.

No person decides findings one by one. Every finding goes in a section by rule,
from the gates, the challenge and the blind-fix gate, and each section says how
strong its evidence is. A person checks a sample and approves the send.

Sections:

- likely: the test passed the gates, the challengers upheld it, a blind fix made
  it pass, and no fixer said the claim does not hold.
- disagree: the test passed the gates, but the checks disagree.
- weak: the challengers refuted the test and no blind fix confirmed it.
- untested: a correctness or documentation claim with no test that passed the
  gates; only the models' verdicts.
- fixed_upstream: the test passes on the project's current default branch.
- advisory: known advisories in dependencies, shown in full.
- security: newly found security issues, counted only; details go privately
  (docs/DISCLOSURE.md).

Severities are the proposals of each model or tool, labelled as proposals.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
SECTIONS = [
    ("likely", "Likely defects",
     "The test fails at the reviewed commit and on your current main, the models that did not write it could "
     "not break it, and a fix written without seeing the test makes it pass without breaking other tests."),
    ("disagree", "Where the models disagree",
     "Each has a test that fails reliably, but the checks point in different directions. Each model's view is "
     "shown. These often mark behaviour that the code or its documentation leaves unclear."),
    ("untested", "Claims we could not test",
     "No test for these passed our gates. What is shown is the models' reading of the code, which is weaker "
     "evidence."),
    ("weak", "Probably not defects",
     "The challengers showed the test is wrong, and no blind fix confirmed it. Listed so nothing is hidden; "
     "a claim several models got wrong can still point at confusing code."),
    ("fixed_upstream", "Already fixed upstream",
     "These failed at the reviewed commit but pass on your current main."),
    ("advisory", "Known advisories in dependencies", "Reported by osv-scanner against the locked dependencies."),
]
VERDICT_BOX = "**Your verdict:** ☐ real ☐ not real ☐ intended behaviour  (a one-word reply per ID is plenty)"


def _by_id(doc: dict | None) -> dict:
    return {x["id"]: x for x in (doc or {}).get("findings", [])}


def section(f: dict, gate: dict | None, chal: dict | None, fix: dict | None) -> str:
    if f["category"] == "security_vulnerability":
        return "security"
    if f["category"] == "dependency_advisory":
        return "advisory"
    verdict = (gate or {}).get("verdict")
    if verdict != "passed":
        if verdict == "failed" and ((gate or {}).get("head") or {}).get("outcome") == "passes":
            return "fixed_upstream"
        return "untested"
    c, x = (chal or {}).get("outcome"), (fix or {}).get("outcome")
    dissent = any(a.get("claim_holds") == "no" for a in (fix or {}).get("attempts", []))
    if c == "upheld" and x == "confirmed" and not dissent:
        return "likely"
    if c == "refuted" and x in ("not_confirmed", "disputed"):
        return "weak"
    return "disagree"


def proposals(f: dict) -> list[dict]:
    """Each source's proposed severity, highest first."""
    out = [{"by": p["by"].replace("verify/", ""), "value": p["value"]} for p in f["severity"]["proposed"]
           if p.get("value") in SEVERITY_ORDER]
    return sorted(out, key=lambda p: SEVERITY_ORDER.index(p["value"]))


def _highest(f: dict) -> int:
    p = proposals(f)
    return SEVERITY_ORDER.index(p[0]["value"]) if p else len(SEVERITY_ORDER)


def _read(run_dir: Path, ref: str | None, name: str) -> str | None:
    if not ref:
        return None
    p = run_dir / ref / name if name else run_dir / ref
    return p.read_text() if p.is_file() else None


def _best_fix(run_dir: Path, fix: dict | None) -> dict | None:
    passing = [a for a in (fix or {}).get("attempts", []) if a["status"] == "passes" and a.get("diff_ref")]
    if not passing:
        return None
    a = sorted(passing, key=lambda a: (a.get("claim_holds") != "yes", len(a.get("files_changed") or [])))[0]
    return {"by": a["fixer"], "summary": a.get("summary", ""), "diff": _read(run_dir, a["diff_ref"], ""),
            "files": a.get("files_changed") or []}


def claim_text(f: dict) -> str:
    """The claim to show a team. A claim from the earlier hand review is working notes, not
    written for the team, so use the verified test's stated expectation and failure instead."""
    if any(d["source"] != "prior_work" for d in f["detection"]["detections"]):
        return f["claim"]
    rp = f["validation"].get("reproduction") or {}
    if rp.get("claimed_failure"):
        return f"{rp['claimed_failure']} Expected behaviour, from {rp.get('expected_behaviour_source') or 'the code'}."
    return f["title"]


def item(f: dict, sec: str, run_dir: Path, gate: dict | None, chal: dict | None, fix: dict | None,
         prior_fix: dict | None) -> dict:
    found = sorted({d["tool"] for d in f["detection"]["detections"]})
    views = [{"stage": "verify", "model": v["verifier"], "verdict": v["verdict"], "reason": v.get("reason", "")}
             for v in f["corroboration"]["verifications"]]
    views += [{"stage": "challenge", "model": c["challenger"],
               "verdict": c.get("counted") or c.get("failed") and "did not run",
               "reason": c.get("reason") or c.get("failed", "")} for c in (chal or {}).get("challenges", [])]
    views += [{"stage": "blind fix", "model": a["fixer"],
               "verdict": f"claim holds: {a.get('claim_holds') or 'no answer'}; fix {a['status'].replace('_', ' ')}",
               "reason": a.get("notes", "")} for a in (fix or {}).get("attempts", [])]
    ref = (gate or {}).get("evidence_ref")
    return {"id": f["id"], "section": sec, "title": f["title"], "area": f["area"],
            "location": f"{f['file']}:{f['line_start']}" + (f"-{f['line_end']}" if f["line_end"] != f["line_start"] else ""),
            "claim": claim_text(f), "why": f["why_it_matters"], "severity": proposals(f), "found_by": found,
            "raised_before": sorted({u for p in f.get("prior_work") or [] for u in p["upstream"]}),
            "test": _read(run_dir, ref, "test_qot_repro.py"), "control": _read(run_dir, ref, "test_qot_control.py"),
            "gate_reason": (gate or {}).get("reason"), "challenge": (chal or {}).get("outcome"),
            "challenge_reason": (chal or {}).get("reason"), "fix_gate": (fix or {}).get("outcome"),
            "fix_gate_reason": (fix or {}).get("reason"), "views": views,
            "fix": _best_fix(run_dir, fix), "prior_fix": prior_fix}


def model_stats(groups: list[dict], findings: list[dict], sections: dict, chal: dict, fixg: dict) -> list[dict]:
    """How each model did, measured against the other checks (not against the maintainers)."""
    s = defaultdict(Counter)
    sec_of = {f["id"]: sections[f["id"]] for f in findings}
    for g in groups:
        for tool in {c["tool"] for c in g["candidates"]}:
            s[tool]["claims"] += 1
            if sec_of.get(g["id"]) == "likely":
                s[tool]["claims_likely"] += 1
        for rp in g.get("reproductions") or []:
            s[rp["by"]]["tests_written"] += 1
    for c in chal.values():
        s[c["author"]]["tests_challenged"] += 1
        s[c["author"]]["tests_upheld"] += c["outcome"] == "upheld"
    for x in fixg.values():
        for a in x["attempts"]:
            s[a["fixer"]]["fixes_attempted"] += 1
            s[a["fixer"]]["fixes_passed"] += a["status"] == "passes"
    return [{"model": m, **{k: c.get(k, 0) for k in ("claims", "claims_likely", "tests_written", "tests_challenged",
                                                      "tests_upheld", "fixes_attempted", "fixes_passed")}}
            for m, c in sorted(s.items()) if m != "prior-work"]


def build(manifest: dict, findings: list[dict], groups: list[dict], gates: dict, challenge: dict,
          fixgate: dict, run_dir: Path, prior_fixes: dict | None = None) -> dict:
    g, c, x = _by_id(gates), _by_id(challenge), _by_id(fixgate)
    prior_by_finding = {v["finding"]: {"name": k, **v} for k, v in (prior_fixes or {}).items()}
    secs = {f["id"]: section(f, g.get(f["id"]), c.get(f["id"]), x.get(f["id"])) for f in findings}
    items = [item(f, secs[f["id"]], run_dir, g.get(f["id"]), c.get(f["id"]), x.get(f["id"]),
                  prior_by_finding.get(f["id"]))
             for f in findings if secs[f["id"]] != "security"]
    items.sort(key=lambda i: (SEVERITY_ORDER.index(i["severity"][0]["value"]) if i["severity"] else 9, i["id"]))
    used = [a for a in manifest["adapters"] if a.get("used")]
    return {
        "title": f"{manifest['repo']['name']}: AI review",
        "header": {"repository": manifest["repo"]["name"], "commit": manifest["repo"]["commit"],
                   "current_main": (gates or {}).get("trees", {}).get("head"),
                   "review_date": (manifest.get("finished_at") or manifest["started_at"])[:10],
                   "completion": manifest.get("status", "unknown"),
                   "scope": (manifest.get("repo") or {}).get("scope", {}),
                   "models": [{"cli": a["name"], "version": a["version"], "model_ids": a["model_ids"]} for a in used],
                   "tools": [{"name": s["name"], "version": s["version"], "status": s["status"]}
                             for s in manifest["scanners"]]},
        "counts": {k: sum(1 for i in items if i["section"] == k) for k, _, _ in SECTIONS},
        # For the round overview: likely defects by category, so counts stay comparable.
        "scorecard": {"counts": {"security_vulnerability": sum(1 for v in secs.values() if v == "security"),
                                 "dependency_advisory": sum(1 for v in secs.values() if v == "advisory"),
                                 **{cat: sum(1 for f in findings if secs[f["id"]] == "likely" and f["category"] == cat)
                                    for cat in ("correctness", "docs_tests_maintenance")}},
                      "basis": "likely defects, where every automatic check agreed"},
        "security_count": sum(1 for v in secs.values() if v == "security"),
        "hand_review_only": sum(1 for f in findings if secs[f["id"]] != "security"
                                and {d["source"] for d in f["detection"]["detections"]} == {"prior_work"}),
        "items": items,
        "models": model_stats(groups, findings, secs, c, x),
        "how_produced": {"method": "https://github.com/marqov-dev/quantum-oss-triage",
                         "harness_revision": manifest["harness_revision"], "run_id": manifest["run_id"]},
    }


SOURCE_NAMES = {"prior-work": "earlier hand review", "antigravity": "gemini"}


def _src(name: str) -> str:
    name = name.split("/")[0]
    return SOURCE_NAMES.get(name, name)


def _sev(i: dict) -> str:
    return ", ".join(f"{p['value']} ({_src(p['by'])})" for p in i["severity"]) or "none proposed"


def to_markdown(r: dict) -> str:
    h, n = r["header"], r["counts"]
    out = [f"# {r['title']}", "",
           f"Reviewed commit `{h['commit'][:12]}`" + (f", rechecked on current main `{h['current_main'][:12]}`"
                                                      if h.get("current_main") else "") + f", {h['review_date']}.", "",
           "This review was made by AI models and fixed-rule tools, then checked by the models against each other "
           "and by running tests. A person checked a sample. Nothing here has been filed upstream.", "",
           "## Summary", "", "| Section | Count |", "| --- | --- |"]
    out += [f"| {label} | {n[key]} |" for key, label, _ in SECTIONS]
    out += [f"| Security issues, reported to you separately | {r['security_count']} |", "",
            "Severities are the models' and tools' proposals, shown as proposed. They are not ours to set.", "",
            f"{r.get('hand_review_only', 0)} of these items came from an earlier review of this repository by hand at Marqov, not "
            "from the models; the models then verified, tested, challenged and fixed them like everything else. "
            "Each item says who found it.", "",
            "**What we ask of you:** for each item, a one-word verdict: real, not real, or intended behaviour. "
            "It is the only way to know which of these checks were right, and it improves the next review.", ""]
    for key, label, blurb in SECTIONS:
        rows = [i for i in r["items"] if i["section"] == key]
        if not rows:
            continue
        out += [f"## {label} ({len(rows)})", "", blurb, ""]
        if key == "advisory":
            out += ["| ID | Advisory | Severity proposed |", "| --- | --- | --- |"]
            out += [f"| {i['id']} | {i['title']} | {_sev(i)} |" for i in rows]
            out.append("")
            continue
        out += ["| ID | Title | Location | Severity proposed | Fix |", "| --- | --- | --- | --- | --- |"]
        out += [f"| {i['id']} | {i['title']} | `{i['location']}` | {_sev(i)} | "
                f"{'blind fix' if i['fix'] else ''}{' + hand fix' if i.get('prior_fix') else ''} |" for i in rows]
        out.append("")
        for i in rows:
            out += _item_md(i, full=key == "disagree")
    out += ["## How the models did", "",
            "Measured against our own checks, not yet against your verdicts.", "",
            "| Model | Claims made | Claims now in Likely defects | Tests written | Tests upheld / challenged | "
            "Blind fixes passed / attempted |", "| --- | --- | --- | --- | --- | --- |"]
    out += [f"| {_src(m['model'])} | {m['claims']} | {m['claims_likely']} | {m['tests_written']} | "
            f"{m['tests_upheld']} / {m['tests_challenged']} | {m['fixes_passed']} / {m['fixes_attempted']} |"
            for m in r["models"]]
    hdr = r["header"]
    out += ["", "## How this was produced", "",
            "Models: " + "; ".join(f"{m['cli']} {m['version'] or ''} ({', '.join(m['model_ids']) or 'id not reported'})"
                                   for m in hdr["models"]) + ".",
            "Tools: " + ", ".join(f"{t['name']} [{t['status']}]" for t in hdr["tools"]) + ".", "",
            f"Method: {r['how_produced']['method']} (harness `{r['how_produced']['harness_revision']}`, "
            f"run `{r['how_produced']['run_id']}`). A rerun is not guaranteed to give identical model answers.", ""]
    return "\n".join(out)


def _item_md(i: dict, full: bool) -> list[str]:
    """A short card. Tests and diffs are in the evidence document."""
    out = [f"### {i['id']} · {i['title']}", "",
           f"`{i['location']}` · {i['area']} · severity proposed: {_sev(i)} · "
           f"found by: {', '.join(_src(s) for s in i['found_by'])}", "",
           f"**Claim.** {_clip(i['claim'], 500)}", ""]
    if i["raised_before"]:
        out += [f"**Raised before.** {', '.join(i['raised_before'])}", ""]
    checks = [s for s in (i["gate_reason"] and i["section"] in ("untested", "fixed_upstream") and f"gates: {i['gate_reason']}",
                          i["challenge"] and f"challenge {i['challenge']}",
                          i["fix_gate"] and f"blind fix {i['fix_gate'].replace('_', ' ')}") if s]
    if checks:
        out += ["**Checks.** " + "; ".join(checks) + ".", ""]
    if full:
        out += [f"- {v['stage']}, {_src(v['model'])}: **{v['verdict']}**. {_clip(v['reason'], 280)}" for v in i["views"]]
        out.append("")
    else:
        out += ["**Models.** " + "; ".join(f"{v['stage']} {_src(v['model'])}: {v['verdict']}" for v in i["views"]) + ".", ""]
    extra = [s for s in ("test" if i["test"] else "", "blind fix" if i["fix"] else "",
                         "hand fix" if i.get("prior_fix") else "") if s]
    if extra:
        out += [f"Evidence document, {i['id']}: {', '.join(extra)}.", ""]
    return out + [VERDICT_BOX, ""]


def to_evidence_markdown(r: dict) -> str:
    """The tests and fixes behind the report, by ID."""
    out = [f"# {r['title']}: evidence", "",
           "Tests and fixes for the items in the report. Each test fails at the reviewed commit; its control passes. "
           "A blind fix was written by a model that never saw the test; it makes the test pass, the control still "
           "passes, and no other test in the touched packages newly fails.", ""]
    for i in r["items"]:
        if not (i["test"] or i["fix"] or i.get("prior_fix")):
            continue
        out += [f"## {i['id']} · {i['title']}", ""]
        if i["test"]:
            out += ["Test:", "", "```python", i["test"].rstrip(), "```", ""]
        if i["control"]:
            out += ["Control:", "", "```python", i["control"].rstrip(), "```", ""]
        if i["fix"] and i["fix"]["diff"]:
            out += [f"Blind fix by {_src(i['fix']['by'])}. {i['fix']['summary']}", "", "```diff", i["fix"]["diff"].rstrip(), "```", ""]
        p = i.get("prior_fix")
        if p and p.get("diff"):
            out += [f"Hand-made fix, rechecked on current main: {p['status'].replace('_', ' ')}.", "",
                    "```diff", p["diff"].rstrip(), "```", ""]
    return "\n".join(out)


def _clip(text: str, n: int = 600) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def load(run_dir: Path, repo_dir: Path) -> dict:
    def j(name, default):
        p = repo_dir / name
        return json.loads(p.read_text()) if p.exists() else default
    prior_dir = repo_dir / "prior-fixes"
    prior = json.loads((prior_dir / "results.json").read_text()) if (prior_dir / "results.json").exists() else None
    for name, v in (prior or {}).items():
        d = prior_dir / name / "fix.diff"
        v["diff"] = d.read_text() if d.exists() else None
    return build(j("manifest.json", {}), j("findings.json", []), j("groups.json", []), j("gates.json", {}),
                 j("challenge.json", {}), j("fixgate.json", {}), run_dir, prior)
