"""Stage 5d: the separate-fix gate.

For each test that passed gates 1 to 3, every configured model except the one
that wrote the test is shown only the claim, never the test, the finder's
reasoning, who wrote what, or the challenge verdicts. Each first says whether
the claim holds and, if it does, writes the smallest fix. The fix is applied to
a throwaway copy in a worker, where the hidden test must now pass, its control
must still pass, and no test in the packages the fix touches may newly fail
(compared by test id with the same tests before the fix).

Tests the challenge refuted are included: a blind fix that makes a refuted test
pass is evidence that the refutation was wrong. Outcomes by rule:

- confirmed: at least one independent fix makes the test pass, cleanly.
- disputed: every fixer judged the claim not to hold.
- unsettled: no fix passed and at least one fixer could not run (model
  failure, unavailable model, or a check that timed out).
- not_confirmed: anything else. A blind fix that fails is weak evidence, so this
  does not refute the test; it only withholds confirmation.

Results go to fixgate.json; finding records and decisions are untouched.
Nothing is pushed anywhere.
"""

from __future__ import annotations

import re
import shlex
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from harness import secrets
from harness.controller import merge, prompts, skills
from harness.controller.context import RepoContext
from harness.stages.fix import EditError, build_diff
from harness.stages.validate import _PYTEST

_TEST_PATH = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$")
_IDS = re.compile(r"^QOT_(BEFORE|AFTER) ((?:FAILED|ERROR) \S+)", re.MULTILINE)
# Statuses where the fixer could not be heard: the test stays unsettled.
_NOT_RUN = ("failed", "timed_out")


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


def targets(paths: list[str]) -> list[str]:
    """The folders whose tests check a fix: the folder of each changed Python file, outermost only.

    A change at the repository root targets the whole suite.
    """
    dirs = {str(PurePosixPath(p).parent) for p in paths if p.endswith(".py")}
    if "." in dirs:
        return ["."]
    return sorted(d for d in dirs if not any(d.startswith(o + "/") for o in dirs if o != d))


def check_script(target_dirs: list[str]) -> str:
    t = " ".join(shlex.quote(d) for d in target_dirs)
    ids = "grep -E '^(FAILED|ERROR) ' {f} | sed -E 's/ - .*//' | sort -u | sed 's/^/QOT_{w} /'; "
    # The run before the fix leaves bytecode caches; a same-size edit made within the same
    # second would then be ignored, so write none and clear any the snapshot carries.
    s = ("export PYTHONDONTWRITEBYTECODE=1; d=$(mktemp -d); "
         "find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null; ")
    if t:
        s += f"{_PYTEST} -rfE {t} >$d/b.txt 2>&1; echo QOT_BEFORE_RC=$?; " + ids.format(f="$d/b.txt", w="BEFORE")
    # As in the fix stage, fall back to --recount when hunk line counts are off.
    s += ("{ git apply --whitespace=nowarn /inputs/fix.diff || git apply --recount --whitespace=nowarn /inputs/fix.diff; } "
          ">$d/a.txt 2>&1; rc=$?; echo QOT_APPLY_RC=$rc; cat $d/a.txt; "
          "if [ $rc -eq 0 ]; then "
          f"{_PYTEST} /inputs/test_qot_control.py >$d/c.txt 2>&1; echo QOT_CONTROL_RC=$?; "
          f"{_PYTEST} /inputs/test_qot_repro.py >$d/r.txt 2>&1; echo QOT_REPRO_RC=$?; "
          "echo ---REPRO---; tail -n 40 $d/r.txt; ")
    if t:
        s += f"{_PYTEST} -rfE {t} >$d/t.txt 2>&1; echo QOT_AFTER_RC=$?; " + ids.format(f="$d/t.txt", w="AFTER")
    return s + "fi; rm -rf $d"


def judge_attempt(stdout: str, timed_out: bool) -> dict:
    if timed_out:
        return {"status": "timed_out", "new_failures": []}
    if "QOT_APPLY_RC=0" not in stdout:
        return {"status": "apply_failed", "new_failures": []}
    before = {m.group(2) for m in _IDS.finditer(stdout) if m.group(1) == "BEFORE"}
    after = {m.group(2) for m in _IDS.finditer(stdout) if m.group(1) == "AFTER"}
    new = sorted(after - before)
    if "QOT_CONTROL_RC=0" not in stdout:
        status = "control_broken"
    elif "QOT_REPRO_RC=0" not in stdout:
        status = "still_fails"
    elif new:
        status = "regressed"
    else:
        status = "passes"
    return {"status": status, "new_failures": new}


def outcome(attempts: list[dict]) -> tuple[str, str]:
    if not attempts:
        return "unsettled", "no fixer was available"
    n = len(attempts)
    passes = sum(x["status"] == "passes" for x in attempts)
    dissent = sum(x["claim_holds"] == "no" for x in attempts)
    if passes:
        extra = f"; {dissent} judged the claim not to hold" if dissent else ""
        return "confirmed", f"{passes} of {n} independent fixes make the test pass{extra}"
    if any(x["status"] in _NOT_RUN for x in attempts):
        return "unsettled", f"{sum(x['status'] in _NOT_RUN for x in attempts)} of {n} fixers could not be run"
    if dissent == n:
        return "disputed", f"all {n} fixers judged the claim not to hold"
    return "not_confirmed", "no independent fix made the test pass"


def _edits_error(edits: list[dict]) -> str | None:
    bad = sorted({e["path"] for e in edits if is_test_path(e["path"])})
    return f"edits touch test files ({', '.join(bad)}); fix the code, not the tests" if bad else None


