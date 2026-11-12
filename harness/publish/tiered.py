"""The per-repository report, sorted by the strength of each finding's evidence.

No person decides findings one by one. Every finding goes in a section by rule,
from the gates, the challenge and the blind-fix gate, and each section says how
strong its evidence is. A person approves the send.

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
    ("advisory", "Known advisories in dependencies", "Reported by osv-scanner against the locked dependencies, then re-checked on your current main."),
]
VERDICT_BOX = "**Your verdict:** ☐ real ☐ not real ☐ intended behaviour  (a one-word reply per ID is plenty)"


def _by_id(doc: dict | None) -> dict:
    return {x["id"]: x for x in (doc or {}).get("findings", [])}


def section(f: dict, gate: dict | None, chal: dict | None, fix: dict | None) -> str:
    if f["category"] == "dependency_advisory":
        return "advisory"
    # Withheld by the sensitive flag, not only by category: a reviewer may mark any finding
    # sensitive (triage decisions.yaml), and its details must then stay out too.
    if f["category"] == "security_vulnerability" or (f.get("sensitivity") or {}).get("sensitive"):
        return "security"
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


def _on_main(a: dict | None) -> str:
    """The advisory on upstream's current default branch, from the gates' re-scan."""
    if not a or a.get("head") == "unknown":
        return "not checked"
    if a["head"] == "present":
        return "still present"
    return f"resolved (now {a['head_version']})" if a.get("head_version") else "resolved"


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
    on_main = {a["id"]: a for a in (gates or {}).get("advisories", [])}
    for i in items:
        if i["section"] == "advisory":
            i["on_main"] = _on_main(on_main.get(i["id"]))
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


MODEL_NAMES = {"claude": "Claude", "codex": "Codex", "antigravity": "Gemini", "gemini": "Gemini"}


def made_by(r: dict) -> str:
    """Who made the review, stated from the run record: never more models, or more human checking, than ran."""
    full = [MODEL_NAMES.get(m["cli"], m["cli"]) for m in r["header"].get("models", [])]
    partial = sorted({MODEL_NAMES[s["model"]] for s in r.get("models", [])
                      if s["model"] in MODEL_NAMES and s["claims"]} - set(full))
    who = " and ".join([", ".join(full[:-1]), full[-1]] if len(full) > 2 else full) or "AI models"
    text = (f"Reviewed by {who}, with fixed-rule tools. The models then checked each other's claims, and their tests "
            "were run against the code.")
    if partial:
        text += f" {' and '.join(partial)}'s part in this review is not finished and will be added in an update."
    return text + " No person has checked these findings yet. Nothing here has been filed upstream."


def to_markdown(r: dict) -> str:
    h, n = r["header"], r["counts"]
    out = [f"# {r['title']}", "",
           f"Reviewed commit `{h['commit'][:12]}`" + (f", rechecked on current main `{h['current_main'][:12]}`"
                                                      if h.get("current_main") else "") + f", {h['review_date']}.", "",
           made_by(r), "",
           "## Summary", "", "| Section | Count |", "| --- | --- |"]
    out += [f"| {label} | {n[key]} |" for key, label, _ in SECTIONS]
    out += [f"| Security issues, details withheld from this report | {r['security_count']} |", "",
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
            out += ["| ID | Advisory | Severity proposed | On your main |", "| --- | --- | --- | --- |"]
            out += [f"| {i['id']} | {i['title']} | {_sev(i)} | {i.get('on_main', 'not checked')} |" for i in rows]
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
            how = ("its failing test now passes, and no other test newly fails" if p.get("hidden_test", True)
                   else "it applies cleanly and no test newly fails; there is no failing test for this one")
            status = how if p["status"] == "passes" else p["status"].replace("_", " ")
            out += [f"Hand-made fix, rechecked on current main: {status}.", "",
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


# --- blocks for a Marqov document ------------------------------------------------
#
# Marqov lists a document's sections in a contents sidebar on its share page. A section
# is a block holding only a "## Heading" line, so every H2 here is its own block.
# Charts are text bars, which follow the reader's light or dark theme and stay at text
# width. "{{top}}" is replaced after upload with the anchor of the first section.

CTA_URL = "https://marqov.ai/request-access"
TOP = "{{top}}"
BAR_WIDTH = 16


def bar(n: int, top: int) -> str:
    if not top or not n:
        return ""
    return "▇" * max(1, round(BAR_WIDTH * n / top))


def _h2(title: str) -> tuple[str, str]:
    return ("markdown", f"## {title}")


def _back_to_top() -> tuple[str, str]:
    return ("markdown", f"[↑ Back to top](#{TOP})")


def _checks(i: dict) -> list[str]:
    g, c, x = i["section"], i["challenge"], i["fix_gate"]
    if g == "fixed_upstream":
        rows = ["✅ Fails at the reviewed commit", "✅ Passes on your current main"]
    elif g == "untested":
        rows = ["➖ No test passed our gates"]
    else:
        rows = ["✅ Fails reliably, also on your current main"]
    rows += {"upheld": ["✅ Challengers could not break the test"],
             "refuted": ["❌ Challengers showed the test is wrong"],
             "unsettled": ["⚠️ Challenge unsettled"]}.get(c, [])
    n = sum(1 for v in i["views"] if v["stage"] == "blind fix" and "fix passes" in v["verdict"])
    m = sum(1 for v in i["views"] if v["stage"] == "blind fix")
    rows += {"confirmed": [f"✅ Blind fix passed ({n} of {m})"],
             "not_confirmed": ["❌ No blind fix passed"],
             "disputed": ["❌ Fixers say it is not a defect"],
             "unsettled": ["⚠️ Blind fix unsettled"]}.get(x, [])
    return [f"- {r}" for r in rows]


def _card(i: dict) -> str:
    out = [f"### {i['id']} · {i['title']}", "",
           f"`{i['location']}` · {i['area']} · found by {', '.join(_src(s) for s in i['found_by'])}", "",
           f"**Severity proposed:** {_sev(i).replace(', ', ' · ')}", "",
           "> " + _clip(i["claim"], 500), "", "**Checks**", "", *_checks(i), ""]
    if i["raised_before"]:
        out += [f"Raised before: {', '.join(i['raised_before'])}", ""]
    if i["section"] in ("disagree", "untested", "weak"):
        out += ["**What each model said**", ""]
        out += [f"- *{v['stage']}, {_src(v['model'])}:* **{v['verdict']}**. {_clip(v['reason'], 260)}" for v in i["views"]]
        out.append("")
    fixes = [s for s in (i["fix"] and f"a blind fix by {_src(i['fix']['by'])}", i.get("prior_fix") and "a hand-made fix") if s]
    if fixes:
        out += [f"🔧 **Ready to apply:** {' and '.join(fixes)}, in the evidence document under {i['id']}.", ""]
    elif i["test"]:
        out += [f"🧪 The test is in the evidence document under {i['id']}.", ""]
    out.append("**Your verdict?** real · not real · intended behaviour (reply with the ID)")
    return "\n".join(out)


def _top_severity(i: dict) -> str:
    return i["severity"][0]["value"] if i["severity"] else "–"


def to_blocks(r: dict, charts: dict | None = None) -> list[tuple[str, object]]:
    """The report as Marqov blocks: ("markdown", text)."""
    h, n = r["header"], r["counts"]
    ready = sum(1 for i in r["items"] if i["fix"] or i.get("prior_fix"))
    rows = [("Likely defects", n["likely"]), ("Models disagree", n["disagree"]), ("Could not test", n["untested"]),
            ("Probably not defects", n["weak"]), ("Fixed on your main", n["fixed_upstream"]),
            ("Dependency advisories", n["advisory"]), ("Security issues, details withheld", r["security_count"])]
    top = max(c for _, c in rows) or 1
    parts: list[tuple[str, object]] = [("markdown", "\n".join([
        f"# {r['title']}", "",
        f"Reviewed commit `{h['commit'][:12]}`" + (f", rechecked on your current main `{h['current_main'][:12]}`"
                                                   if h.get("current_main") else "") + f" · {h['review_date']}"]))]
    parts += [_h2("At a glance"), ("markdown", "\n".join([
        f"- **{n['likely']} likely defects**, each with a failing test and a fix written without seeing that test.",
        f"- **{n['disagree']} where the models disagree**: often a sign the intended behaviour is unclear.",
        f"- 🔧 **{ready} fixes ready to apply**, in the evidence document.", "",
        "| Where the findings landed | Count |", "| --- | --- |",
        *[f"| {label} | {bar(c, top)} {c} |" for label, c in rows], "",
        "The first four rows run from the strongest evidence to the weakest.", "",
        made_by(r), "",
        "Security issues are counted only. Their details are not in this report; under our disclosure policy they "
        "are reported to you privately."]))]
    parts += [_h2("How to read this report"), ("markdown", "\n".join([
        "Each finding sits in a section by the strength of its evidence, strongest first. Each card shows the claim, "
        "its checks (✅ passed, ⚠️ unsettled, ❌ failed), and where to find its test and fix.", "",
        f"- **{SECTIONS[0][1]}:** every automatic check agrees.",
        f"- **{SECTIONS[1][1]}:** each model's view is on the card.",
        f"- **{SECTIONS[2][1]}:** the models' reading of the code only.",
        f"- **{SECTIONS[3][1]}:** listed so nothing is hidden.", "",
        f"{r.get('hand_review_only', 0)} of the items came from an earlier review of this repository by hand at "
        "Marqov; the models then checked, tested and fixed them like everything else. Severities are proposals, "
        "labelled with who proposed them.", "",
        "**What we ask:** for any item you look at, a one-word verdict (real, not real or intended behaviour) "
        "with its ID. It tells us which checks were right, and improves the next review."]))]
    for key, label, blurb in SECTIONS:
        items = [i for i in r["items"] if i["section"] == key]
        if not items:
            continue
        parts.append(_h2(f"{label} ({len(items)})"))
        if key == "advisory":
            parts.append(("markdown", "\n".join([blurb, "", "| Advisory | Severity | On your main |", "| --- | --- | --- |"]
                                                + [f"| {i['title']} · {i['id']} | {_top_severity(i)} | "
                                                   f"{i.get('on_main', 'not checked')} |" for i in items])))
        else:
            parts.append(("markdown", "\n".join([blurb, "", "| Finding | Severity | Fix |", "| --- | --- | --- |"]
                                                + [f"| {i['title']} · {i['id']} | {_top_severity(i)} | "
                                                   f"{'🔧' if i['fix'] or i.get('prior_fix') else ''} |" for i in items])))
            parts += [("markdown", _card(i)) for i in items]
        parts.append(_back_to_top())
    order = ("claude", "codex", "antigravity", "gemini")
    models = sorted((m for m in r["models"] if m["model"] in order), key=lambda m: order.index(m["model"]))
    frac = lambda a, b: f"{bar(a, b) or '–'} {a} of {b}" if b else "none"
    parts += [_h2("How the models did"), ("markdown", "\n".join(
        ["Measured against the other checks, not yet against your verdicts.", "",
         "| Model | Tests that survived the challenge | Blind fixes that passed |", "| --- | --- | --- |"]
        + [f"| {_src(m['model'])} | {frac(m['tests_upheld'], m['tests_challenged']) if m['tests_challenged'] else 'wrote no tests'} | "
           f"{frac(m['fixes_passed'], m['fixes_attempted'])} |" for m in models] + [""]
        + [f"- **{_src(m['model'])}** raised {m['claims']} claims of its own; {m['claims_likely']} are now likely "
           "defects." for m in models]
        + [f"- **Fixed-rule tools:** " + ", ".join(f"{m['model']} {m['claims']}" for m in r["models"] if m not in models)
           + " leads, checked by the models."])), _back_to_top()]
    parts += [_h2("How this was produced"), ("markdown", "\n".join(
        ["**Models**", ""]
        + [f"- {m['cli']}: {', '.join(m['model_ids']) or 'model id not reported'} ({(m['version'] or '').split(' (sandbox')[0]})"
           for m in h["models"]]
        + ["", "**Tools**", ""] + [f"- {t['name']}: {t['status']}" for t in h["tools"]]
        + ["", f"Method: [quantum-oss-triage]({r['how_produced']['method']}), run `{r['how_produced']['run_id']}`, "
               f"harness `{r['how_produced']['harness_revision']}`. A rerun is not guaranteed to give identical "
               "model answers."]))]
    parts += [_h2("Run this on your own code"), ("markdown", "\n".join([
        "This review ran on Marqov: the run record, every test and fix, and this report sit together in one "
        "Project, so the work can be checked and rerun.", "",
        f"### [Run this on your code with Marqov →]({CTA_URL})", "", f"[↑ Back to top](#{TOP})"]))]
    return parts


def to_evidence_blocks(r: dict) -> list[tuple[str, object]]:
    """One section per finding, so the contents sidebar lists them by ID."""
    head, *rest = to_evidence_markdown(r).split("\n## ")
    parts: list[tuple[str, object]] = [("markdown", head)]
    for b in rest:
        title, _, body = b.partition("\n")
        parts += [_h2(title), ("markdown", body.strip() + f"\n\n[↑ Back to top](#{TOP})")]
    return parts


def blocks_markdown(parts: list) -> str:
    """The blocks joined as one markdown text, for the local outbox."""
    return "\n\n".join(v.replace(f"#{TOP}", "#") for k, v in parts if k == "markdown")
