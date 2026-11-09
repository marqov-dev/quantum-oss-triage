"""Stage 5: behavioural validation in a worker, then merge into finding records.

A reproduction counts only if the expected behaviour is justified
independently, the reviewed commit fails for the claimed reason, and a control
case passes. Install or import failures prove nothing.
"""

from __future__ import annotations

import hashlib
import json
import re

from harness.stages import deps
from harness.controller import merge, schema
from harness.controller.context import RepoContext

_PYTEST = "python -m pytest -q -p no:cacheprovider -o addopts= --no-header"
_ASSERTION = re.compile(r"AssertionError|^E\s+assert\b|^E\s+Failed: ", re.MULTILINE)
_NOT_A_REPRO = re.compile(r"ModuleNotFoundError|ImportError|SyntaxError|IndentationError|fixture '.*' not found")


def repro_script() -> str:
    return (f"{_PYTEST} /inputs/test_qot_control.py >/tmp/c.txt 2>&1; echo QOT_CONTROL_RC=$?; "
            f"{_PYTEST} /inputs/test_qot_repro.py >/tmp/r.txt 2>&1; echo QOT_REPRO_RC=$?; "
            "echo ---CONTROL---; tail -n 30 /tmp/c.txt; echo ---REPRO---; tail -n 60 /tmp/r.txt")


def _rc(out: str, name: str) -> int | None:
    m = re.search(rf"QOT_{name}_RC=(\d+)", out)
    return int(m.group(1)) if m else None


def judge(stdout: str, timed_out: bool) -> tuple[str, str]:
    if timed_out:
        return "blocked", "reproduction timed out"
    control, repro = _rc(stdout, "CONTROL"), _rc(stdout, "REPRO")
    repro_out = stdout.split("---REPRO---", 1)[-1]
    if control != 0:
        return "blocked", f"control case did not pass (exit {control}); the test harness is not trustworthy here"
    if repro == 0:
        return "not_reproduced", "the reproduction passed at the reviewed commit, so it does not show the defect"
    if repro != 1 or _NOT_A_REPRO.search(repro_out):
        return "blocked", f"the reproduction errored rather than failed (exit {repro}); errors prove nothing"
    if not _ASSERTION.search(repro_out):
        return "blocked", "the reproduction failed with an exception, not an assertion about behaviour"
    return "reproduced", "the reproduction fails at the reviewed commit and the control passes"


def inputs_key(g: dict) -> str:
    """What a validation depends on: the tests proposed for the group, in order."""
    tests = [[rp["by"], rp["test_code"], rp["control_code"]] for rp in g["reproductions"]]
    return hashlib.sha256(json.dumps(tests).encode()).hexdigest()[:16]


def _still_valid(rec: dict, g: dict, key: str) -> bool:
    if "inputs" in rec:
        return rec["inputs"] == key
    # Saved before validations recorded their inputs. A reproduced result stands; one that
    # saw fewer tests than the group now has (a model that joined later) is redone.
    result = rec.get("payload") or {}
    if result.get("status") == "reproduced":
        return True
    seen = len(((result.get("reproduction") or {}).get("attempts")) or [])
    return seen >= len(g["reproductions"])


def validate_group(ctx: RepoContext, g: dict) -> dict:
    unit = ctx.ledger.unit(ctx.spec.name, "validate", g["id"], None)
    key = inputs_key(g)
    rec = unit.load()
    if rec and rec.get("status") == "done" and _still_valid(rec, g, key):
        return rec["payload"]
    sensitive = any(c["area"] == "security" or c.get("security_impact") for c in g["candidates"])
    if not g["reproductions"]:
        pending = any(v["verdict"] in ("pending", "failed") for v in g["verifications"])
        note = ("security validation needs a documented technical inspection by a person" if sensitive
                else "no reproduction was proposed")
        result = {"status": "pending" if pending else "unvalidated", "method": None, "evidence_ref": None,
                  "notes": note, "reproduction": None}
        unit.save("pending" if pending else "done", result, extra={"inputs": key})
        return result
    worker_ok, why = ctx.worker.available() if ctx.worker else (False, "no worker")
    if worker_ok and (problem := deps.environment_problem(ctx)):
        worker_ok, why = False, problem
    if not worker_ok:
        result = {"status": "blocked", "method": "reproduction", "evidence_ref": None,
                  "notes": f"worker unavailable: {why}", "reproduction": None}
        unit.save("pending", result)  # rerun once a worker is available
        return result
    attempts = []
    result = None
    for i, rp in enumerate(g["reproductions"]):
        inputs = ctx.repo_dir / "evidence" / "repro" / g["id"] / str(i)
        inputs.mkdir(parents=True, exist_ok=True)
        (inputs / "test_qot_repro.py").write_text(rp["test_code"])
        (inputs / "test_qot_control.py").write_text(rp["control_code"])
        r = ctx.worker.run(repro_script(), ctx.source_dir, inputs=inputs, timeout_s=300)
        (inputs / "output.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
        status, why = judge(r.stdout, r.timed_out)
        attempts.append({"by": rp["by"], "status": status, "why": why})
        result = {"status": status, "method": "reproduction",
                  "evidence_ref": str(inputs.relative_to(ctx.run_dir)),
                  "notes": why + (f" (proposed by {rp['by']}, {rp['independence']} verifier)"),
                  "reproduction": {"by": rp["by"], "expected_behaviour_source": rp["expected_behaviour_source"],
                                   "claimed_failure": rp["claimed_failure"], "attempts": attempts}}
        if status == "reproduced":
            break
    unit.save("done", result, extra={"inputs": key})
    return result


def run(ctx: RepoContext, groups: list[dict]) -> list[dict]:
    previous = {f["id"]: f for f in ctx.read_json("findings.json", [])}
    records = []
    for g in groups:
        validation = validate_group(ctx, g)
        rec = merge.build_record(ctx.spec.name, ctx.commit, g["id"], g["candidates"], g["verifications"], validation,
                                 ctx.source_dir)
        old = previous.get(rec["id"])
        if old:  # a rerun keeps what a person already decided
            rec["disposition"] = {**rec["disposition"], **{k: v for k, v in old["disposition"].items() if k != "queue" and k != "queue_reason"}}
            rec["severity"]["final"], rec["severity"]["set_by"] = old["severity"]["final"], old["severity"]["set_by"]
            rec["fix"] = old.get("fix")
            if old["sensitivity"].get("removal_reason") or "set by reviewer" in old["sensitivity"]["reasons"]:
                rec["sensitivity"] = old["sensitivity"]
        for err in schema.validate("finding", rec):
            ctx.manifest.fail(f"{ctx.spec.name}/validate/{rec['id']}", f"finding record invalid: {err}")
        records.append(rec)
    ids = {r["id"] for r in records}
    for fid, old in previous.items():
        if fid not in ids and old["disposition"]["decision"] != "pending":
            ctx.manifest.incomplete(f"validate: decided finding {fid} is no longer produced; recheck decisions.yaml")
    records.sort(key=lambda r: (r["disposition"]["queue"] != "main", merge.SEVERITY_ORDER.index(merge.top_proposed_severity(r))))
    ctx.write_json("findings.json", records)
    ctx.manifest.stage("validate", "complete", findings=len(records),
                       main_queue=sum(r["disposition"]["queue"] == "main" for r in records),
                       reproduced=sum(r["validation"]["status"] == "reproduced" for r in records))
    return records
