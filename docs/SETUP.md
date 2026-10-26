# Setup

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- Docker, for workers.
- At least one AI CLI, signed in with your own account: Claude Code
  (`claude`), OpenAI Codex CLI (`codex`) or Google Antigravity CLI (`agy`).
  Round one uses personal subscriptions and no API keys. Check each
  provider's terms on scripted use of a personal plan.

No credential ever goes in this repository. The harness keeps its own CLI
configuration under `~/.config/quantum-oss-triage/` (override with
`QOT_CONFIG_ROOT`).

## Steps

```bash
uv sync
docker build -f docker/worker.Dockerfile -t quantum-oss-triage-worker:dev .
uv run qot doctor
```

`qot doctor` prints the worker image digest and runs the hostile isolation
probe for every installed CLI. It records the result per CLI version in
`~/.config/quantum-oss-triage/isolation-attestations.json`. The pipeline
refuses a CLI version without a passing attestation. After upgrading a CLI,
run `qot doctor` again.

### Claude Code: optional fully separate configuration

By default the harness uses your normal Claude Code sign-in, with flags that
stop it loading any `CLAUDE.md`, settings, hooks, skills, plugins, memory or
MCP servers. For complete separation, including account metadata, sign in
once to a harness-owned config directory:

```bash
CLAUDE_CONFIG_DIR=~/.config/quantum-oss-triage/claude claude
```

Run `/login` inside, then exit. With `config_dir: auto` (the default in
`config/harness.yaml`), the harness uses that directory from then on. Run
`qot doctor` again so the attestation records the new mode.

### Codex and Antigravity

Install them and sign in with your own accounts. The Codex adapter links only
`~/.codex/auth.json` into its own `CODEX_HOME`. Neither adapter has been run
against a real install yet. Confirm the flags with `codex exec --help` and
`agy --help`, then run `qot doctor`.

## Running

```bash
uv run qot evaluate                         # the evaluation set, end to end
uv run qot run --repo org/name              # repositories from config/repos.yaml
uv run qot status runs/<run-id>
# edit runs/<run-id>/<org>__<name>/decisions.yaml, then:
uv run qot triage-apply runs/<run-id> --repo org/name
uv run qot run --repo org/name --run-dir runs/<run-id> --stages pin,fix
uv run qot publish runs/<run-id> --public-summary
```

Rerunning `qot run` with the same `--run-dir` resumes from the last finished
unit. `--retry-failed` reruns units whose output failed validation twice.

Run directories hold unredacted security findings. Keep them out of this
repository (they are git-ignored) and store them in the private runs
repository.
