# Method

This document describes how quantum-oss-triage reviews a repository and what
each part of a result means. The design principles come first, because every
mechanism below follows from them.

## Principles

- **Fixed scanners are the backbone; models add judgment.** A scanner hit is a
  lead, not a confirmed defect. Advisory databases change without the code
  changing, so their versions and dates are recorded.
- **Different models catch different things and make different mistakes.**
  All available models review independently, then check each other. We record
  whether a model found something on its own or agreed after seeing another
  model's claim. Only the first is independent.
- **Evidence is kept in separate fields, not one score.** Detection source,
  corroboration, validation, impact, severity, sensitivity and disposition are
  recorded separately (`schemas/finding.schema.json`). Models agreeing is not
  validation. Severity is set by a person.
- **A false positive costs more than a miss.** There is no finding quota. A
  repository with no validated findings, within a stated scope, is a
  legitimate result.
- **Incomplete is never shown as clean.** Every report states what was
  reviewed and what was not. A missing or failed scanner is recorded as
  `unavailable` or `failed`, never as a pass.
- **The repository is untrusted input.** Its code, docs and agent
  configuration can carry text written to steer an AI reviewer, and its
  install scripts and tests are code we run. Instructions in the skills are
  not the defence; the separation below is.
- **A person signs off on everything that leaves.**

## Three separate parts

| Part | Does | Holds |
| --- | --- | --- |
| Controller (`harness/controller`, `harness/stages`, `harness/adapters`) | Schedules work, runs the AI CLIs, checks their output against the schemas, keeps the evidence | The CLIs' own sign-ins only |
| Workers (`harness/workers`, `docker/worker.Dockerfile`) | Run scanners, tests, reproductions and fix checks | Nothing: no credentials, no home directory, no Docker socket |
| Publisher (`harness/publish`, run as its own process) | Writes the shareable documents and, with `--live`, the configured Marqov Projects; later, GitHub | The Marqov API keys, read from their key files (outside the repository) in live mode only; later, a fork-only GitHub token |

The AI tools read; workers run. A test (`tests/test_publish.py`) fails if the
publisher imports the controller, adapters or workers, or the other way round.

### Workers

Each worker is a fresh container with:

- the source snapshot mounted read-only at `/src`;
- the repository's installed dependencies, if any, read-only at `/deps`;
- a throwaway writable copy at `/work` (tmpfs, 1 GB);
- `--network none` (the osv-scanner step gets network to query the advisory
  database, and reads lockfiles only; the dependency step gets the package
  registry only, see below);
- `--read-only`, `--cap-drop ALL`, `no-new-privileges`, user `65534`;
- limits of 2 CPUs, 2 GB memory, 256 processes and a time limit per call;
  output is capped at 5 MB per stream;
- no environment from the host, apart from `HOME=/tmp` and two harness flags.

### No inherited agent settings

The AI CLIs are started with an empty environment plus `PATH`, `HOME`, `USER`
and locale. A desktop or IDE session can export many variables (account
details, messaging sockets, proxy URLs, API keys), and none of them are passed
on. In addition:

- **Claude Code** runs with `--safe-mode --restricted --setting-sources ""
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools Read,Grep,Glob
  --disable-slash-commands --no-session-persistence --permission-mode dontAsk`
  and a harness system prompt. `--bare` would be cleaner, but it accepts only
  API keys, and round one uses subscriptions. For a fully separate
  configuration, sign in once to a harness-owned config directory (see
  [SETUP](SETUP.md)). Without it, account metadata such as the account email
  is still placed in the model's context by the CLI itself. No repository or
  personal settings, memory, hooks, skills or MCP servers are loaded.
