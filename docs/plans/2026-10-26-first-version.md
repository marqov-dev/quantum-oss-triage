# quantum-oss-triage first version: implementation plan

> **For agentic workers:** Use superpowers:executing-plans (native, chosen by the starting session) to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A tested harness that runs the review pipeline (pin, scan, review, verify, validate, triage, fix, publish) end to end on an evaluation set with whichever AI CLIs are installed and signed in.

**Architecture:** A Python package `harness` with three separate parts. The **controller** runs the AI CLIs with a clean configuration against a read-only review copy and keeps the evidence. **Workers** are disposable Docker containers with no credentials that run the scanners, tests and reproductions. The **publisher** is a separate entry point that reads only approved local files and writes local Marqov outbox files. All state lives in a run directory as JSON units keyed by (repo, stage, skill, model), so a stopped run resumes.

**Tech Stack:** Python 3.12 via `uv`, `jsonschema`, `pyyaml`, `pytest`, Docker (`python:3.12-slim` worker image).

**Spec:** "Open-source quantum repo review: draft plan" (https://claude.ai/artifact/DyqLrfa2imm15Dsd3Nb3cd), sections "Key insights", "Technical design" and "Execution plan".

## Global Constraints

- Licence Apache-2.0 (already in `LICENSE`).
- No credentials in the repository. The Marqov key is read only from `~/.config/marqov/api-key`, and only in `harness/publish/`. In this version the publisher writes local files only and does not read the key at all.
- Workers get no model, GitHub or Marqov credentials, no home directory, no Docker socket, a read-only source mount, a throwaway writable copy, and CPU, memory, disk, output and time limits.
- CLIs never load the repository's or David's agent settings (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.claude/`, hooks, MCP servers, personal skills, plugins, memory).
- AI tools get read and search tools only. No shell.
- Claude adapter: `claude -p ... --output-format json`. Codex: `codex exec --json --output-schema <schema> -o <out>` with `--sandbox read-only`. Antigravity: `agy -p ... --output-format json --mode plan --sandbox --print-timeout 20m` inside a hard 25-minute timeout.
- Every model output is validated against its schema. An invalid output gets one retry, then the unit is logged as failed. Outputs are never fixed up by hand.
- Separate fields for detection source, corroboration, validation, impact, severity, sensitivity and disposition.
- Models agreeing is not validation. Severity is set by a person. Severity never decides privacy; the sensitive flag does.
- Main queue: validated, or found independently by two models, or confirmed by an independent verifier with no refutation. Confirmed and refuted means disputed, which also goes to the main queue. Everything else goes to the low-priority list.
- Incomplete is never shown as clean. A scanner that fails or is missing is recorded as `unavailable` or `failed`, never as a pass.
- Fix branches are named `review/2026-10/<finding-id>`. Nothing is pushed in this version. Security fixes are exported only as `.patch` files to the private evidence store.
- Never "deterministic". Use "recorded, integrity-checkable and rerunnable".

## Review Focus

1. **CLI missing or not signed in**: the pipeline records the model as unavailable in the manifest and continues with the rest. It never crashes or silently drops coverage. Test: `test_pipeline_records_unavailable_adapters`.
2. **Usage limit hit mid-repository**: the run stops cleanly, the repository is marked paused, and a rerun skips completed units. Test: `test_resume_skips_completed_units` and `test_usage_limit_pauses_repo`.
3. **Model output that is not JSON, or does not match the schema**: one retry, then a failed unit with the raw output kept. Test: `test_adapter_retries_once_then_fails`.
4. **Hostile repository text**: canary strings never appear in outputs, no hook or MCP marker is created, the snapshot hash is unchanged, and the planted bug in the hostile repo is still found. Test: the `hostile` evaluation case plus `test_isolation_flags`.
5. **Secret values from gitleaks**: redacted before anything is stored. Test: `test_gitleaks_output_is_redacted`.

---

### Task 1: Skeleton, schemas and package

**Files:** `pyproject.toml`, `.gitignore`, `README.md`, `harness/__init__.py`, `harness/__main__.py`, the empty subpackages, `schemas/{finding,verdict,run,review-output,fix-output}.schema.json`, `harness/controller/schema.py`, `config/repos.yaml`, `config/harness.yaml`, `tests/test_schemas.py`.

**Interfaces:**
- Produces: `schema.load(name: str) -> dict`, `schema.validate(name: str, data) -> list[str]` (an empty list means valid). Names are `finding`, `verdict`, `run`, `review-output`, `fix-output`.
- `review-output` and `fix-output` and `verdict` are strict (every property required, `additionalProperties: false`, nullable types for optional values) so Codex `--output-schema` accepts them.

- [ ] Test that every schema is a valid Draft 2020-12 schema, that a minimal good example validates, and that a finding missing `sensitivity` fails.
- [ ] Write the schemas and the `schema.py` helpers. The finding record has top-level `detection`, `corroboration`, `validation`, `impact`, `severity`, `sensitivity` and `disposition` objects.
- [ ] Run `uv run pytest tests/test_schemas.py`. Expected: PASS.

### Task 2: Clean configuration and adapters

**Files:** `harness/controller/cleanenv.py`, `harness/adapters/{base,claude,codex,antigravity}.py`, `tests/test_adapters.py`, `tests/fakes/` (fake CLIs as shell scripts).

**Interfaces:**
- `AdapterResult(ok: bool, data: dict|None, raw: str, model_id: str|None, tokens: dict, error: str|None, attempts: int, usage_limited: bool, duration_s: float)`
- `Adapter.name`, `Adapter.available() -> tuple[bool, str]`, `Adapter.version() -> str|None`, `Adapter.run(prompt: str, system: str, schema_name: str, cwd: Path, timeout_s: int) -> AdapterResult`. The base class owns validation and the single retry.
- `cleanenv.base_env() -> dict` keeps only `PATH`, `HOME`, `LANG`, `TERM`=dumb and `USER`, plus any adapter-specific variables. `cleanenv.codex_home(root) -> Path` writes a harness-owned `CODEX_HOME` holding a `config.toml` with no MCP servers.
- Claude flags: `--safe-mode --restricted --setting-sources "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools Read,Grep,Glob --disable-slash-commands --no-session-persistence --permission-mode dontAsk --system-prompt <harness text> --json-schema <schema>`.
- Codex flags: `--sandbox read-only --skip-git-repo-check -C <cwd> -c project_doc_max_bytes=0`. Antigravity: as in Global Constraints. Both are marked `isolation_verified: false` until `harness doctor` passes the hostile probe for that CLI version.

- [ ] Tests with fake CLIs: valid output is parsed, invalid output is retried once then fails, a timeout kills the process, a usage-limit message sets `usage_limited`, a missing binary reports unavailable, the Claude argument list contains every isolation flag, and the environment passed has no `*_API_KEY`, `GITHUB_TOKEN` or `MARQOV` variables.
- [ ] Implement. Run `uv run pytest tests/test_adapters.py`. Expected: PASS.

### Task 3: Workers, worker image and scanners

**Files:** `docker/worker.Dockerfile`, `harness/workers/{base,docker,local}.py`, `harness/scanners/{base,gitleaks,osv,semgrep,zizmor,scorecard,ruff,bandit,lychee,project_tests}.py`, `tests/test_workers.py`, `tests/test_scanners.py`.

**Interfaces:**
- `Worker.run(cmd: list[str], src: Path, *, network: bool=False, timeout_s=600, writable_copy=True) -> WorkerResult(exit_code, stdout, stderr, timed_out, truncated)`. Docker flags: `--network none` (unless `network`), `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--pids-limit 256`, `--memory 2g`, `--cpus 2`, `--user 65534:65534`, `-v src:/src:ro`, `--tmpfs /work:size=1g`, `--tmpfs /tmp:size=256m`, `-e HOME=/tmp`, no other environment. Output is capped at 5 MB per stream.
- `LocalWorker` exists only for unit tests and refuses to run unless `QOT_ALLOW_LOCAL_WORKER=1`.
- `Scanner.name`, `Scanner.run(worker, src) -> ScanResult(status: "ok"|"failed"|"unavailable"|"not_applicable", tool_version, findings: list[dict], hygiene: dict, note)`. Leads (`gitleaks`, `osv`, `semgrep`, `zizmor`, and `bandit` at medium or above) become findings. `ruff`, `lychee` and low-severity `bandit` become hygiene counts only.
- gitleaks runs with `--redact`, and the wrapper also replaces any `Secret`/`Match` value with `REDACTED`.

- [ ] Tests: each parser on recorded sample output, the Docker argument list, the local-worker guard, and gitleaks redaction.
- [ ] Build the image in the background (`docker build -f docker/worker.Dockerfile -t quantum-oss-triage-worker:dev .`). Any tool that fails to install is reported by `qot-scan-versions` inside the image and recorded as unavailable.

### Task 4: Skills

**Files:** `skills/{review-security,review-correctness,review-docs,review-quantum,verify-finding,propose-fix,verify-fix}/SKILL.md`, `harness/controller/skills.py`, `tests/test_skills.py`.

**Interfaces:** `skills.load(name) -> Skill(name, description, body, sha256)`. Front matter has `name`, `description` and `output_schema`.

- [ ] Test that every skill parses, names its output schema, and contains the untrusted-input rule.
- [ ] Write the skills. Each check in `review-quantum` states when its rule applies.

### Task 5: Ledger, stages and pipeline

**Files:** `harness/controller/{ledger,manifest,pipeline,merge,snapshot}.py`, `harness/stages/{pin,scan,review,verify,validate,triage,fix,publish}.py`, `tests/test_ledger.py`, `tests/test_merge.py`, `tests/test_pipeline.py`.

**Interfaces:**
- `Ledger(run_dir).unit(repo, stage, skill, model) -> Unit`. `Unit.done() -> bool`, `Unit.save(status, payload, tokens)`. Tokens are also appended to `usage.jsonl`.
- `snapshot.review_copy(src, dest)` makes a read-only copy (`chmod -R a-w`) and `snapshot.tree_hash(path) -> str`.
- `merge.fingerprint(area, path, snippet) -> str` and `merge.group(findings) -> list[list[dict]]` (same file, line ranges within 3 lines, same area family).
- `pipeline.run(config, run_dir, repos, models, stages, decisions=None) -> dict`.
- Verify: verifiers are the other available models. When only one model is available, the same model verifies in a fresh context, marked `same_model`, and that confirmation does not count toward the main queue.
- Validate: a reproduction from `verify-finding` counts only if its test fails at the reviewed commit and its control passes, both run in a worker.

- [ ] Tests: resume skips completed units, a usage limit pauses the repository, a missing adapter is recorded, the main-queue rule, the sensitive flag, and fingerprint stability.

### Task 6: triage.md, renderer and publisher

**Files:** `harness/stages/triage.py`, `harness/publish/{render,redact,marqov,github}.py`, `tests/test_publish.py`.

- [ ] `triage.md` and `decisions.yaml` template. Report Markdown and HTML rendered from approved fields only. Security rows show ID, severity and date only. `redact.check(text) -> list[str]` flags paths with line numbers, secret patterns and exploit wording in sensitive rows. `marqov.py` writes `outbox/<org>__<repo>/{workspace,report}.json`. `github.py` plans branch names and refuses to push.

### Task 7: Evaluation set and end-to-end run

**Files:** `evaluations/{planted-bugs,harmless-lookalikes,hostile}/`, each with `expected.yaml`, plus `harness/evaluate.py` and `tests/test_evaluations.py`.

- [ ] `qot evaluate` copies each case into a run directory, initialises git, runs the pipeline, and scores it. Recall on planted bugs; no main-queue finding on a harmless lookalike; hostile case: canary absent, markers absent, snapshot hash unchanged, planted bug found.
- [ ] `qot doctor` runs the hostile isolation probe for each installed CLI and writes `isolation-attestations.json`.
- [ ] Run the full evaluation with the installed CLIs, fix the skills until it passes, then run `uv run pytest`.