def attempt(ctx: RepoContext, fid: str, model: str, claim: dict, test_dir: Path, available: set) -> dict:
    rec = {"fixer": model, "model_id": None, "claim_holds": None}
    check_unit = ctx.ledger.unit(ctx.spec.name, "fixgate-check", fid, model)
    if check_unit.done():
        return check_unit.payload()
    if model not in available and not ctx.ledger.unit(ctx.spec.name, "fixgate", fid, model).done():
        return {**rec, "status": "failed", "notes": "model not available in this run"}
    skill = skills.load("blind-fix")
    prompt = prompts.blind_fix(skill, ctx.spec.name, ctx.commit, claim)
    out = ctx.repo_dir / "fixgate" / fid / model
    diff, problem = None, None
    for unit_id, p in ((fid, prompt), (f"{fid}-retry", None)):
        if p is None:
            p = prompt + f"\n\nYour previous edits could not be used: {problem}. Copy `old` text exactly from the file."
        call = ctx.call_model("fixgate", unit_id, model, "blind-fix", p, ctx.config.timeouts["fix_s"])
        if not call.ok:
            return {**rec, "status": "failed", "notes": call.error or "failed"}
        prop = call.payload
        rec.update(model_id=call.model_id, claim_holds=prop["claim_holds"], summary=prop["summary"],
                   notes=prop["notes"], unit=call.unit)
        if prop["claim_holds"] == "no":
            return _done(check_unit, {**rec, "status": "not_a_defect"})
        if not prop["feasible"] or not prop["edits"]:
            return _done(check_unit, {**rec, "status": "not_feasible"})
        try:
            if problem := _edits_error(prop["edits"]):
                raise EditError(problem)
            diff = build_diff(ctx, fid, prop["edits"], tree=out / "tree")
            break
        except EditError as e:
            problem = str(e)
    if diff is None:
        return _done(check_unit, {**rec, "status": "edits_invalid", "notes": problem})
    files = sorted({e["path"] for e in prop["edits"]})
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "fix.diff").write_text(diff)
    for name in ("test_qot_repro.py", "test_qot_control.py"):
        shutil.copyfile(test_dir / name, inputs / name)
    dirs = targets(files)
    timeout_s = max(900, 2 * (ctx.spec.tests_timeout_s or 0) + 600)
    r = ctx.worker.run(check_script(dirs), ctx.source_dir, inputs=inputs, timeout_s=timeout_s)
    (out / "worker-output.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
    # The worker checked the real diff; what is kept has secrets redacted.
    stored = secrets.redact(diff)
    for p in (out / "fix.diff", inputs / "fix.diff"):
        p.write_text(stored)
    rec.update(judge_attempt(r.stdout, r.timed_out), files_changed=files, targets=dirs,
               diff_ref=str((out / "fix.diff").relative_to(ctx.run_dir)), diff_redacted=stored != diff)
    return rec if rec["status"] == "timed_out" else _done(check_unit, rec)


def _done(unit, rec: dict) -> dict:
    unit.save("done", rec)
    return rec


def run(ctx: RepoContext) -> list[dict]:
    worker_ok, why = ctx.worker.available() if ctx.worker else (False, "no worker")
    if not worker_ok:
        ctx.manifest.incomplete(f"fixgate: worker unavailable: {why}")
        return []
    gates = ctx.read_json("gates.json", {}).get("findings", [])
    groups = {g["id"]: g for g in ctx.read_json("groups.json", [])}
    challenged = {c["id"]: c["outcome"] for c in ctx.read_json("challenge.json", {}).get("findings", [])}
    models, available = list(ctx.config.models), set(ctx.model_order())
    todo = []
    for gf in gates:
        g = groups.get(gf["id"])
        if gf["verdict"] != "passed" or not g or not gf.get("evidence_ref"):
            continue
        test_dir = ctx.run_dir / gf["evidence_ref"]
        author = g["reproductions"][int(test_dir.name)]["by"]
        todo.append((gf["id"], author, gf["evidence_ref"], test_dir, merge.representative(g["candidates"]),
                     [m for m in models if m != author]))
    jobs = [(fid, m, claim, test_dir) for fid, _, _, test_dir, claim, fixers in todo for m in fixers]
    with ThreadPoolExecutor(max_workers=max(1, ctx.config.parallel)) as pool:
        done = list(pool.map(lambda j: (j[0], attempt(ctx, j[0], j[1], j[2], j[3], available)), jobs))
    by_id: dict[str, list] = {fid: [] for fid, *_ in todo}
    for fid, rec in done:
        by_id[fid].append(rec)
    results = []
    for fid, author, ref, _, _, _ in todo:
        result, reason = outcome(by_id[fid])
        results.append({"id": fid, "author": author, "evidence_ref": ref, "challenge": challenged.get(fid),
                        "outcome": result, "reason": reason, "attempts": by_id[fid]})
    ctx.write_json("fixgate.json", {"rule": "confirmed if any blind fix makes the hidden test pass with its control "
                                            "and no new failures in the touched packages; disputed if every fixer "
                                            "says the claim does not hold; unsettled if a fixer could not run; "
                                            "else not_confirmed",
                                    "findings": results})
    not_run = sum(x["status"] in _NOT_RUN for _, x in done)
    if not_run:
        ctx.manifest.incomplete(f"fixgate: {not_run} of {len(jobs)} attempts could not run (shown as unsettled)")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    ctx.manifest.stage("fixgate", "complete" if not not_run else "incomplete", attempts=len(jobs),
                       attempts_not_run=not_run, **counts)
    return results
