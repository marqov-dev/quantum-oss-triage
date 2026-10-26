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
| Publisher (`harness/publish`, run as its own process) | Writes the shareable documents; later, Marqov and GitHub | In future, the Marqov API key and a fork-only GitHub token. In v0.1, nothing |

The AI tools read; workers run. A test (`tests/test_publish.py`) fails if the
publisher imports the controller, adapters or workers, or the other way round.

### Workers

Each worker is a fresh container with:

- the source snapshot mounted read-only at `/src`;
- a throwaway writable copy at `/work` (tmpfs, 1 GB);
- `--network none` (only the osv-scanner step gets network, to query the
  advisory database; it reads lockfiles and runs no project code);
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
- **Codex** runs with a harness-owned `CODEX_HOME` (no MCP servers or
  profiles; only the sign-in file is linked), `--sandbox read-only` and
  `-c project_doc_max_bytes=0` so `AGENTS.md` is not read as instructions.
- **Antigravity** runs in plan mode with `--sandbox`, inside a hard 25-minute
  process timeout, because print mode has a reported headless hang. It still
  uses the operator's home directory, so its user-level settings are not yet
  isolated.

Codex and Antigravity read files by running shell commands on the host, even
in their read-only or plan modes. Text in a repository could get one of them
to run, say, `python -c "import pkg"`, which executes the project's code
outside a worker. The pipeline and `qot doctor` therefore refuse both
(`allow_host_shell_adapters: false`) until they run inside a reviewer sandbox:
a container that holds only the review copy and that CLI's sign-in. Claude
Code is allowed because it gets only the Read, Grep and Glob tools, confined
to the review copy by `--restricted`.

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

## The stages

Each unit of work is keyed by (repository, stage, skill, model) and saved when
it completes. A run that stops, for example on a subscription usage limit,
resumes from the last finished unit. Token usage is logged per unit in
`usage.jsonl` and summed per model in `manifest.json`.

One repository is finished by every available model before the next starts.
If any provider reports a usage limit, the repository pauses and the run
stops.

1. **Pin.** Clone (no hooks, no submodules, the operator's git config ignored)
   and record the commit SHA. Every later stage reads that commit only. The
   scope (included and excluded paths) is recorded.
2. **Scan.** gitleaks, osv-scanner, Semgrep (open Python and secrets rules,
   fetched at image build), zizmor, Ruff, Bandit, lychee (local links only)
   and the project's own tests, each in a worker. OpenSSF Scorecard needs a
   GitHub token and a GitHub remote, so it is recorded as unavailable in
   v0.1. Security and correctness leads become candidate findings. Lint,
   style and link results become hygiene counts. gitleaks values, authors and
   emails are redacted before anything is stored.
3. **Review.** Every review skill on every available model, independently.
   Models do not see the scanner leads, so their detections stay independent.
4. **Cross-check.** Likely duplicates are grouped first (same file, nearby
   lines, same area family or similar wording). Each group goes to the models
   that did not raise it, with `verify-finding`, which asks them to try to
   disprove it. When only one model is available it rechecks its own claims in
   a fresh context. That is recorded as `same_model` and never counts toward
   the main queue.
5. **Validate and merge.** A verifier that confirms a correctness, quantum or
   docs claim can supply a reproduction: a test that must fail at the reviewed
   commit and a control test that must pass. Both run in a worker. Import or
   install failures, errors in place of assertion failures, and a failing
   control all count as `blocked`, never as a reproduction. Groups become
   finding records with stable IDs (`QOT-` plus a hash of repository and
   fingerprint).
6. **Human triage.** `triage.md` lists the main queue with all evidence and
   every verdict, and the low-priority list in brief. The reviewer records a
   decision (accept, reject, duplicate, defer, investigate) and a severity per
   finding in `decisions.yaml`.
7. **Fixes.** For accepted findings only. The first available model proposes
   exact search-and-replace edits (model-written diffs are often malformed).
   The harness applies them to a temporary clone, refusing paths outside the
   repository and old text that does not occur exactly once, and takes the
   diff from git. Invalid edits get one retry with the reason. The other
   models review the diff with `verify-fix`. A worker applies it to
   a throwaway copy, reruns the reproduction (which must now pass) and the
   existing tests (which must not regress). A fix with any objection stays
   `pending_objections`. Non-security fixes get a planned branch
   `review/2026-10/<finding-id>`, which is not pushed until a person approves
   that branch. Security fixes are only ever exported as a private `.patch`.
8. **Publish.** A separate process renders the per-repository Report from
   accepted findings only, runs the sensitive-content check, and writes local
   Marqov documents (a Workspace "run record" and a Report "review").

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

Stubbed or not built yet:

- **Codex and Antigravity adapters** are written and unit-tested, but have
  not been run against real installs, and are refused by default because they
  run shell commands on the host. The next piece of work is the reviewer
  sandbox: a container per CLI holding only the review copy and that CLI's
  sign-in. Until then round one has one model. A claim that model makes is
  rechecked only by the same model, which does not count toward
  corroboration.
  Scanner leads are still checked independently by the model. Security
  claims reach the main queue anyway, through the sensitivity rule.
- **Dependency installation** in a registry-only network step is not built.
  Project tests run with only what the worker image has, so suites with
  dependencies fail at import and are reported as such.
- **OpenSSF Scorecard** is recorded as unavailable.
- **Live Marqov publishing** waits for marqov-platform PRs #2943 and #2971.
  `harness/publish/marqov.py` writes local files only and never reads the key.
- **GitHub publishing** plans branch names and refuses to push.
- **Trends across runs**, the Capsule export of a run record, and the tests,
  maintenance and triage-contribution skills are later work.
- Rust and C++ scanners come with the repositories that need them.
