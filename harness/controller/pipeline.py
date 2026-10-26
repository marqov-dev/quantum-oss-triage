"""The controller's main loop: one repository at a time, stage by stage.

All three models finish a repository before the next one starts. If any
provider reports a usage limit, the repository pauses and the run stops; a
rerun with the same run directory resumes from the last finished unit.
"""

from __future__ import annotations

import traceback
from pathlib import Path

import yaml

from harness import adapters as adapter_mod
from harness.controller import attest, prompts, skills
from harness.controller.config import Config, RepoSpec
from harness.controller.context import RepoContext, UsageLimitReached
from harness.controller.ledger import Ledger
from harness.controller.manifest import Manifest
from harness.stages import fix, pin, review, scan, triage, validate, verify
from harness.workers.base import Worker
from harness.workers.docker import DockerWorker

DEFAULT_STAGES = ("pin", "scan", "review", "verify", "validate", "triage", "fix")


def build_adapters(config: Config, only: list[str] | None = None, require_attestation: bool | None = None):
    """Return (usable adapters, manifest rows for every configured adapter)."""
    require = config.require_isolation_attestation if require_attestation is None else require_attestation
    usable, rows = {}, []
    for name, cfg in config.models.items():
        a = adapter_mod.build(name, **(cfg or {}))
        ok, reason = a.available()
        version = a.version() if ok else None
        mode = a.config_mode() if hasattr(a, "config_mode") else None
        verified = attest.verified(name, version, mode)
        if only and name not in only:
            ok, reason = False, "not selected for this run"
        elif ok and a.runs_shell_on_host and not config.allow_host_shell_adapters:
            ok, reason = False, ("runs shell commands on the host, so repository code could run outside a worker; "
                                 "needs the reviewer sandbox (not built in v0.1)")
        elif ok and require and not verified:
            ok, reason = False, f"isolation not verified for {version!r}; run `qot doctor`"
        rows.append({"name": name, "available": ok, "reason": reason if not ok else (mode or "ok"), "version": version,
                     "model_ids": [], "isolation_verified": verified, "used": ok, "configured_model": a.model})
        if ok:
            usable[name] = a
    return usable, rows


def _run_stage(ctx: RepoContext, stage: str) -> None:
    if stage == "pin":
        pin.run(ctx)
    elif stage == "scan":
        scan.run(ctx)
    elif stage == "review":
        if not ctx.adapters:
            ctx.manifest.incomplete("review: no AI CLI available and isolation-verified")
        review.run(ctx)
    elif stage == "verify":
        verify.run(ctx, ctx.read_json("leads.json", []) + ctx.read_json("candidates.json", []))
    elif stage == "validate":
        validate.run(ctx, ctx.read_json("groups.json", []))
    elif stage == "triage":
        findings = ctx.read_json("findings.json", [])
        triage.write(ctx, findings)
        decided = yaml.safe_load((ctx.repo_dir / "decisions.yaml").read_text()) or {}
        if any((d or {}).get("decision", "pending") != "pending" for d in (decided.get("findings") or {}).values()):
            triage.apply(ctx)
    elif stage == "fix":
        fix.run(ctx)
    else:
        raise ValueError(f"unknown stage {stage!r} (publishing is a separate process: qot publish)")


def _summarise_tokens(ctx: RepoContext) -> None:
    tokens: dict = {}
    model_ids: dict = {}
    prefix = ctx.spec.name + "/"
    for row in ctx.ledger.usage():
        if not row["unit"].startswith(prefix) or not row.get("adapter") or row["adapter"] == "-":
            continue
        t = tokens.setdefault(row["adapter"], {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
                                               "reported_cost_usd": 0.0, "units": 0})
        for k in ("input", "output", "cache_read", "cache_creation"):
            t[k] += int(row.get(k, 0) or 0)
        t["reported_cost_usd"] = round(t["reported_cost_usd"] + float(row.get("reported_cost_usd", 0) or 0), 4)
        t["units"] += 1
        if row.get("model_id"):
            model_ids.setdefault(row["adapter"], set()).add(row["model_id"])
    ctx.manifest.data["tokens"] = tokens
    for a in ctx.manifest.data["adapters"]:
        a["model_ids"] = sorted(model_ids.get(a["name"], []))


def run(config: Config, run_dir: Path, repos: list[RepoSpec], *, stages=DEFAULT_STAGES, models: list[str] | None = None,
        worker: Worker | None = None, adapters: dict | None = None, require_attestation: bool | None = None,
        retry_failed: bool = False, log=print) -> dict:
    run_dir = Path(run_dir)
    ledger = Ledger(run_dir)
    if adapters is None:
        usable, rows = build_adapters(config, models, require_attestation)
    else:  # tests inject fake adapters
        usable = adapters
        rows = [{"name": n, "available": True, "reason": "injected", "version": a.version(), "model_ids": [],
                 "isolation_verified": False, "used": True} for n, a in adapters.items()]
    worker = worker or DockerWorker(image=config.worker["image"], cpus=str(config.worker.get("cpus", "2")),
                                    memory=config.worker.get("memory", "2g"))
    summary = {"run_dir": str(run_dir), "repos": {}, "stopped": None}
    for spec in repos:
        manifest = Manifest.open(run_dir / spec.slug / "manifest.json", run_id=run_dir.name,
                                 repo={"name": spec.name, "source": spec.source, "commit": "0" * 40,
                                       "scope": {"include": spec.include, "exclude": spec.exclude}})
        manifest.data["adapters"] = rows
        manifest.data["skills"] = [{"name": s, "sha256": skills.load(s).sha256} for s in skills.available()]
        manifest.data["prompts_sha256"] = prompts.templates_sha256()
        ctx = RepoContext(spec, run_dir.name, run_dir, config, ledger, manifest, worker, usable,
                          retry_failed=retry_failed, log=log)
        manifest.clear_notes("models")
        for a in rows:
            if not a["used"]:
                manifest.incomplete(f"model {a['name']} not used: {a['reason']}")
        pinned = ledger.unit(spec.name, "pin", None, None)
        if pinned.done():
            ctx.commit = pinned.payload()["commit"]
        log(f"{spec.name}: models {', '.join(usable) or 'none'}")
        status = "complete"
        current = None
        try:
            for stage in stages:
                current = stage
                log(f"[{spec.name}] {stage}")
                manifest.clear_notes(stage)
                manifest.stage(stage, "running")
                _run_stage(ctx, stage)
                if manifest.data["stages"][stage]["status"] == "running":
                    manifest.stage(stage, "complete")
        except UsageLimitReached as e:
            manifest.stage(current, "paused", note=str(e))
            status = "paused"
            summary["stopped"] = f"usage limit: {e}"
        except Exception as e:  # recorded, never hidden
            manifest.fail(f"{spec.name}/{current}", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}")
            manifest.stage(current, "incomplete", note=f"{type(e).__name__} (details in the private run record)")
            status = "failed"
        _summarise_tokens(ctx)
        if status == "complete" and (manifest.data["coverage"]["incomplete_checks"] or manifest.data["failures"]):
            status = "incomplete"
        errors = manifest.finish(status)
        summary["repos"][spec.name] = {"status": status, "manifest_errors": errors,
                                       "dir": str(ctx.repo_dir), "commit": ctx.commit}
        log(f"[{spec.name}] {status}")
        if status == "paused":
            break  # one repository at a time: pick up here in the next usage window
    return summary
