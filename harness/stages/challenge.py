"""Stage 5c: the other models attack each test that passed the gates.

The model that wrote a reproduction does not judge it. Every other available
model gets the claim, the test, the control and the observed failure, but not
the finder's reasoning, who wrote the test, or earlier verdicts. Outcomes by
rule:

- refuted: at least one challenger called the test invalid and cited
  repository lines for it.
- upheld: every challenger called it valid.
- unsettled: anything else, including an invalid verdict with no citation, or one
  whose only problem is a weak control: the evidence is weaker, but the defect may
  be real, so the test needs a stronger control rather than dismissal.

Results go to challenge.json; finding records and decisions are untouched.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.controller import merge, prompts, skills
from harness.controller.context import ModelCall, RepoContext

_OBSERVED_CHARS = 6000


def counted(v: dict) -> str:
    """The verdict as the rule counts it: an invalid verdict needs a citation, and a weak control alone does not refute."""
    if v["verdict"] == "invalid" and not v["citations"]:
        return "unsure"
    if v["verdict"] == "invalid" and v["problem"] == "weak_control":
        return "needs_stronger_control"
    return v["verdict"]


def outcome(verdicts: list[dict]) -> tuple[str, str]:
    if not verdicts:
        return "unsettled", "no challenger was available"
    counts = [counted(v) for v in verdicts]
    if "invalid" in counts:
        return "refuted", "a challenger called the test invalid and cited evidence"
    if all(c == "valid" for c in counts):
        return "upheld", f"all {len(counts)} challengers called the test valid"
    if "needs_stronger_control" in counts:
        return "unsettled", "a challenger found the control too weak; the test needs a stronger control"
    return "unsettled", "at least one challenger was unsure, or called it invalid without a citation"


def _test(attempt: Path, rp: dict) -> dict:
    out = (attempt / "output.txt").read_text(errors="ignore")
    return {"test_code": (attempt / "test_qot_repro.py").read_text(),
            "control_code": (attempt / "test_qot_control.py").read_text(),
            "expected_behaviour_source": rp["expected_behaviour_source"], "claimed_failure": rp["claimed_failure"],
            "observed": out.split("--- stderr ---", 1)[0][-_OBSERVED_CHARS:]}


def run(ctx: RepoContext) -> list[dict]:
    gates = ctx.read_json("gates.json", {}).get("findings", [])
    groups = {g["id"]: g for g in ctx.read_json("groups.json", [])}
    skill = skills.load("challenge-test")
    # Every configured model except the author challenges, whether or not it can run now: one
    # that cannot leaves the test unsettled, never judged by fewer challengers.
    models, available = list(ctx.config.models), set(ctx.model_order())
    todo = []
    for gf in gates:
        g = groups.get(gf["id"])
        if gf["verdict"] != "passed" or not g or not gf.get("evidence_ref"):
            continue
        attempt = ctx.run_dir / gf["evidence_ref"]
        rp = g["reproductions"][int(attempt.name)]
        test = _test(attempt, rp)
        prompt = prompts.challenge_test(skill, ctx.spec.name, ctx.commit, merge.representative(g["candidates"]),
                                        test, test["observed"])
        todo.append((gf["id"], rp["by"], gf["evidence_ref"], [m for m in models if m != rp["by"]], prompt))

    def one(job):
        fid, model, prompt = job
        if model not in available and not ctx.ledger.unit(ctx.spec.name, "challenge", fid, model).done():
            return fid, model, ModelCall(False, None, None, "", "model not available in this run")
        return fid, model, ctx.call_model("challenge", fid, model, "challenge-test", prompt,
                                          ctx.config.timeouts["verify_s"])

    jobs = [(fid, m, prompt) for fid, _, _, challengers, prompt in todo for m in challengers]
    with ThreadPoolExecutor(max_workers=max(1, ctx.config.parallel)) as pool:
        calls = list(pool.map(one, jobs))
    by_id: dict[str, list] = {fid: [] for fid, *_ in todo}
    failed = 0
    for fid, model, call in calls:
        if call.ok:
            by_id[fid].append({"challenger": model, "model_id": call.model_id, **call.payload,
                               "counted": counted(call.payload), "unit": call.unit})
        else:
            failed += 1
            by_id[fid].append({"challenger": model, "model_id": call.model_id, "failed": call.error or "failed",
                               "unit": call.unit})
    results = []
    for fid, author, ref, challengers, _ in todo:
        ok = [v for v in by_id[fid] if "failed" not in v]
        result, reason = outcome(ok)
        if len(ok) < len(challengers):
            result, reason = "unsettled", f"{len(challengers) - len(ok)} of {len(challengers)} challenges failed to run"
        results.append({"id": fid, "author": author, "evidence_ref": ref, "outcome": result, "reason": reason,
                        "challenges": by_id[fid]})
    ctx.write_json("challenge.json", {"rule": "refuted if any cited invalid other than a weak control; upheld if all valid; else unsettled",
                                      "findings": results})
    if failed:
        ctx.manifest.incomplete(f"challenge: {failed} of {len(jobs)} units failed (shown as unsettled)")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    ctx.manifest.stage("challenge", "complete" if not failed else "incomplete", units_total=len(jobs),
                       units_failed=failed, **counts)
    return results
