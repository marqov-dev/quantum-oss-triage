"""Stage 4: cross-check. Each claim goes to the models that did not raise it.

Likely duplicates are grouped first so a claim is not verified three times.
When only one model is available, it rechecks its own claims in a fresh
context. That is recorded as `same_model` and never counts toward the main
queue: it can still produce a reproduction, which is real validation.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from harness.controller import merge, prompts, skills
from harness.controller.context import RepoContext


def plan(ctx: RepoContext, groups: list[list[dict]]) -> list[dict]:
    out = []
    models = ctx.model_order()
    seen: set[str] = set()
    for g in sorted(groups, key=lambda g: sorted((c["tool"], c.get("rule_id") or "", c["title"]) for c in g)):
        gid = merge.group_key(ctx.spec.name, g, ctx.source_dir)
        if gid in seen:  # same lines, distinct claims: disambiguate by the representative's rule or title
            rep = merge.representative(g)
            gid = merge.stable_id(ctx.spec.name, f"{gid}|{rep.get('rule_id') or rep['title']}")
        seen.add(gid)
        detectors = {c["tool"] for c in g}
        others = [m for m in models if m not in detectors]
        verifiers = [(m, "independent") for m in others] or [(m, "same_model") for m in models if m in detectors]
        out.append({"id": gid, "candidates": g, "verifiers": verifiers})
    return out


def run(ctx: RepoContext, candidates: list[dict]) -> list[dict]:
    groups = plan(ctx, merge.group(candidates))
    skill = skills.load("verify-finding")
    jobs = [(g, m, ind) for g in groups for m, ind in g["verifiers"]]

    def one(job):
        g, model, independence = job
        rep = merge.representative(g["candidates"])
        source = "another AI reviewer" if rep["tool"] in merge.MODEL_TOOLS else f"the static analysis tool {rep['tool']}"
        prompt = prompts.verify(skill, ctx.spec.name, ctx.commit, rep, source)
        return job, ctx.call_model("verify", g["id"], model, "verify-finding", prompt, ctx.config.timeouts["verify_s"])

    with ThreadPoolExecutor(max_workers=max(1, ctx.config.parallel)) as pool:
        results = list(pool.map(one, jobs))

    by_group: dict[str, list] = {g["id"]: [] for g in groups}
    repros: dict[str, list] = {g["id"]: [] for g in groups}
    failed = 0
    for (g, model, independence), call in results:
        if call.ok:
            v = call.payload
            by_group[g["id"]].append({
                "verifier": model, "model_id": call.model_id, "verdict": v["verdict"], "reason": v["reason"],
                "lines_read": v["lines_read"], "independence": independence, "security_impact": v["security_impact"],
                "proposed_severity": v["proposed_severity"], "unit": call.unit})
            if v["verdict"] == "confirm" and v.get("reproduction"):
                repros[g["id"]].append({"by": model, "independence": independence, **v["reproduction"]})
        else:
            failed += 1
            by_group[g["id"]].append({"verifier": model, "model_id": call.model_id, "verdict": "failed",
                                      "reason": call.error or "failed", "lines_read": [], "independence": independence,
                                      "unit": call.unit})
    for g in groups:
        if not g["verifiers"]:
            by_group[g["id"]].append({"verifier": "none", "verdict": "pending", "reason": "no model available to verify",
                                      "independence": "independent", "unit": ""})
    if failed:
        ctx.manifest.incomplete(f"verification: {failed} of {len(jobs)} units failed (shown as pending)")
    ctx.manifest.stage("verify", "complete" if not failed else "incomplete", units_total=len(jobs),
                       units_done=len(jobs) - failed, units_failed=failed, groups=len(groups))
    out = [{"id": g["id"], "candidates": g["candidates"], "verifications": by_group[g["id"]],
            "reproductions": repros[g["id"]]} for g in groups]
    ctx.write_json("groups.json", out)
    return out
