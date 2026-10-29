"""qot: the quantum-oss-triage command line."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness.controller import cleanenv
from harness.controller.config import Config, load_repos
from harness.paths import REPO_ROOT


def _run_dir(arg: str | None) -> Path:
    return Path(arg) if arg else REPO_ROOT / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qot", description=__doc__)
    ap.add_argument("--config", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run stages 1-7 on repositories from config/repos.yaml")
    r.add_argument("--repo", action="append")
    r.add_argument("--repos-file", type=Path)
    r.add_argument("--run-dir")
    r.add_argument("--stages", default="pin,deps,scan,review,verify,validate,triage,fix")
    r.add_argument("--models", help="comma-separated subset of configured models")
    r.add_argument("--retry-failed", action="store_true")
    r.add_argument("--no-attestation-check", action="store_true", help="for development only")

    t = sub.add_parser("triage-apply", help="apply decisions.yaml to findings.json")
    t.add_argument("run_dir", type=Path)
    t.add_argument("--repo", required=True)

    p = sub.add_parser("publish", help="run the publisher process (local outbox; Marqov only with --live)")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--repo", action="append")
    p.add_argument("--public-summary", action="store_true")
    p.add_argument("--live", action="store_true", help="upload to the configured Marqov Projects (default: dry run)")

    d = sub.add_parser("doctor", help="check the worker image and probe each CLI's isolation")
    d.add_argument("--models")

    e = sub.add_parser("evaluate", help="run the pipeline end to end on the evaluation set")
    e.add_argument("--run-dir")
    e.add_argument("--cases")
    e.add_argument("--models")
    e.add_argument("--no-attestation-check", action="store_true", help="for development only")

    sb = sub.add_parser("sandbox-build", help="build the reviewer sandbox images for Codex and Antigravity")
    sb.add_argument("clis", nargs="*", default=["codex", "agy"])

    sl = sub.add_parser("sandbox-login", help="sign a CLI in inside its reviewer sandbox (interactive)")
    sl.add_argument("cli", choices=["codex", "agy"])
    sl.add_argument("--copy", action="store_true",
                    help="copy only the operator's sign-in file instead (Codex: ~/.codex/auth.json)")

    s = sub.add_parser("status", help="summarise a run directory")
    s.add_argument("run_dir", type=Path)

    args = ap.parse_args(argv)
    config = Config.load(args.config)
    split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731

    if args.cmd == "run":
        from harness.controller import pipeline

        repos = load_repos(args.repos_file)
        if args.repo:
            repos = [x for x in repos if x.name in args.repo]
        if not repos:
            print("No repositories selected. config/repos.yaml is empty until the shortlist is chosen; "
                  "use `qot evaluate` for the evaluation set.", file=sys.stderr)
            return 2
        summary = pipeline.run(config, _run_dir(args.run_dir), repos, stages=tuple(split(args.stages)),
                               models=split(args.models), retry_failed=args.retry_failed,
                               require_attestation=False if args.no_attestation_check else None)
        print(json.dumps(summary, indent=2))
        return 0 if not summary["stopped"] else 3

    if args.cmd == "triage-apply":
        from harness.controller.context import RepoContext
        from harness.controller.ledger import Ledger
        from harness.controller.manifest import Manifest
        from harness.controller.config import RepoSpec
        from harness.stages import triage

        spec = RepoSpec(args.repo, "")
        manifest = Manifest.open(args.run_dir / spec.slug / "manifest.json", run_id=args.run_dir.name, repo={})
        ctx = RepoContext(spec, args.run_dir.name, args.run_dir, config, Ledger(args.run_dir), manifest, None, {})
        ctx.commit = manifest.data["repo"].get("commit", "")
        print(json.dumps(triage.apply(ctx), indent=2))
        manifest.finish(manifest.data["status"] if manifest.data["status"] != "running" else "incomplete")
        return 0

    if args.cmd == "publish":
        # A separate process with a clean environment: the publisher is the only
        # part that will ever hold the Marqov key.
        cmd = [sys.executable, "-m", "harness.publish", str(args.run_dir)]
        for repo in args.repo or []:
            cmd += ["--repo", repo]
        if args.public_summary:
            cmd.append("--public-summary")
        if args.live:
            cmd.append("--live")
        if args.config:
            cmd += ["--config", str(args.config)]
        return subprocess.run(cmd, env=cleanenv.base_env([os.path.dirname(sys.executable)]), cwd=REPO_ROOT).returncode

    if args.cmd == "doctor":
        from harness import doctor

        out = doctor.run(config, split(args.models))
        print(json.dumps(out, indent=2))
        return 0 if all(a["status"] in ("passed", "unavailable", "refused") for a in out["adapters"]) else 1

    if args.cmd == "evaluate":
        from harness import evaluate

        res = evaluate.run(config, _run_dir(args.run_dir), only_cases=split(args.cases), models=split(args.models),
                           require_attestation=False if args.no_attestation_check else None)
        print((Path(res["run_dir"]) / "evaluation.md").read_text())
        return 0 if res["passed"] else 1

    if args.cmd == "sandbox-build":
        from harness.adapters import sandbox

        for cli in args.clis:
            sb_ = sandbox.ReviewerSandbox(cli)
            cmd = ["docker", "build", "-f", str(sandbox.DOCKERFILE), "--target", sb_.spec.target, "-t", sb_.image,
                   str(sandbox.DOCKERFILE.parent)]
            print(" ".join(cmd))
            if subprocess.run(cmd).returncode != 0:
                return 1
        return 0

    if args.cmd == "sandbox-login":
        from harness.adapters import sandbox

        sb_ = sandbox.ReviewerSandbox(args.cli)
        if args.copy:
            copied = sb_.copy_personal_auth()
            if not copied:
                print(f"nothing to copy for {args.cli}; run `qot sandbox-login {args.cli}` without --copy",
                      file=sys.stderr)
                return 1
            print(f"copied {', '.join(copied)} into {sb_.home}")
            return 0
        print(f"Signing {args.cli} in inside its sandbox. The sign-in is stored only in {sb_.home}.")
        return subprocess.run(sb_.login_command()).returncode

    if args.cmd == "status":
        for m in sorted(args.run_dir.glob("*/manifest.json")):
            data = json.loads(m.read_text())
            stages = ", ".join(f"{k}:{v['status']}" for k, v in data["stages"].items())
            print(f"{data['repo']['name']} @ {data['repo']['commit'][:12]}  {data['status']}  [{stages}]")
            for a, t in data["tokens"].items():
                print(f"    {a}: {t['units']} units, in {t['input']} out {t['output']} cache {t['cache_read']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
