"""Stage 7: fixes for accepted findings only.

One model writes the fix as exact search-and-replace edits, the harness turns
them into a diff with git, and the other models review it. The fix is applied to a
throwaway copy in a worker, where the reproduction must now pass and the
existing tests must not regress. Nothing is pushed: non-security fixes get a
planned branch that waits for explicit approval, and security fixes are
exported only as a private .patch file.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from harness import secrets
from harness.controller import prompts, skills
from harness.controller.context import RepoContext
from harness.stages.validate import _PYTEST


def worker_script(has_repro: bool) -> str:
    # Models sometimes get hunk line counts wrong, so fall back to --recount.
    # It is only a fallback: on some valid diffs --recount itself fails.
    s = ("{ git apply --whitespace=nowarn /inputs/fix.diff || git apply --recount --whitespace=nowarn /inputs/fix.diff; } "
         ">/tmp/a.txt 2>&1; rc=$?; echo QOT_APPLY_RC=$rc; cat /tmp/a.txt; [ $rc -eq 0 ] || exit 0; ")
    if has_repro:
        s += f"{_PYTEST} /inputs/test_qot_repro.py >/tmp/r.txt 2>&1; echo QOT_REPRO_RC=$?; tail -n 30 /tmp/r.txt; "
    # `ls tests test` fails when either folder is missing, so test each one.
    s += (f"if [ -d tests ] || [ -d test ] || ls test_*.py >/dev/null 2>&1; then {_PYTEST} >/tmp/t.txt 2>&1; "
          "echo QOT_TESTS_RC=$?; tail -n 1 /tmp/t.txt | sed 's/^/QOT_TESTS_SUMMARY=/'; else echo QOT_TESTS_RC=none; fi")
    return s


def _counts(summary: str) -> dict:
    return {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|errors?)", summary or "")}


def check_in_worker(ctx: RepoContext, fid: str, diff: str, repro_code: str | None) -> dict:
    inputs = ctx.repo_dir / "fixes" / fid / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "fix.diff").write_text(diff if diff.endswith("\n") else diff + "\n")
    if repro_code:
        (inputs / "test_qot_repro.py").write_text(repro_code)
    r = ctx.worker.run(worker_script(bool(repro_code)), ctx.source_dir, inputs=inputs, timeout_s=900)
    (inputs.parent / "worker-output.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
    out = r.stdout
    applied = "QOT_APPLY_RC=0" in out
    repro = re.search(r"QOT_REPRO_RC=(\d+)", out)
    tests = re.search(r"QOT_TESTS_SUMMARY=(.*)", out)
    baseline = (ctx.read_json("scan-summary.json", {}).get("project-tests") or {}).get("hygiene", {})
    after = _counts(tests.group(1)) if tests else {}
    regressed = bool(tests) and (after.get("failed", 0) > baseline.get("failed", 0)
                                 or after.get("passed", 0) < baseline.get("passed", 0))
    return {"applied": applied, "timed_out": r.timed_out,
            "repro_passes": (repro.group(1) == "0") if repro else None,
            "tests_after": tests.group(1) if tests else "no tests run",
            "tests_baseline": baseline.get("summary", "none"), "tests_regressed": regressed}


class EditError(ValueError):
    pass


def build_diff(ctx: RepoContext, fid: str, edits: list[dict]) -> str:
    """Apply search-and-replace edits to a temporary clone and return git's diff.

    Only text operations happen on the host; nothing from the repository runs.
    """
    from harness.stages.pin import git

    tree = ctx.repo_dir / "fixes" / fid / "tree"
    if tree.exists():
        shutil.rmtree(tree)
    tree.parent.mkdir(parents=True, exist_ok=True)
    git(["clone", "--quiet", "--no-hardlinks", "--no-recurse-submodules", str(ctx.source_dir), str(tree)])
    try:
        root = tree.resolve()
        created = []
        for i, e in enumerate(edits, 1):
            rel = Path(e["path"])
            target = (tree / rel).resolve()
            if rel.is_absolute() or ".." in rel.parts or not str(target).startswith(str(root) + "/") \
                    or rel.parts[:1] == (".git",) or (tree / rel).is_symlink():
                raise EditError(f"edit {i}: path {e['path']!r} is outside the repository")
            if e["old"] == "":
                if target.exists():
                    raise EditError(f"edit {i}: {e['path']} already exists; to change it, give the exact old text")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(e["new"])
                created.append(str(rel))
                continue
            if not target.is_file():
                raise EditError(f"edit {i}: {e['path']} does not exist")
            text = target.read_text()
            n = text.count(e["old"])
            if n != 1:
                raise EditError(f"edit {i}: the old text occurs {n} times in {e['path']}; it must occur exactly once")
            target.write_text(text.replace(e["old"], e["new"], 1))
        if created:
            git(["add", "--intent-to-add", "--", *created], cwd=tree)
        diff = git(["diff", "--no-color", "--no-ext-diff", "--no-textconv"], cwd=tree)
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    if not diff.strip():
        raise EditError("the edits change nothing")
    return diff + "\n"


def fix_one(ctx: RepoContext, f: dict) -> dict:
    order = ctx.model_order()
    if not order:
        return {"status": "pending", "notes": "no model available"}
    proposer = order[0]
    repro_code = None
    if f["validation"]["status"] == "reproduced" and f["validation"].get("evidence_ref"):
        repro_code = (ctx.run_dir / f["validation"]["evidence_ref"] / "test_qot_repro.py").read_text()
    call = ctx.call_model("fix", f["id"], proposer, "propose-fix",
                          prompts.propose_fix(skills.load("propose-fix"), ctx.spec.name, ctx.commit, f,
                                              {"test_code": repro_code} if repro_code else None),
                          ctx.config.timeouts["fix_s"])
    if not call.ok:
        return {"status": "proposal_failed", "proposer": proposer, "notes": call.error or ""}
    prop = call.payload
    if not prop["feasible"] or not prop["edits"]:
        return {"status": "not_feasible", "proposer": proposer, "notes": prop["notes"]}
    try:
        diff = build_diff(ctx, f["id"], prop["edits"])
    except EditError as e:
        # One retry, telling the model exactly what did not fit.
        prompt = prompts.propose_fix(skills.load("propose-fix"), ctx.spec.name, ctx.commit, f,
                                     {"test_code": repro_code} if repro_code else None)
        prompt += f"\n\nYour previous edits could not be applied: {e}. Copy `old` text exactly from the file."
        call = ctx.call_model("fix", f"{f['id']}-retry", proposer, "propose-fix", prompt, ctx.config.timeouts["fix_s"])
        if not call.ok:
            return {"status": "proposal_failed", "proposer": proposer, "notes": call.error or ""}
        prop = call.payload
        if not prop["feasible"] or not prop["edits"]:
            return {"status": "not_feasible", "proposer": proposer, "notes": prop["notes"]}
        try:
            diff = build_diff(ctx, f["id"], prop["edits"])
        except EditError as e2:
            return {"status": "edits_invalid", "proposer": proposer, "notes": str(e2)}
    prop = {**prop, "diff": diff, "files_changed": sorted({e["path"] for e in prop["edits"]})}
    fix_dir = ctx.repo_dir / "fixes" / f["id"]
    fix_dir.mkdir(parents=True, exist_ok=True)
    (fix_dir / "fix.diff").write_text(prop["diff"])
    worker_ok, why = ctx.worker.available() if ctx.worker else (False, "no worker")
    check = check_in_worker(ctx, f["id"], prop["diff"], repro_code) if worker_ok else {"applied": None, "note": why}

    others = [m for m in order if m != proposer]
    reviewers = [(m, "independent") for m in others] or [(proposer, "same_model")]
    reviews = []
    for model, independence in reviewers:
        rc = ctx.call_model("verify-fix", f["id"], model, "verify-fix",
                            prompts.verify_fix(skills.load("verify-fix"), ctx.spec.name, ctx.commit, f, prop["diff"]),
                            ctx.config.timeouts["verify_s"])
        reviews.append({"verifier": model, "independence": independence,
                        "verdict": rc.payload["verdict"] if rc.ok else "failed",
                        "reason": rc.payload["reason"] if rc.ok else (rc.error or ""),
                        "fix_assessment": rc.payload.get("fix_assessment") if rc.ok else None})

    independent = [r for r in reviews if r["independence"] == "independent"]
    # A reviewer who agrees the fix removes the cause but says it changes
    # behaviour (pickle -> JSON changes the wire format) leaves a caveat that
    # travels with the fix, whatever its status.
    caveats = [{"by": r["verifier"], "text": r["fix_assessment"].get("regression_risk") or r["reason"]}
               for r in reviews if (r.get("fix_assessment") or {}).get("fixes_cause") == "yes"
               and r["fix_assessment"].get("keeps_behaviour") != "yes"]
    objections = [r for r in reviews if r["verdict"] in ("refute", "unsure", "failed")]
    if not worker_ok:
        status = "pending"
    elif not check["applied"]:
        status = "apply_failed"
    elif repro_code and not check["repro_passes"]:
        status = "repro_still_fails"
    elif check["tests_regressed"]:
        status = "tests_regressed"
    elif objections:
        status = "pending_objections"
    elif not independent:
        status = "checked_same_model_only"
    else:
        status = "validated"
    sensitive = f["sensitivity"]["sensitive"]
    # The worker has checked the real diff; what is stored has secrets redacted.
    # A redacted diff that removes a secret no longer applies as is: regenerate
    # it from the reviewed commit before sending it privately.
    stored = secrets.redact(prop["diff"])
    for p in (fix_dir / "fix.diff", fix_dir / "inputs" / "fix.diff"):
        if p.exists():
            p.write_text(stored)
    rec = {"status": status, "proposer": proposer, "diff_redacted": stored != prop["diff"], "proposer_model_id": call.model_id, "summary": prop["summary"],
           "files_changed": prop["files_changed"], "diff_ref": str((fix_dir / "fix.diff").relative_to(ctx.run_dir)),
           "worker_check": check, "reviews": reviews, "caveats": caveats}
    if sensitive:
        patch = ctx.repo_dir / "evidence" / "patches" / f"{f['id']}.patch"
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(stored)
        rec["delivery"] = {"kind": "private_patch", "path": str(patch.relative_to(ctx.run_dir)),
                           "note": "security fixes are never pushed; attach to the private vulnerability report"}
    else:
        rec["delivery"] = {"kind": "fork_branch", "branch": f"{ctx.config.fix_branch_prefix}{f['id']}",
                           "status": "awaiting explicit approval to publish", "pushed": False}
    return rec


def run(ctx: RepoContext) -> list[dict]:
    findings = ctx.read_json("findings.json", [])
    accepted = [f for f in findings if f["disposition"]["decision"] == "accept"]
    for f in accepted:
        # Rechecking is cheap: the proposal and reviews are cached units.
        if f.get("fix") and f["fix"].get("status") not in (None, "pending", "proposal_failed", "apply_failed", "edits_invalid"):
            continue
        ctx.log(f"  fix {f['id']} ...")
        f["fix"] = fix_one(ctx, f)
        ctx.write_json("findings.json", findings)
    ctx.manifest.stage("fix", "complete", accepted=len(accepted),
                       statuses={s: sum((f.get("fix") or {}).get("status") == s for f in accepted)
                                 for s in {(f.get("fix") or {}).get("status") for f in accepted}})
    return accepted
