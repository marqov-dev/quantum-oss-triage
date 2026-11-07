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

from harness.stages import deps
from harness.controller.context import RepoContext
from harness.stages import pin
from harness.scanners import tool_versions
from harness.scanners.osv import OsvScanner
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
    """Upstream's default branch head ('head') or its newest release tag ('release'), as it is now.

    The clone is kept between runs, but every call fetches first, so a check never
    uses a copy of upstream from an earlier run.
    """
    root = ctx.repo_dir / "gates" / where
    src = root / "source"
    if not src.exists():
        root.mkdir(parents=True, exist_ok=True)
        pin.git(["clone", "--no-recurse-submodules", "--quiet", ctx.spec.source, str(src)])
    pin.git(["fetch", "--quiet", "--force", "--tags", "--prune", "origin"], cwd=src)
    pin.git(["remote", "set-head", "origin", "--auto"], cwd=src)
    target = "origin/HEAD"
    if where == "release":
        try:
            target = pin.git(["describe", "--tags", "--abbrev=0", "origin/HEAD"], cwd=src)
        except RuntimeError:  # no tags: there is no release to check
            return None
    pin.git(["checkout", "--quiet", "--force", "--detach", target], cwd=src)
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


def _check_trees(ctx: RepoContext, result: dict, inputs: Path, trees: dict, only: set | None = None) -> None:
    for where, (src, commit) in trees.items():
        if only is not None and where not in only:
            continue
        r = ctx.worker.run(repro_script(), src, inputs=inputs, timeout_s=300)
        (inputs / f"gates-{where}.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
        result[where] = {"commit": commit, "outcome": still_present(r.stdout, r.timed_out, result["evidence"],
                                                                    result["signature"])}


def gate_one(ctx: RepoContext, f: dict, trees: dict) -> dict:
    unit = ctx.ledger.unit(ctx.spec.name, "gates", f["id"], None)
    inputs, out, ev = _best_attempt(ctx.repo_dir / "evidence" / "repro" / f["id"])
    ref = str(inputs.relative_to(ctx.run_dir)) if inputs else None
    # A cached verdict stands only for the same evidence: a finding gated before validate
    # wrote its test (or with a different best test) is gated again.
    cached = unit.payload() if unit.done() else None
    if cached and (cached.get("validation") != f["validation"]["status"] or cached.get("evidence_ref") != ref):
        cached = None
    if cached:
        result = cached
        # Upstream may have moved since this was checked: repeat only the checks
        # whose tree changed. The reruns are against the pinned commit and stand.
        moved = {w for w, (_, c) in trees.items() if (result.get(w) or {}).get("commit") != c}
        if result["evidence"] == "none" or not moved:
            return result
        _check_trees(ctx, result, ctx.run_dir / result["evidence_ref"], trees, moved)
    else:
        result = {"id": f["id"], "validation": f["validation"]["status"], "evidence": ev, "evidence_ref": ref}
        if ev != "none":
            sig = signature(out)
            r = ctx.worker.run(rerun_script(RERUNS), ctx.source_dir, inputs=inputs, timeout_s=60 * RERUNS)
            (inputs / "gates-reruns.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
            result["signature"] = sig
            result["stability"] = stability(r.stdout, sig, RERUNS, r.timed_out)
            _check_trees(ctx, result, inputs, trees)
    result["verdict"], result["reason"] = verdict(result["evidence"], result.get("stability"),
                                                  (result.get("head") or {}).get("outcome"))
    unit.save("done", result)
    return result


_ADVISORY = re.compile(r"^Known advisory in dependency (\S+) (\S+)$")


def _head_versions(src: Path) -> dict[str, str]:
    """Package versions in the head tree's uv.lock, when it has one."""
    import tomllib
    try:
        lock = tomllib.loads((src / "uv.lock").read_text())
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
    return {p["name"].lower(): p.get("version") for p in lock.get("package", []) if p.get("name")}


def recheck_advisories(ctx: RepoContext, findings: list[dict], trees: dict) -> list[dict]:
    """Scan upstream's current head for the same advisories. One that no longer appears
    there for that package is reported as resolved on the default branch."""
    advisories = [f for f in findings if f.get("category") == "dependency_advisory"]
    if not advisories or "head" not in trees:
        return []
    src, commit = trees["head"]
    unit = ctx.ledger.unit(ctx.spec.name, "gates-osv", commit[:12], None)
    if unit.done():
        leads = unit.payload()["leads"]
    else:
        r = OsvScanner().run(ctx.worker, src, tool_versions(ctx.worker, src))
        if r.status not in ("ok", "not_applicable"):
            return [{"id": f["id"], "head": "unknown", "note": r.note[:200]} for f in advisories]
        leads = [{"title": x["title"], "ids": x["rule_id"].split(",")} for x in r.findings]
        unit.save("done", {"leads": leads})
    at_head: dict[str, set] = {}
    for x in leads:
        if m := _ADVISORY.match(x["title"]):
            at_head.setdefault(m.group(1).lower(), set()).update(x["ids"])
    versions = _head_versions(src)
    out = []
    for f in advisories:
        m = _ADVISORY.match(f["title"])
        if not m:
            continue
        pkg, ids = m.group(1).lower(), {i for d in f["detection"]["detections"]
                                    for i in (d.get("rule_id") or "").split(",") if i}
        present = bool(ids & at_head.get(pkg, set()))
        out.append({"id": f["id"], "head": "present" if present else "resolved",
                    "head_version": versions.get(pkg)})
    return out


def run(ctx: RepoContext) -> list[dict]:
    findings = ctx.read_json("findings.json", [])
    worker_ok, why = ctx.worker.available() if ctx.worker else (False, "no worker")
    if worker_ok and (problem := deps.environment_problem(ctx)):
        worker_ok, why = False, problem
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
                                  "reruns": RERUNS, "findings": results,
                                  "advisories": recheck_advisories(ctx, findings, trees)})
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    ctx.manifest.stage("gates", "complete", **counts)
    return results
