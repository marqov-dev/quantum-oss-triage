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

They run in reviewer sandbox containers, not on the host. The host installs
are not used by the harness.

```bash
uv run qot sandbox-build            # both images (Linux builds of codex-cli 0.164.0 and agy 1.4.7)
uv run qot sandbox-login codex --copy   # copy only ~/.codex/auth.json, or omit --copy for device-code sign-in
uv run qot sandbox-login agy        # interactive: open the URL, sign in, paste the code within 60 seconds
uv run qot doctor --models codex,antigravity
```

The sign-ins are kept only in `~/.config/quantum-oss-triage/sandbox/<cli>/home`.

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
Units a provider refused because its model was at capacity are rerun on any
resume, without the flag.

## Publishing to Marqov

`qot publish` is a dry run unless given `--live`. The Marqov Project and
document ids are kept out of this repository, in
`~/.config/quantum-oss-triage/marqov-targets.yaml`, which uses the same keys
as `publish.marqov` in `config/harness.yaml` and is laid over it:

```yaml
hub:
  project_id: <hub Project id>
  key_path: ~/.config/marqov/<hub key file>
repos:
  project_id: <Project id for per-repository documents>
protected_documents:
  <document id>: <why it must never be written>
retired_projects: [<Project id or prefix>]
```

API keys stay in their own files under `~/.config/marqov/`; never put a key
in either file.

Run directories hold unredacted security findings. Keep them out of this
repository (they are git-ignored) and store them in the private runs
repository.
