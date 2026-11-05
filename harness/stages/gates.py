"""Stage 5b: automatic gates on findings that a reproduction supports.

Gates decide by rule, with no model calls:

1. Evidence: a reproduction failed on an assertion, or raised an exception in
   the project's own code while its control passed ("crash candidate").
2. Stable: rerun in fresh processes, the control passes and the reproduction
   fails the same way every time.
3. Still present: the same test still fails the same way on the project's
   current default branch. The latest release is recorded for information.

The fourth gate, a fix written in a separate session making the test pass,
is its own stage (fixgate.py), after the challenge. Results go to gates.json beside findings.json, so finding
records and a person's decisions are untouched.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.controller.context import RepoContext
from harness.stages import pin
from harness.stages.validate import _ASSERTION, _NOT_A_REPRO, _PYTEST, judge, repro_script

RERUNS = 20
# A pytest location line for a file given by a relative path: code under /work,
# the project's own tree. Dependencies (/deps) and the test files (/inputs) are absolute.
_PROJECT_FRAME = re.compile(r"^(?!/)[\w./-]+\.py:\d+:", re.MULTILINE)
_FIRST_ERROR = re.compile(r"^E\s+(.+)$", re.MULTILINE)


def evidence(stdout: str, timed_out: bool) -> str:
    """'assertion', 'crash' or 'none', from one reproduction output."""
    status, _ = judge(stdout, timed_out)
    if status == "reproduced":
        return "assertion"
    if timed_out or "QOT_CONTROL_RC=0" not in stdout or "QOT_REPRO_RC=1" not in stdout:
        return "none"
    repro_out = stdout.split("---REPRO---", 1)[-1]
    if _NOT_A_REPRO.search(repro_out) or _ASSERTION.search(repro_out):
        return "none"
    return "crash" if _PROJECT_FRAME.search(repro_out) else "none"


def _norm(line: str) -> str:
    return re.sub(r"0x[0-9a-f]+", "0x", re.sub(r"^E\s+", "", line.strip()))[:200]


def signature(stdout: str) -> str:
    """The first pytest error line of the reproduction, with addresses removed."""
    m = _FIRST_ERROR.search(stdout.split("---REPRO---", 1)[-1])
    return _norm(m.group(0)) if m else ""


def rerun_script(n: int) -> str:
    return (f"for i in $(seq {n}); do "
            f"{_PYTEST} /inputs/test_qot_control.py >/tmp/c.txt 2>&1; c=$?; "
            f"{_PYTEST} /inputs/test_qot_repro.py >/tmp/r.txt 2>&1; r=$?; "
            "e=$(grep -m1 -E '^E ' /tmp/r.txt | cut -c1-400); "
            # printf, not echo: sh's echo turns a literal \n in a repr into a line break.
            "printf '%s\\n' \"QOT_RUN $i $c $r $e\"; done")


def stability(stdout: str, want: str, n: int, timed_out: bool = False) -> dict:
    runs = re.findall(r"^QOT_RUN (\d+) (\d+) (\d+) ?(.*)$", stdout, re.MULTILINE)
    bad = [int(i) for i, c, r, e in runs if c != "0" or r != "1" or _norm(e) != want]
    return {"runs": len(runs), "expected": n, "inconsistent_runs": bad, "timed_out": timed_out,
            "passed": len(runs) == n and not bad}


def still_present(stdout: str, timed_out: bool, want_evidence: str, want_sig: str) -> str:
    """'still_fails', 'passes' (changed or fixed upstream) or 'inconclusive'."""
    if timed_out or "QOT_CONTROL_RC=0" not in stdout:
        return "inconclusive"
    if "QOT_REPRO_RC=0" in stdout:
        return "passes"
    if evidence(stdout, False) == want_evidence and signature(stdout) == want_sig:
        return "still_fails"
    return "inconclusive"


def verdict(ev: str, stable: dict | None, head: str | None) -> tuple[str, str]:
    if ev == "none":
        return "no_evidence", "no reproduction failed on an assertion or a project-code exception"
    if stable and stable.get("timed_out") and not stable["inconsistent_runs"]:
        done = f"{stable['runs']} of {stable['expected']}, all consistent" if stable["runs"] else "no run finished"
        return "inconclusive", f"reruns timed out ({done})"
    if not stable or not stable["passed"]:
        return "failed", "not stable on reruns"
    if head == "passes":
        return "failed", "passes on the current default branch, so it may be fixed or changed upstream"
    if head != "still_fails":
        return "failed", "could not be confirmed on the current default branch"
    return "passed", "gates 1 to 3 passed; the separate-fix gate is not built yet"


def _checkout(ctx: RepoContext, where: str) -> tuple[Path, str] | None:
    """A clone of the project's default branch head ('head') or its latest release tag ('release')."""
    root = ctx.repo_dir / "gates" / where
    src = root / "source"
    if not src.exists():
        root.mkdir(parents=True, exist_ok=True)
        pin.git(["clone", "--no-recurse-submodules", "--quiet", ctx.spec.source, str(src)])
        if where == "release":
            try:
                tag = pin.git(["describe", "--tags", "--abbrev=0"], cwd=src)
            except RuntimeError:  # no tags: there is no release to check
                return None
            pin.git(["checkout", "--quiet", "--detach", tag], cwd=src)
    return src, pin.git(["rev-parse", "HEAD"], cwd=src)