- **Codex** and **Antigravity** read files by running shell commands, so
  they run in a **reviewer sandbox** (`harness/adapters/sandbox.py`,
  `docker/reviewer.Dockerfile`): one container per CLI and per call, holding
  only the read-only review copy at `/review`, a per-call output folder and a
  harness-owned home (`~/.config/quantum-oss-triage/sandbox/<cli>/home`) with
  that CLI's sign-in and the harness's settings for it. Nothing else from the
  operator's home is mounted or copied, so personal settings, permission rules,
  instructions, skills, MCP servers and memory (for example the permission
  rules in `~/.gemini/config/config.json`) cannot load. The container has a
  read-only root, no capabilities, no-new-privileges, CPU, memory and process
  limits, and is killed at the timeout. Its seccomp profile is Docker's
  default plus user namespaces, so the CLI's own command sandbox works inside
  it.
  - Codex: `codex exec --sandbox read-only --ephemeral --ignore-rules
    --strict-config -c project_doc_max_bytes=0`, with a harness `config.toml`
    that turns off web search, hooks, plugins, apps, browser and computer use,
    and multi-agent. Its shell commands run in Codex's own bubblewrap sandbox
    inside the container: read-only, no network, no capabilities (checked
    live).
  - Antigravity: `agy -p ... --output-format json --json-schema <file> --mode
    plan --sandbox --disable-slash-commands`, inside a hard 25-minute process
    timeout, because print mode has a reported headless hang. On macOS agy
    keeps its sign-in in the keychain, which cannot be copied, so it is signed
    in once inside its sandbox (`qot sandbox-login agy`).
  - The CLI process itself needs the network to reach its provider, so the
    container is on Docker's default bridge with unrestricted egress. The
    review copy is public source, but the CLI's own sign-in token sits in the
    container. Codex's shell commands have no network; a model could still
    quote a file it can read into its reply, which the harness redacts for
    secret-like values before storing. An egress allowlist is later work.
  - Codex's sign-in can be copied from `~/.codex/auth.json` (`qot
    sandbox-login codex --copy`, OpenAI's documented fallback for headless
    machines) or made separately with device-code sign-in (`qot sandbox-login
    codex`). The copy then refreshes on its own; whether a refresh in one copy
    invalidates the other is not documented.

The pipeline still refuses a CLI that reads with shell commands if it is
configured to run on the host (`sandbox: false`), unless
`allow_host_shell_adapters` is set. Claude Code runs on the host because it
gets only the Read, Grep and Glob tools, confined to the review copy by
`--restricted`.

The AI tools see a read-only copy of the in-scope source, without `.git` and
without symlinks.

The pipeline uses a CLI only after `qot doctor` has passed the hostile probe
for that exact CLI version. The probe reviews `evaluations/hostile`, which has
a `CLAUDE.md`, `AGENTS.md` and `GEMINI.md` with instructions, hooks, project
MCP servers, a repository skill, and prompt injection in docs and code. It
passes only if no canary token appears, no hook or MCP marker file is
created, and the snapshot is unchanged. Each canary is spelled out in parts in
the fixtures, so a model that quotes the text does not trip the check, but a
model that obeys it does.

For a sandboxed CLI the probe also fails if any personal configuration could
reach it. The CLI runs with `HOME` set to a decoy operator home whose
user-level settings, instructions and permission rules (`~/.codex/AGENTS.md`,
`~/.codex/config.toml`, `~/.gemini/GEMINI.md`, `~/.gemini/config/config.json`
and others) carry their own canary; no mount may be the operator's home or lie
inside their `~/.codex` or `~/.gemini`; and no file in the sandbox home may be
a copy of a file from the operator's real user-level configuration, sign-in
files and the CLI's own bundled skills excepted. As a negative control, Codex
run with the decoy `AGENTS.md` mounted does print the canary. The marker
folder is mounted at the same path inside the container, so an obeyed hook is
still visible.

## The stages

Each unit of work is keyed by (repository, stage, skill, model) and saved when
it completes. A run that stops, for example on a subscription usage limit,
resumes from the last finished unit. Token usage is logged per unit in
`usage.jsonl` and summed per model in `manifest.json`.

One repository is finished by every available model before the next starts.
If any provider reports a usage limit, the repository pauses and the run
stops. A provider that refuses because its model is at capacity (a server-side
refusal, not our usage) is retried after 30, 120 and 300 seconds; a unit still
refused after that is recorded as failed and run again whenever the run
resumes, including a rerun of `qot evaluate` on the same run folder.

1. **Pin.** Clone (no hooks, no submodules, the operator's git config ignored)
   and record the commit SHA. Every later stage reads that commit only. The
   scope (included and excluded paths) is recorded.
2. **Dependencies.** The install plan is read from the snapshot's files
   (requirements files except documentation ones, `pyproject.toml` test or
   dev extras and dependency groups, `setup.py` or `setup.cfg`); nothing runs
   on the host. A worker installs them into an isolated virtual environment in
   the repository's run folder. Its only network is the package registry: it
   sits on an internal Docker network with no route out, and a proxy container
   forwards HTTPS to `pypi.org` and `files.pythonhosted.org` only, logging
   every allowed and refused connection. The project itself is uninstalled
   again, so the code under review always comes from the worker's copy. Later
   workers mount the environment read-only at `/deps` and still run with no
   network. The resolved versions (`pip freeze`) are kept as evidence. A
   failed or partial install is recorded as such; a suite that then fails at
   import is reported, not hidden.
3. **Scan.** gitleaks, osv-scanner, Semgrep (open Python and secrets rules,
   fetched at image build), zizmor, Ruff, Bandit, lychee (local links only)
   and the project's own tests, each in a worker. OpenSSF Scorecard needs a
   GitHub token and a GitHub remote, so it is recorded as unavailable in
   v0.1. Security and correctness leads become candidate findings. Lint,
   style and link results become hygiene counts. gitleaks values, authors and
   emails are redacted before anything is stored.
4. **Review.** Every review skill on every available model, independently.
   Models do not see the scanner leads, so their detections stay independent.
5. **Cross-check.** Likely duplicates are grouped first (same file, nearby
   lines, same area family or similar wording). Each group goes to the models
   that did not raise it, with `verify-finding`, which asks them to try to
   disprove it. When only one model is available it rechecks its own claims in
   a fresh context. That is recorded as `same_model` and never counts toward
   the main queue.
6. **Validate and merge.** A verifier that confirms a correctness, quantum or
   docs claim can supply a reproduction: a test that must fail at the reviewed
   commit and a control test that must pass. Both run in a worker. Import or
   install failures, errors in place of assertion failures, and a failing
   control all count as `blocked`, never as a reproduction. Groups become
   finding records with stable IDs (`QOT-` plus a hash of repository and
   fingerprint).
7. **Human triage.** `triage.md` lists the main queue with all evidence and
   every verdict, and the low-priority list in brief. The reviewer records a
   decision (accept, reject, duplicate, defer, investigate) and a severity per
   finding in `decisions.yaml`.
8. **Fixes.** For accepted findings only. The first available model proposes
   exact search-and-replace edits (model-written diffs are often malformed).
   The harness applies them to a temporary clone, refusing paths outside the
   repository and old text that does not occur exactly once, and takes the
   diff from git. Invalid edits get one retry with the reason. The other
   models review the diff with `verify-fix`. A worker applies it to
   a throwaway copy, reruns the reproduction (which must now pass) and the
   existing tests (which must not regress). A fix with any objection stays
   `pending_objections`. A reviewer who agrees a fix removes the cause but
   says it changes behaviour (for example, replacing pickle with JSON changes
   the format a service must send) leaves a caveat that is kept with the fix
   and shown in the review. Non-security fixes get a planned branch
   `review/2026-10/<finding-id>`, which is not pushed until a person approves
   that branch. Security fixes are only ever exported as a private `.patch`.
9. **Publish.** A separate process renders the per-repository Report from
   accepted findings only, runs the sensitive-content check, and writes the
   local outbox. With `qot publish --live` it also uploads to Marqov, to two
   separately configured targets (`publish.marqov` in `config/harness.yaml`),
   each with its own Project id and key file. Per repository, a Workspace
   "<repo>: run record" and a Report "<repo>: review" go to the per-repository
   Project (one for all, or one each); they can carry security rows, so the
   publisher refuses to send them to the hub Project unless
   `repos.allow_hub` is set. Then a live upload first checks, read-only, that
   the hub's team has exactly one member, and stops if it has more. An API
   key cannot list team members, so when the API refuses the check the
   upload also stops, unless a person has recorded that they checked it in
   the web app (`hub.single_member_confirmed`). The Reports "Round one:
   overview" and (with `--public-summary`) "Round one: public summary", counts
   only, go to the hub Project, which a wider collaborators team may see.
   They leave out per-repository security and advisory counts unless
   `hub.show_security_counts` is true, because a count next to a repository
   name says it has a vulnerability before its maintainers have been told. No
   Project id is built in: a live run refuses to start until every target it
   needs is configured, and refuses a Project listed in `retired_projects`. Each document is one markdown block. Without `--live` it prints what it would upload and never reads the
   key. The sensitive-content check runs again on the exact text of each
   document immediately before upload; a document that fails is not sent. The
   publisher only writes documents it created, or one with exactly the same
   title if its record is lost; it never overwrites a document edited in the
   web app, never archives or deletes, and refuses the hand-written partner
   overview outright. Share links can be created only in the web app, so it
   prints the list of Reports to share.

### Queue and sensitivity rules

- **Main queue:** anything sensitive (see below), even when refuted, so a
  person always looks at secrets, credentials in logs and other security
  claims; or validated by reproduction; or found independently by two models;
  or confirmed by an independent verifier with no refutation; or disputed
  (confirmed and refuted). Everything else goes to the low-priority list.
  This is the starting rule, to be tuned after the first batch.
- **Sensitive:** the area is security, or any model or verifier marked
  security impact, or gitleaks, osv-scanner or zizmor raised it. Severity
  never decides sensitivity. A reviewer can add the flag; removing it needs a
  written reason.

### Earlier work by the reviewer

When the reviewer has already looked at a repository, what they found,
reported, fixed or rejected is listed in `prior-work.yaml` in that
repository's run folder (private, like the rest of the run record). Each item
enters the verify stage as a lead, the way a scanner's result does: a model
finding at the same place is merged with it rather than reported as new, and
an item no model raised is still checked by every model. An earlier
conclusion is evidence, not a verdict, and it never counts as an independent
model. The triage file shows what was raised before; a published review
links only the public upstream issue or pull request of a non-sensitive
finding.

## Reports

A Report contains a header (repository, commit, date, models and versions,
tools and their status, scope, completion), a scorecard with counts in four
categories (newly found security vulnerabilities, known dependency
advisories, correctness defects, and documentation, test and maintenance
defects), the triage list, finding details for non-security findings, and how
the report was produced.

Security rows show only an ID, the severity a person set, and the date
reported privately. Before writing, an automated check blocks the output if it
finds the exact location, title or claim of any sensitive finding,
secret-like values, exploit wording or email addresses. It is a backstop: a
person still reads every public title and summary.

We describe runs as *recorded, integrity-checkable and rerunnable*. We do not
claim that a rerun gives identical model answers.

## Status of v0.1

Works and tested:

- Schemas, the three adapters' command lines and parsing, the
  validate-and-retry-once rule, and hard timeouts.
- The clean environment and Claude Code isolation flags, verified live
  against the hostile probe for the installed version.
- The Docker worker and its limits, verified live (no network, no host
  environment, read-only source, output cap, timeout kill).
- All eight scanner wrappers, with parsers tested on real output from the
  pinned tool versions.
- Resumable units, usage-limit pause and resume, and per-unit token logs.
- Grouping, merging, queue and sensitivity rules, reproduction in a worker,
  fix proposal and checking, triage files, report rendering, the
  sensitive-content check and the local Marqov outbox.
- The reviewer sandbox for Codex and Antigravity, with the doctor probe
  failing on any personal configuration; all three CLIs pass it.
- Registry-only dependency installation, and existing test suites run before
  and after every proposed fix.
- Retries with backoff when a provider is at capacity, and reruns of those
  units on resume.
- Earlier work by the reviewer read as evidence (`prior-work.yaml`).
- Live Marqov publishing, tested against an in-process fake of the Project
  API; the read-only checks were run against the live API.

Stubbed or not built yet:

- **Codex and Antigravity** run in the reviewer sandbox. Egress from the
  sandbox is not restricted (see above).
- **Dependency installation** covers Python packages from PyPI only. Git,
  URL and private-index requirements are refused by the proxy and recorded.
  A project with compiled extensions cannot import them from the source copy
  (the installed copy is removed), so its suite fails at import and is
  reported as such.
- **OpenSSF Scorecard** is recorded as unavailable.
- **Team membership** cannot be read with a Marqov API key, so the
  single-member condition for per-repository documents in the hub is a
  recorded statement by a person, not a check.
- **Rust and C++** repositories: the worker image has no Rust or C++
  toolchain, so their existing tests do not run and fix checks rest on review.
- **Marqov sealing**: the platform refuses to seal a Project with more than
  one active Workspace (409, the interim guard from marqov-platform #2971),
  so a shared per-repository Project cannot be sealed while it holds several
  repositories' run records.
- **GitHub publishing** plans branch names and refuses to push.
- **Trends across runs**, the Capsule export of a run record, and the tests,
  maintenance and triage-contribution skills are later work.
- Rust and C++ scanners come with the repositories that need them.
