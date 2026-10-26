"""Stage 3: every review skill on every available model, independently."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from harness.controller import prompts, skills, snapshot
from harness.controller.context import RepoContext


def run(ctx: RepoContext) -> list[dict]:
    files = snapshot.listing(ctx.review_dir)
    jobs = [(s, m) for s in ctx.config.review_skills for m in ctx.model_order()]

    def one(job):
        skill_name, model = job
        prompt = prompts.review(skills.load(skill_name), ctx.spec.name, ctx.commit, ctx.spec.include,
                                ctx.spec.exclude, files)
        return job, ctx.call_model("review", skill_name, model, skill_name, prompt, ctx.config.timeouts["review_s"])

    with ThreadPoolExecutor(max_workers=max(1, ctx.config.parallel)) as pool:
        results = list(pool.map(one, jobs))

    candidates, reviewed, not_reviewed = [], set(), set()
    done = failed = 0
    for (skill_name, model), call in results:
        if not call.ok:
            failed += 1
            ctx.manifest.incomplete(f"review {skill_name} on {model}: failed (details in the private run record)")
            continue
        done += 1
        cov = call.payload["coverage"]
        reviewed.update(cov["reviewed"])
        not_reviewed.update(cov["not_reviewed"])
        for f in call.payload["findings"]:
            candidates.append({**f, "tool": model, "model_id": call.model_id, "skill": skill_name, "unit": call.unit})
    ctx.manifest.data["coverage"]["reviewed"] = sorted(reviewed)
    ctx.manifest.data["coverage"]["not_reviewed"] = sorted(not_reviewed - reviewed)
    ctx.manifest.stage("review", "complete" if not failed else "incomplete", units_total=len(jobs),
                       units_done=done, units_failed=failed)
    ctx.write_json("candidates.json", candidates)
    return candidates
