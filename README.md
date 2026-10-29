# quantum-oss-triage

An open method and harness for multi-model AI review of open-source quantum
computing repositories. Several AI models review a repository independently,
check each other's claims, and hand a ranked, evidenced list to a person, who
checks every finding before anything reaches a maintainer.

The value is not in running the AI. Maintainers can do that themselves. It is
in the checking, ranking and evidence that make the output safe to act on.

## What is here

| Path | What it is |
| --- | --- |
| `skills/` | Review instructions in the open Agent Skills format (a folder with `SKILL.md`): `review-security`, `review-correctness`, `review-docs`, `review-quantum`, `verify-finding`, `propose-fix`, `verify-fix`. |
| `schemas/` | JSON Schemas for model output (`review-output`, `verdict`, `fix-output`), the stored finding record (`finding`) and the run manifest (`run`). |
| `harness/` | The Python harness: `controller/` (scheduling, schema checks, evidence), `adapters/` (Claude Code, Codex, Antigravity), `workers/` (disposable containers), `scanners/` (fixed, non-AI tools), `stages/`, `publish/`. |
| `evaluations/` | The evaluation set: planted bugs, harmless code that looks suspicious, and a hostile repository. |
| `docker/worker.Dockerfile` | The credential-free worker image. |
| `docker/reviewer.Dockerfile` | The reviewer sandbox images for Codex and Antigravity, which read files with shell commands. |
| `docs/` | [METHOD](docs/METHOD.md), [DISCLOSURE](docs/DISCLOSURE.md), [SETUP](docs/SETUP.md), [CONTRIBUTING](docs/CONTRIBUTING.md). |

If you only want the review instructions, copy `skills/` into your own tool's
skills folder (for example `.agents/skills/` or `.claude/skills/`). You do not
need the harness for that. The skills on their own give results that depend on
who runs them and with which model. The harness is what makes results
comparable and checkable.

## Quick start

```bash
uv sync
docker build -f docker/worker.Dockerfile -t quantum-oss-triage-worker:dev .
uv run qot sandbox-build     # reviewer sandboxes for Codex and Antigravity
uv run qot sandbox-login agy # sign a CLI in inside its sandbox (once)
uv run qot doctor            # checks the worker and each installed CLI's isolation
uv run qot evaluate          # the full pipeline on the evaluation set
uv run pytest                # the harness's own tests
```

`qot run` reviews the repositories listed in `config/repos.yaml`. Decisions go
in each repository's `decisions.yaml`. `qot triage-apply` records them, and
`qot publish` renders the reports (a dry run unless given `--live`). See
[docs/SETUP.md](docs/SETUP.md).

## Status

Version 0.1, built for round one. See [docs/METHOD.md](docs/METHOD.md#status-of-v01)
for what works, what is stubbed and what is not built yet.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
