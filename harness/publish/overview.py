"""The round's main page: which projects are being reviewed, by which models, and how far each has got.

It shows progress only. Findings, counts of findings and security details stay in each
team's private report (docs/DISCLOSURE.md), so this page can be shared widely. It is
rebuilt from the run records on every publish, so it never drifts from what ran.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from harness.publish.tiered import CTA_URL, TOP, _h2, bar

TITLE = "Round one: overview"
METHOD_URL = "https://github.com/marqov-dev/quantum-oss-triage"
MODEL_NAMES = {"claude": "Claude", "codex": "Codex", "antigravity": "Gemini"}

# The steps a reader sees, in order, and the stages behind each.
STEPS = [("Reviewed", ("review",)), ("Cross-checked", ("verify",)), ("Tested", ("validate", "gates")),
         ("Challenged", ("challenge",)), ("Fixed blind", ("fixgate",))]
STEP_TEXT = {
    "Reviewed": "each model reads the code and lists what it believes is wrong",
    "Cross-checked": "the other models check every claim against the code",
    "Tested": "for each claim that can be tested, a failing test is written, rerun and checked on the project's current main",
    "Challenged": "models that did not write a test try to show it is wrong",
    "Fixed blind": "models that never saw the test write a fix, which must make it pass without breaking others",
    "Report": "the team receives a private report, with every model's view shown",
}
_RAN = ("complete", "incomplete")


def _units(repo_dir: Path) -> Counter:
    """(stage, model, status) -> count, from the ledger's unit files."""
    c: Counter = Counter()
    for f in (repo_dir / "units").glob("*__*__*.json"):
        stage, model = f.stem.split("__", 1)[0], f.stem.rsplit("__", 1)[1]
        try:
            status = json.loads(f.read_text()).get("status")
        except (OSError, json.JSONDecodeError):
            continue
        c[(stage, model, status)] += 1
    return c


def model_cell(units: Counter, model: str, owed: dict | None = None) -> str:
    owed = owed or {}
    # Never a count: how many units a step has would reveal how many claims a model made,
    # and unvalidated suspicions are never counted in public (docs/DISCLOSURE.md).
    def counts(stage):
        total = sum(n for (s, m, _), n in units.items() if s == stage and m == model)
        return units[(stage, model, "done")], total
    done, total = counts("review")
    if not total:
        return "not yet"
    if done < total:
        return "review not finished"
    done, total = counts("verify")
    if total and done < total:
        return "cross-check not finished"
    # A step never started leaves no unit file, so missing challenges and blind fixes are
    # found from the records: every test a model did not write needs its challenge and fix.
    if owed.get("challenge"):
        return "challenges to go"
    if owed.get("fixgate"):
        return "blind fixes to go"
    return "✅"


def owed_work(repo_dir: Path, models: list[str]) -> dict[str, dict[str, bool]]:
    """model -> {"challenge": bool, "fixgate": bool}: whether it still owes a challenge or a
    blind fix on some test it did not write. Only booleans: no counts reach this page."""
    out = {m: {"challenge": False, "fixgate": False} for m in models}
    for stage, file, key, who in (("challenge", "challenge.json", "challenges", "challenger"),
                                  ("fixgate", "fixgate.json", "attempts", "fixer")):
        path = repo_dir / file
        if not path.is_file():
            continue
        for f in json.loads(path.read_text()).get("findings", []):
            # An attempt that failed to run (quota, outage) is still owed.
            seen = {a.get(who) for a in f.get(key) or [] if not a.get("failed") and a.get("status") != "failed"}
            for m in models:
                if m != f.get("author") and m not in seen:
                    out[m][stage] = True
    return out


def repo_status(repo_dir: Path, models: list[str], published: dict) -> dict:
    m = json.loads((repo_dir / "manifest.json").read_text())
    stages = m.get("stages", {})
    reached = None
    for label, names in STEPS:
        if all(stages.get(s, {}).get("status") in _RAN for s in names):
            reached = label
        else:
            break
    name = m["repo"]["name"]
    report = "in Marqov" if f"{name}:report" in published else ("being checked" if reached == "Fixed blind" else "–")
    if report == "in Marqov":
        reached = "Report"
    units, owed = _units(repo_dir), owed_work(repo_dir, models)
    return {"repo": name, "reached": reached or "–", "report": report,
            "models": {mo: model_cell(units, mo, owed[mo]) for mo in models}}


def build(run_dir: Path, models: list[str], published: dict) -> dict:
    rows = [repo_status(d.parent, models, published) for d in sorted(Path(run_dir).glob("*/manifest.json"))]
    order = [label for label, _ in STEPS] + ["Report"]
    rows.sort(key=lambda r: (-(order.index(r["reached"]) if r["reached"] in order else -1), r["repo"].lower()))
    funnel = [(label, sum(1 for r in rows if r["reached"] in order[i:])) for i, label in enumerate(order)]
    return {"rows": rows, "models": models, "funnel": funnel}


def to_blocks(s: dict, model_ids: dict | None = None) -> list[tuple[str, str]]:
    rows, models, total = s["rows"], s["models"], len(s["rows"])
    names = [MODEL_NAMES.get(m, m) for m in models]
    parts = [("markdown", "\n".join([
        f"# {TITLE}", "",
        f"Marqov is reviewing {total} open-source quantum computing projects with {len(models)} AI models "
        f"({', '.join(names)}). Each claim a model makes is checked by the others, tested, challenged and, "
        "where it holds, fixed. Each team receives a private report of what was found, with every model's "
        "view shown, including where they disagree.", "",
        "This page shows progress only. Findings stay in each team's private report."]))]
    parts += [_h2("Progress"), ("markdown", "\n".join(
        [f"How many of the {total} projects have reached each step.", "",
         "| Step | Projects |", "| --- | --- |"]
        + [f"| {label} | {bar(n, total) or '–'} {n} of {total} |" for label, n in s["funnel"]]
        + ["", f"[↑ Back to top](#{TOP})"]))]
    model_ids = model_ids or {}
    parts += [_h2("Models"), ("markdown", "\n".join(
        [f"- **{MODEL_NAMES.get(m, m)}**" + (f": `{model_ids[m]}`" if model_ids.get(m) else "") for m in models]
        + ["", "Gemini runs through Google's Antigravity command-line tool. During review no model can change "
               "the code: Claude is limited to tools that read and search it, and Codex and Gemini run in "
               "containers holding a read-only copy."]))]
    parts += [_h2("Projects"), ("markdown", "\n".join(
        ["✅ means the model has finished every step run so far for that project.", "",
         f"| Project | {' | '.join(names)} | Reached | Report |", "| --- |" + " --- |" * (len(models) + 2)]
        + [f"| {r['repo']} | {' | '.join(r['models'][m] for m in models)} | {r['reached']} | {r['report']} |"
           for r in rows]
        + ["", f"[↑ Back to top](#{TOP})"]))]
    parts += [_h2("How each project is reviewed"), ("markdown", "\n".join(
        [f"{i}. **{label}:** {STEP_TEXT[label]}." for i, label in enumerate([l for l, _ in STEPS] + ["Report"], 1)]
        + ["", "Nothing is filed upstream by the harness. Security findings go to each team privately.", "",
           f"The method and the harness are open source: {METHOD_URL}"]))]
    parts += [_h2("Run this on your own code"), ("markdown", "\n".join([
        "The reviews run on Marqov: each project's run record, tests, fixes and report sit together in one "
        "Project, so the work can be checked and rerun.", "",
        f"### [Run this on your code with Marqov →]({CTA_URL})", "", f"[↑ Back to top](#{TOP})"]))]
    return parts