def _best_attempt(root: Path) -> tuple[Path | None, str, str]:
    """The first reproduction attempt with assertion evidence, else the first with a crash."""
    found: dict[str, tuple[Path, str]] = {}
    for d in sorted(p for p in root.glob("*") if (p / "output.txt").is_file()) if root.is_dir() else []:
        out = (d / "output.txt").read_text(errors="ignore")
        found.setdefault(evidence(out, False), (d, out))
    for ev in ("assertion", "crash"):
        if ev in found:
            return found[ev][0], found[ev][1], ev
    return None, "", "none"


def gate_one(ctx: RepoContext, f: dict, trees: dict) -> dict:
    unit = ctx.ledger.unit(ctx.spec.name, "gates", f["id"], None)
    if unit.done():
        return unit.payload()
    inputs, out, ev = _best_attempt(ctx.repo_dir / "evidence" / "repro" / f["id"])
    ref = str(inputs.relative_to(ctx.run_dir)) if inputs else None
    result = {"id": f["id"], "validation": f["validation"]["status"], "evidence": ev, "evidence_ref": ref}
    if ev != "none":
        sig = signature(out)
        r = ctx.worker.run(rerun_script(RERUNS), ctx.source_dir, inputs=inputs, timeout_s=60 * RERUNS)
        (inputs / "gates-reruns.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
        result["signature"] = sig
        result["stability"] = stability(r.stdout, sig, RERUNS, r.timed_out)
        for where, (src, commit) in trees.items():
            r = ctx.worker.run(repro_script(), src, inputs=inputs, timeout_s=300)
            (inputs / f"gates-{where}.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
            result[where] = {"commit": commit, "outcome": still_present(r.stdout, r.timed_out, ev, sig)}
    result["verdict"], result["reason"] = verdict(ev, result.get("stability"),
                                                  (result.get("head") or {}).get("outcome"))
    unit.save("done", result)
    return result


def run(ctx: RepoContext) -> list[dict]:
    findings = ctx.read_json("findings.json", [])
    worker_ok, why = ctx.worker.available() if ctx.worker else (False, "no worker")
    if not worker_ok:
        ctx.manifest.incomplete(f"gates: worker unavailable: {why}")
        return []
    trees = {w: t for w in ("head", "release") if (t := _checkout(ctx, w))}
    seen, todo = set(), []
    for f in findings:
        if f["id"] not in seen:
            seen.add(f["id"])
            todo.append(f)
    with ThreadPoolExecutor(max_workers=max(1, ctx.config.parallel)) as pool:
        results = list(pool.map(lambda f: gate_one(ctx, f, trees), todo))
    ctx.write_json("gates.json", {"pinned_commit": ctx.commit or None,
                                  "trees": {w: c for w, (_, c) in trees.items()},
                                  "reruns": RERUNS, "findings": results})
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    ctx.manifest.stage("gates", "complete", **counts)
    return results
