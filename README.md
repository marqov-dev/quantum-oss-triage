# quantum-oss-triage

This project aims to create an open method and harness for multi-model AI review of open-source quantum computing repositories. 

The process uses a mixture of sandboxed deterministic review cycles, and then patches in several AI models to review a repository independently,
check each other's claims, and hand a ranked, evidenced list to a real human, who
checks every finding before anything reaches a maintainer.

The value is not in running the AI alone. Maintainers can do that themselves. It is
in the systematic approach, and in reviewing and auditing that make the output safe to act on.

While this project is spun out of an internal effort at [Marqov](https://marqov.ai), and currently uses the Marqov Platform's hosted Projects feature to store and privately disseminate the review findings, this is not a breaking requirement for anyone looking to fork and iterate the project. Likewise the first cohort of candidate open source projects are primarily from our community at the [Unitary Foundation](https://unitary.foundation), where I am a Fellow, but will expand to cover as many of the core quantum projects as possible. If you would like your project added, drop me a line via the [contact form](https://marqov.ai/contact).

## Projects in round one

| Organisation | Repositories |
| --- | --- |
| Unitary Foundation | [ucc](https://github.com/unitaryfoundation/ucc), [metriq-gym](https://github.com/unitaryfoundation/metriq-gym), [mitiq](https://github.com/unitaryfoundation/mitiq), [jeff](https://github.com/unitaryfoundation/jeff), [qrack](https://github.com/unitaryfoundation/qrack), [clifft](https://github.com/unitaryfoundation/clifft) |
| QuTiP | [qutip](https://github.com/qutip/qutip) |
| Xanadu | [pennylane](https://github.com/PennyLaneAI/pennylane) |
| PsiQuantum | [bartiq](https://github.com/PsiQ/bartiq), [psiqdk](https://github.com/PsiQ/psiqdk) |
| Qiskit Community | [qrmi](https://github.com/qiskit-community/qrmi) |
| Independent | [quimb](https://github.com/jcmgray/quimb) |
| PCSS | [open-qbench](https://github.com/PCSS-Quantum/open-qbench) |

The list lives in `config/repos.yaml`. Listing a project means it is in scope
for review, not that its maintainers are involved or have endorsed the work.

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

## How the models are accessed

The harness runs each provider's command-line tool (`claude`, `codex`, `agy`)
directly, so the desktop apps do not need to be open. Docker does need to be
running. Each tool uses a sign-in you make once, and round one uses personal
subscriptions, not API keys. The harness removes API keys from the environment
the tools run in, and a run pauses when a provider reports a usage limit.

A paid overage setting on your account could still bill you past a limit, so
check it with each provider, along with their terms on scripted use of a
personal plan. See [docs/SETUP.md](docs/SETUP.md).

## Status

Version 0.1, built for round one. See [docs/METHOD.md](docs/METHOD.md#status-of-v01)
for what works, what is stubbed and what is not built yet.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
