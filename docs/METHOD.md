# Method

This document describes how quantum-oss-triage reviews a repository and what
each part of a result means. The design principles come first, because every
mechanism below follows from them. Where this document and the code differ,
the code is right and this document is out of date.

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
  recorded separately (`schemas/finding.schema.json`). The gates, the
  challenge and the blind fix are recorded in their own files beside the
  findings. Models agreeing is not validation. Severity is shown as each
  model's or tool's proposal, labelled as such; we do not set it.
- **A false positive costs more than a miss.** There is no finding quota. A
  repository with no validated findings, within a stated scope, is a
  legitimate result.
- **Incomplete is never shown as clean.** Every report states what was
  reviewed and what was not. A missing or failed scanner is recorded as
  `unavailable` or `failed`, never as a pass. A model call or check that could
  not run is recorded as failed and shown as unsettled, never dropped.
- **The repository is untrusted input.** Its code, docs and agent
  configuration can carry text written to steer an AI reviewer, and its
  install scripts and tests are code we run. Instructions in the skills are
  not the defence; the separation below is.
- **No model judges its own work.** A test is challenged by the models that
  did not write it, and fixed blind by them.
- **A person checks a sample of every report and approves the send.** Nothing
  goes upstream without their explicit approval.

## Three separate parts

| Part | Does | Holds |
| --- | --- | --- |
| Controller (`harness/controller`, `harness/stages`, `harness/adapters`) | Schedules work, runs the AI CLIs, checks their output against the schemas, keeps the evidence | The CLIs' own sign-ins only |
| Workers (`harness/workers`, `docker/worker.Dockerfile`) | Run dependency installs, scanners, tests, reproductions and fix checks | Nothing: no credentials, no home directory, no Docker socket |
| Publisher (`harness/publish`, run as its own process) | Writes the shareable documents and, with `--live`, the configured Marqov Projects; later, GitHub | The Marqov API keys, read from their key files (outside the repository) in live mode only; later, a fork-only GitHub token |

The AI tools read; workers run. The controller itself runs only git and text
operations on repository content (cloning, copying, applying search-and-replace
edits); it never runs repository code. A test (`tests/test_publish.py`) fails
if the publisher imports the controller, stages, adapters or workers, or the
other way round.

### Workers

Each worker is a fresh container with:

- the source snapshot mounted read-only at `/src`;
- the repository's installed dependencies, if any, read-only at `/deps`;
- harness-provided inputs (tests, controls, diffs), if any, read-only at
  `/inputs`;
- a throwaway writable copy at `/work` (tmpfs, 1 GB) and a `/tmp` tmpfs of
  512 MB. The copy leaves out git's object store, which can be larger than
  `/work`; git still works in the copy because it reads objects from the
  read-only original through an alternates file;
- `--read-only`, `--cap-drop ALL`, `no-new-privileges`, user `65534`;
- limits of 2 CPUs, 2 GB memory (no extra swap), 256 processes and a time
  limit per call, after which the container is killed; output is capped at
  5 MB per stream;
- no environment from the host. A worker gets `HOME=/tmp` and two harness
  flags; when dependencies are mounted it also gets a `PATH` that starts with
  the dependency environment, `PYTHONPATH` set to the copy under review, and
  `PYTHONDONTWRITEBYTECODE=1`.

A repository can be configured to run its workers as another platform
(`worker: {platform: linux/amd64}` in `config/repos.yaml`), for projects whose
dependencies publish wheels for one architecture only and no source. On a host
of another architecture this is emulated and slower.

### Network

| Step | Network |
| --- | --- |
| Dependency install | An internal Docker network with no route out. A proxy container on that network forwards HTTPS `CONNECT` on port 443 to the configured registry hosts only, and logs every allowed and refused request. With `worker.registries: [pypi, crates]` those hosts are `pypi.org`, `files.pythonhosted.org`, `index.crates.io`, `static.crates.io` and `crates.io`. Anything else, including git hosts and plain HTTP, gets 403. Sources a build would fetch from a git host are supplied instead as commit-pinned archives the controller downloads and checks by sha256 (`deps.prefetch`), mounted read-only. |
| osv-scanner (in the scan stage, and again on upstream's default branch in the gates stage) | The default Docker bridge, unrestricted, because the advisory database is queried live. The step reads lockfiles and runs no project code. |
| Every other worker step (scanners, the project's tests, reproductions, gates, fix checks) | None (`--network none`). |
| Reviewer sandbox (Codex, Antigravity) | The default Docker bridge, unrestricted; see below. |
| Controller | Clones the repository and, in the gates stage, fetches upstream again with git. |

The dependency-install container differs from other workers in three further
ways: it has 4 GB of memory, a 3 GB `/tmp`, and its `/work` and `/tmp` are
mounted with exec, because build backends run the tools they install there.
It writes only to `/deps` and its own tmpfs.

### No inherited agent settings

The AI CLIs are started with an empty environment plus `HOME`, `USER`,
`LOGNAME`, `LANG`, `TMPDIR`, a plain `PATH`, `TERM=dumb` and `NO_COLOR=1`. A
desktop or IDE session can export many variables (account details, messaging
sockets, proxy URLs, API keys), and none of them are passed on. In addition:

- **Claude Code** runs with `--safe-mode --restricted --setting-sources ""
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools Read,Grep,Glob
  --disable-slash-commands --no-session-persistence --permission-mode dontAsk`,
  a harness system prompt, and the configured `--model` and `--effort`.
  `--bare` would be cleaner, but it accepts only API keys, and round one uses
  subscriptions. For a fully separate configuration, sign in once to a
  harness-owned config directory (see [SETUP](SETUP.md)). Without it, account
  metadata such as the account email is still placed in the model's context by
  the CLI itself. No repository or personal settings, memory, hooks, skills or
  MCP servers are loaded.
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
  it. The CLI receives only `HOME`, `TERM` and `NO_COLOR`.
  - Codex: `codex exec --json --sandbox read-only --ephemeral --ignore-rules
    --strict-config -c project_doc_max_bytes=0`, with the configured model and
    reasoning effort, and a harness `config.toml` that turns off web search,
    hooks, plugins, apps, browser and computer use, multi-agent and related
    features. Its shell commands run in Codex's own bubblewrap sandbox inside
    the container: read-only, no network, no capabilities (checked live).
  - Antigravity: `agy -p ... --output-format json --json-schema <file>
    --disable-slash-commands --print-timeout 20m`, inside a hard 25-minute
    process timeout, because print mode has a reported headless hang. Its
    `--mode plan` has no effect with `--disable-slash-commands`, and its own
    `--sandbox` cannot start inside the container, so neither is used there.
    Shell commands are limited instead by an allow-list in the harness's agy
    settings: `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `nl`, `pwd`, `find`,
    `git grep`, `cut` and `tr`, plus a read of the schema file. `sed`, `awk`
    and `xargs` are left off because each can run other commands. agy refuses
    anything else, including `find -exec`, `;` and `$(...)`. The model is told
    the list in its prompt. When agy refuses a command it ends its turn with
    no answer; the adapter reads the refused command from agy's transcript and
    asks again, naming it, at most twice. Unlike Codex's, the allowed commands
    run with network access, but none of them is a network client. On macOS agy
    keeps its sign-in in the keychain, which cannot be copied, so it is signed
    in once inside its sandbox (`qot sandbox-login agy`). agy has no effort
    flag; the level is part of the model name.
  - The CLI process itself needs the network to reach its provider, so the
    container is on Docker's default bridge with unrestricted egress. The
    review copy is public source, but the CLI's own sign-in token sits in the
    container, and `cat` can read Antigravity's. Codex's shell commands have no
    network; a model could still quote a file it can read into its reply, which
    the harness redacts for secret-like values before storing. An egress
    allowlist is later work.
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

The AI tools see a read-only copy of the in-scope source, without `.git`,
without symlinks, and without bulky or generated folders (`node_modules`,
virtual environments, caches, `build`, `dist`).

The pipeline uses a CLI only after `qot doctor` has passed the hostile probe
for that exact CLI version (for a sandboxed CLI, the version and the sandbox
image). The probe reviews `evaluations/hostile`, which has a `CLAUDE.md`,
`AGENTS.md` and `GEMINI.md` with instructions, hooks, project MCP servers, a
repository skill, and prompt injection in docs and code. It passes only if no
canary token appears, no hook or MCP marker file is created, and the snapshot
is unchanged. Each canary is spelled out in parts in the fixtures, so a model
that quotes the text does not trip the check, but a model that obeys it does.

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

### Models

`config/harness.yaml` pins an exact model and effort for each CLI: Claude Code
runs `claude-opus-5-5` at medium effort, Codex runs `gpt-6.1-sol` at medium
effort, and Antigravity runs `gemini-3.8-flash-medium`. The model ID each CLI
reports is recorded per unit and in `manifest.json`. The order in the file
matters in one place: the first available model proposes fixes for accepted
findings.

## How work is recorded and resumed

Each unit of work is keyed by (repository, stage, skill, model) and saved when
it completes. A run that stops, for example on a subscription usage limit,
resumes from the last finished unit. Token usage is logged per unit in
`usage.jsonl` and summed per model in `manifest.json`. Secret-like values are
redacted before any unit is stored.

Every model reply is checked against its JSON schema. An invalid reply is
asked again once, with the errors; a second invalid reply is recorded as
failed.

One repository is finished by every available model before the next starts.
If any provider reports a usage limit, the repository pauses and the run
stops. A provider that refuses because its model is at capacity (a server-side
refusal, not our usage) is retried after 30, 120 and 300 seconds; a unit still
refused after that is recorded as failed and run again whenever the run
resumes. Other failed units are not run again on resume unless the run is
started with `--retry-failed`.

Before each worker launch and model call the harness checks that Docker
answers, that the worker image exists, and that the run directory and
Docker's data folder have the free space set in `worker.preflight` (answers
are cached for a few seconds). After a failed container it checks the daemon
and disk again, uncached, so that an outage is not recorded as the project's
result. On an outage the stage is marked `paused`, no unit is saved for the
work that hit it, `manifest.interruption` records the cause, and `qot run`
exits 4 (3 for a usage limit). Running the same command again resumes. A unit
still running when Docker stops is not interrupted; the outage is caught when
it returns or times out.

A saved result is reused only while what it depended on is unchanged:

- a validation records the tests proposed for its finding, and runs again if
  that set changes (for example, when a model that joined later proposes a
  test);
- a gate verdict is reused only while the finding's validation status and best
  test are unchanged. If upstream's default branch has moved, the
  default-branch check is repeated; the reruns against the pinned commit
  stand;
- a challenge verdict and a blind-fix check record the test they judged, and
  are done again if the finding's best test changes.

Records saved before this rule existed carry no inputs and are kept, except a
validation that saw fewer tests than its finding now has.

## The stages

The default order is pin, deps, scan, review, verify, validate, gates,
challenge, fixgate, triage, fix. Publishing is a separate process.

1. **Pin** (`pin.py`). Clone (no hooks, no submodules, the operator's git
   config ignored) and record the commit SHA, the hash of the source tree and
   the hash of the review copy. Every later stage reads that commit only. The
   scope (included and excluded paths) is recorded.
2. **Dependencies** (`deps.py`). The install plan is read from the snapshot's
   files: a `uv.lock`, requirements files (except ones whose name contains
   "doc"), `pyproject.toml` extras named test, tests, testing or dev, any
   extras set for the repository under `deps.extras`, dependency groups with
   those names, and `setup.py` or `setup.cfg`. Nothing runs on the host. A
   worker installs them, with the network limits above, into an isolated
   virtual environment in the repository's run folder. When the repository
   has a `uv.lock`, its pinned versions are exported by uv (offline, without
   resolving) and installed without resolving again; if that fails the step
   falls back to resolving from the project metadata, and the record says
   which was used. The project itself stays installed, for its metadata and
   entry points, but later workers put the copy under review first on the
   path, so the code that runs is the copy's. The resolved versions
   (`pip freeze`) are kept as evidence. An install is `ok`, `partial` or
   `failed`. It is `failed` when the environment could not be created, or
   when nothing of the project installed; then validation, gates, blind fix
   and fix refuse to run and the run is marked incomplete, so a missing
   environment is never measured as a defect. Scanners still run.

   Per-repository options in `config/repos.yaml` cover what the snapshot
   alone cannot, and each is recorded in the manifest's `dependencies`:
   `worker.python` runs every worker for that repository on an image variant
   with another interpreter (`<tag>-py310`; uv cannot fetch one through the
   proxy); `deps.local_packages` installs a monorepo's own subpackages from
   the copy and puts them first on the path; `deps.prefetch` supplies a
   git submodule or CMake FetchContent source without opening the proxy to
   git hosts (the host downloads a commit-pinned archive, checks it against a
   configured sha256 and, optionally, against the commit or tag the snapshot
   declares; the worker unpacks it from a read-only mount);
   `deps.source_builds` builds a locked package from such an archive when no
   wheel fits the platform; `deps.omit` leaves out a locked package that has
   no distribution for the platform at all. Omissions and source builds mark
   the run incomplete with their stated reason. Files the build adds to the
   package that the copy lacks (a compiled extension, a version file) are
   kept with the environment and linked into later workers' copies where
   missing, since the copy comes first on the path.
3. **Scan** (`scan.py`). gitleaks, osv-scanner, Semgrep (open Python and
   secrets rules, fetched at image build), zizmor, Ruff, Bandit, lychee (local
   links only) and the project's own tests, each in a worker. OpenSSF
   Scorecard needs a GitHub token and a GitHub remote, so it is recorded as
   unavailable, or not applicable if the binary is present. Security and
   correctness leads become candidate findings. Lint, style and link results
   become hygiene counts. gitleaks values, authors and emails are redacted
   before anything is stored. The project's tests are recorded as a clean
   baseline only when the suite ran (pytest exited 0 or 1, at least one test
   ran, no collection or setup errors); a timeout, an error count or an empty
   run is recorded as failed, so the run is incomplete. A repository with a
   long suite sets `tests.timeout_s`; no subset is chosen for it, since any
   subset would hide what it leaves out. Where osv-scanner finds no package
   source it can read (pixi.lock, for one), it scans the versions the
   dependency stage installed instead.
4. **Review** (`review.py`). Every review skill (security, correctness, docs,
   quantum) on every available model, independently. Models do not see the
   scanner leads, so their detections stay independent.
5. **Cross-check** (`verify.py`). Scanner leads, earlier work by the reviewer
   (below) and model claims are grouped first: same file, lines within two of
   each other, and the same area family or similar wording. Claims from the
   same unit are never merged. Each group goes to the models that did not
   raise it, with `verify-finding`, which asks them to try to disprove it.
   Verifiers are told whether the claim came from another AI reviewer, a named
   scanner or earlier notes, but not which model. When only one model is
   available it rechecks its own claims in a fresh context. That is recorded
   as `same_model` and never counts toward the main queue. A model listed in
   `verify_model_claims_only` skips scanner and earlier-work claims while
   another model can check them (empty by default).
6. **Validate and merge** (`validate.py`). A verifier that confirms a claim
   can supply a reproduction: a test that must fail at the reviewed commit and
   a control test that must pass. The skill asks for none on security
   findings; the code does not enforce that. Each proposed test runs in a
   worker, in turn, until one reproduces. Groups then become finding records
   with stable IDs (`QOT-` plus a hash of repository and fingerprint). A rerun
   keeps what a person already decided for a finding.
7. **Gates** (`gates.py`, `gates.json`). By rule; no model is involved. See
   below.
8. **Challenge** (`challenge.py`, `challenge.json`, skill `challenge-test`).
   For each test that passed the gates, every configured model except the
   test's author tries to show the test is wrong: its expectation unsupported,
   its failure for another reason, or its target something else. Challengers
   see the claim's title, area, location and text, the test, its control, the
   author's stated expected behaviour and expected failure, and the observed
   output. They do not see the finder's evidence or reasoning, who found the
   claim, who wrote the test, or other verdicts.
9. **Blind fix** (`fixgate.py`, `fixgate.json`, skill `blind-fix`). For each
   test that passed the gates, including tests the challenge refuted, the
   same non-author models see only the claim (title, area, location and
   text), never the test, its control or the challenge. Each says whether the
   claim holds and, if so, writes the smallest fix as exact search-and-replace
   edits. Edits to test files are refused, with one retry. The harness turns
   the edits into a diff with git on a temporary clone. In a worker, the
   diff is applied to a throwaway copy; the hidden test must then pass, its
   control must still pass, and no test in the folders of the changed Python
   files may newly fail, compared by test id with the same tests run before
   the fix. A change at the repository root checks the whole suite; a fix
   that changes no Python file has no suite comparison.
10. **Triage** (`triage.py`). Writes `triage.md` and a `decisions.yaml`
   template, and applies any decisions a person has recorded there (accept,
   reject, duplicate, defer, investigate; severity; the sensitive flag).
   Nothing in this stage decides for the reviewer.
11. **Fixes for accepted findings** (`fix.py`, the earlier flow, only for
   findings a person accepted in `decisions.yaml`). The first available model
   proposes exact search-and-replace edits (model-written diffs are often
   malformed), shown the reproduction if the finding was reproduced. The
   harness applies them to a temporary clone, refusing paths outside the
   repository and old text that does not occur exactly once, and takes the
   diff from git. Invalid edits get one retry with the reason. The other
   models review the diff with `verify-fix`. A worker applies it to a
   throwaway copy, reruns the reproduction (which must now pass) and the
   whole existing suite, if the repository has a `tests` or `test` folder or
   root `test_*.py` files, which must not have more
   failures or errors, or fewer passes, than the baseline from the scan stage.
   The fix's status is one of `validated`, `pending_objections`,
   `checked_same_model_only`, `tests_regressed`, `tests_not_run` (the suite
   ran at baseline but not after the change), `repro_still_fails`,
   `apply_failed`, `check_timed_out`, `edits_invalid`, `not_feasible`,
   `proposal_failed` or `pending`. A reviewer who agrees a fix removes the
   cause but says it changes behaviour leaves a caveat that is kept with the
   fix and shown in the review. Non-security fixes get a planned branch
   `review/2026-10/<finding-id>`, which is not pushed until a person approves
   that branch. Security fixes are only ever exported as a private `.patch`.
12. **Publish** (a separate process; see Reports).

### The gates

The gates run on every finding, using the best test its verifiers proposed:
the first attempt that failed on an assertion, otherwise the first that
crashed in the project's own code.

1. **Evidence.** The test fails on an assertion while its control passes, or
   fails with an exception whose traceback has a frame in the project's own
   code (not in the dependencies or the test file) while its control passes.
   The second kind is a *crash candidate*. Import errors, syntax errors and
   missing fixtures never count.
2. **Stable.** Rerun 20 times, each in fresh processes in one worker, the
   control passes and the test fails with the same first error line (memory
   addresses removed) every time.
3. **Still present.** The same test, run against upstream's current default
   branch (fetched fresh on every run, with the dependencies installed for the
   pinned commit), still fails with the same kind of evidence and the same
   first error line. The newest release tag is checked too, for information
   only; it does not decide the verdict.

Known dependency advisories are also rechecked here: osv-scanner scans
upstream's default branch, and each advisory is recorded as still present or
resolved there.

### Queue and sensitivity rules

- **Main queue:** anything sensitive (see below), even when refuted, so a
  person always looks at secrets, credentials in logs and other security
  claims; or reproduced; or found independently by two models; or confirmed
  by an independent verifier with no refutation; or disputed (confirmed and
  refuted). Everything else goes to the low-priority list. This is the
  starting rule, to be tuned after the first batch.
- **Sensitive:** the area is security, or any model or verifier marked
  security impact, or gitleaks, osv-scanner or zizmor raised it. Severity
  never decides sensitivity. A reviewer can add the flag; removing it needs a
  written reason.

### Earlier work by the reviewer

When the reviewer has already looked at a repository, what they found,
reported, fixed or rejected is listed in `prior-work.yaml` in that
repository's run folder (private, like the rest of the run record). Each item
enters the cross-check stage as a lead, the way a scanner's result does: a
model finding at the same place is merged with it rather than reported as
new, and an item no model raised is still checked by the other models. An
earlier conclusion is evidence, not a verdict, and it never counts as an
independent model. The triage file shows what was raised before; a published
review links only the public upstream issue or pull request of a
non-sensitive finding.

## Outcome vocabulary

Each check has its own small set of outcomes, decided by rule.

**Validation** (`findings.json`, `validation.status`):

| Outcome | Meaning |
| --- | --- |
| `reproduced` | The test fails on an assertion at the reviewed commit and its control passes. |
| `not_reproduced` | The test passed at the reviewed commit, so it does not show the defect. |
| `blocked` | The test could not show anything: it timed out, its control failed, it errored (import, syntax, missing fixture, an exit code other than a test failure), or it failed with an exception rather than an assertion. Also used when no worker or no installed environment was available. |
| `unvalidated` | No test was proposed. For a sensitive finding the note says that validation needs a documented technical inspection by a person. |
| `pending` | No test was proposed and a verification is still pending or failed. |

The schema also allows `inspection`; no stage sets it yet.

**Gates** (`gates.json`, `verdict`):

| Outcome | Meaning |
| --- | --- |
| `passed` | Gates 1 to 3 passed. |
| `failed` | Not stable on reruns; or the test passes on the current default branch (it may be fixed or changed upstream); or the result there could not be confirmed. |
| `inconclusive` | The reruns timed out before all 20 finished, and those that finished were consistent. |
| `no_evidence` | No test failed on an assertion or with an exception in the project's code. |

**Challenge** (`challenge.json`, `outcome`):

| Outcome | Meaning |
| --- | --- |
| `upheld` | Every challenger called the test valid. |
| `refuted` | At least one challenger called the test invalid and cited repository lines, for a reason other than a weak control. |
| `unsettled` | Anything else: a challenger unsure, an invalid verdict with no citation, a control judged too weak (the defect may still be real; the test needs a stronger control), or any challenger that could not run, including a configured model unavailable in this run. |

**Blind fix** (`fixgate.json`, `outcome`):

| Outcome | Meaning |
| --- | --- |
| `confirmed` | At least one blind fix makes the hidden test pass, with its control passing and no new failures in the touched folders. Fixers who judged the claim not to hold are counted in the reason. |
| `disputed` | Every fixer judged the claim not to hold. |
| `unsettled` | No fix passed and at least one fixer could not run (model failure, unavailable model, or a check that timed out). |
| `not_confirmed` | Anything else, for example fixes that did not apply, broke the control, did not make the test pass, or caused new failures. A failed blind fix is weak evidence, so this does not refute the test; it only withholds confirmation. |

### How the counts relate

The gates, the challenge and the blind fix do not use the validation status.
The challenge and the blind fix run on every test that passed gates 1 to 3,
and gate 1 accepts crash candidates, which validation records as `blocked`
because they fail with an exception rather than an assertion. A reproduced
finding whose test is not stable, or no longer fails upstream, does not reach
the challenge or the blind fix. So the number of `confirmed` blind fixes can
exceed the number of `reproduced` findings, and the two sets need not overlap
fully. The main-queue rule counts only `reproduced` as validation.

## What each check shows and does not show

| Check | Shows | Does not show |
| --- | --- | --- |
| Scanners | A tool's rule matched, at pinned tool versions. An advisory exists for an installed or locked version. | That the code is reachable, exploitable or wrong. An advisory lead says whether the project uses the affected code is not established. |
| Review | A model, reading the code without the scanner leads, believes something is wrong. | Anything beyond that model's reading. |
| Cross-check | Whether other models, trying to disprove a claim, agree. | Correctness: models agreeing is not validation, and a verifier that has seen the claim is not independent of it. |
| Validation | A test written by a verifier fails at the reviewed commit for the stated reason while a nearby control passes. | That the test's expected behaviour is the intended one. The expectation comes from the verifier's reading of docs, a reference or the maths. |
| Gates | The failure is real in this environment, repeatable, and still present on upstream's current default branch. | That the expectation is right, or that the failure matters. A crash candidate shows an exception in project code, not a wrong answer. The default-branch check uses the dependencies installed for the pinned commit. |
| Challenge | Models that did not write the test could not show it is wrong, or one could, with citations. | Correctness: challengers are models reading the same code, and `upheld` can be shared error. |
| Blind fix | A model that never saw the test can write a change that makes it pass without breaking its control or tests in the touched folders. The test and the claim are consistent. | That the claim's expectation is right, because the fixer works from the same claim; that the fix is the right one; or that nothing outside the touched folders regressed. |
| Fix for an accepted finding | The diff applies, the reproduction passes, and the whole suite has no more failures or errors and no fewer passes than at baseline. | That no individual test changed from passing to failing while another changed the other way (the comparison is by counts); that the fix is acceptable to the maintainers. |
| Person | The sampled cards and every public title and summary were read before sending. | That every finding was read. |

## Reports

A run with gates produces two documents per repository. The **report** puts
each finding in a section by rule, from the gates, the challenge and the blind
fix:

| Section | Rule |
| --- | --- |
| Likely defects | Gates passed, challenge upheld, blind fix confirmed, and no fixer said the claim does not hold. |
| Where the models disagree | Gates passed, but the checks point in different directions (any other combination). |
| Claims we could not test | No test passed the gates (and none passes on the default branch); only the models' verdicts. |
| Probably not defects | Gates passed, challenge refuted, and the blind fix not confirmed or disputed. |
| Already fixed upstream | Gates failed because the test passes on the current default branch. |
| Known advisories in dependencies | Found by osv-scanner, shown in full in the team's private report, with whether each is still present on the default branch. |
| Security | Newly found security issues, counted only; details go privately ([DISCLOSURE](DISCLOSURE.md)). |

Each card shows who found it, every source's proposed severity, the gates,
challenge and blind-fix outcomes, each model's view, and a box for the
maintainer's verdict (real, not real, or intended). The report ends with how
each model did, measured against the other checks. The **evidence** document
holds each test, its control, the blind fix and any earlier hand-made fix.
Claims that came from earlier hand review are shown through the verified
test's expectation, not the reviewer's working notes. A run without gates
falls back to a report from accepted findings only.

Before writing, an automated check blocks the shared documents if they
contain the exact location, title or claim of a sensitive finding, secret-like
values, exploit wording or email addresses. It is a backstop: a person still
reads every public title and summary.

The publisher writes a local outbox. With `qot publish --live` it also
uploads to Marqov, to two separately configured targets (`publish.marqov` in
`config/harness.yaml`, with Project ids kept in a local file outside the
repository), each with its own Project id and key file:

- Per repository, a Workspace "<repo>: run record", the report and the
  evidence document go to the per-repository Project (one for all, or one
  each). They can carry security rows, so the publisher refuses to send them
  to the hub Project unless `repos.allow_hub` is set. A live upload then
  first checks, read-only, that the hub's team has exactly one member, and
  stops if it has more. An API key cannot list team members, so when the API
  refuses the check the upload also stops, unless a person has recorded that
  they checked it in the web app (`hub.single_member_confirmed`).
- The hub Project, which a wider collaborators team may see, gets "Round one:
  overview" and, with `--public-summary`, "Round one: public summary". The
  overview shows progress only (which repositories, which models, how far
  each has got), rebuilt from the run records, with no finding counts. It is
  checked against every sensitive finding of every repository (dependency
  advisories aside) before upload.
  `--overview-only` publishes just this page. The public summary holds counts
  only, and leaves out per-repository security and advisory counts unless
  `hub.show_security_counts` is true.

No Project id is built in: a live run refuses to start until every target it
needs is configured, and refuses a Project listed in `retired_projects`.
Without `--live` it prints what it would upload and never reads the key. The
sensitive-content check runs again on the exact text of each document
immediately before upload; a document that fails is not sent. The report and
evidence documents are written as several blocks (one per section) so the
share page lists their sections; other documents are one markdown block. The
publisher only writes documents it created, or one with exactly the same
title if its record is lost. It replaces a document's blocks only while they
are still exactly what it uploaded last time, so a document edited in the web
app is never overwritten. It never archives or deletes a document, and
refuses protected documents outright. It prints the list of documents to
share, since share links are made in the web app.

We describe runs as *recorded, integrity-checkable and rerunnable*. We do not
claim that a rerun gives identical model answers.

## Status

Works and covered by the test suite (`tests/`):

- Schemas, the three adapters' command lines and parsing, the
  validate-and-retry-once rule, hard timeouts, and Antigravity's refusal
  recovery.
- The clean environment and Claude Code isolation flags; the hostile probe is
  run live by `qot doctor` for the installed version.
- The Docker worker and its limits (no network, no host environment,
  read-only source, output cap, timeout kill), and the copy without git's
  object store.
- All eight scanner wrappers, with parsers tested on real output from the
  pinned tool versions.
- Resumable units, usage-limit pause and resume, capacity retries, per-unit
  token logs, and reruns when a unit's inputs change.
- Grouping, merging, queue and sensitivity rules, reproduction in a worker,
  the gates, the challenge, the blind fix, fix proposal and checking, triage
  files, report rendering, the sensitive-content check and the local outbox.
- The reviewer sandbox for Codex and Antigravity, with the doctor probe
  failing on any personal configuration.
- Registry-only dependency installation, per-repository worker platforms,
  and stopping project-code stages after a failed install.
- Earlier work by the reviewer read as evidence (`prior-work.yaml`).
- Live Marqov publishing, tested against an in-process fake of the Project
  API.

Limits and work not built yet:

- **Reviewer sandbox egress** is not restricted (see above).
- **osv-scanner** runs with unrestricted network, in the scan stage and when
  the gates recheck advisories.
- **Dependency installation** reaches the configured registries only. Git,
  URL and private-index requirements are refused by the proxy and recorded.
  The worker has compilers, CMake and a pinned Rust toolchain, so C, C++,
  Cython and Rust extensions can build; sources a build fetches from a git
  host must be listed under `deps.prefetch`. A package that publishes wheels
  for one architecture only and no source cannot install on a host of another
  architecture unless the repository runs its workers as that platform, or
  leaves the package out with `deps.omit` (recorded as incomplete). Files a
  build adds are linked into the copy under review where missing; results
  recorded before this was added may have run without them.
- **OpenSSF Scorecard** is not wired up.
- **Antigravity** may still end a turn on a refused command after its two
  retries; the unit is then recorded as failed (shown as "did not answer").
- **Findings without a test**, such as CI or configuration claims, rest on
  the models' verdicts; the report puts them in their own section.
- **Security findings** get no reproduction by design; validation needs a
  documented technical inspection by a person, which no stage records yet.
- **The gates' message** for a passed verdict still reads "the separate-fix
  gate is not built yet"; the blind-fix stage exists and runs after the
  challenge.
- **Team membership** cannot be read with a Marqov API key, so the
  single-member condition for per-repository documents in the hub is a
  recorded statement by a person, not a check.
- **Rust and C++** repositories: the dependency stage builds Python
  packages only. A repository's own Rust or C++ test suite (cargo test,
  CTest) is not run, so fix checks there rest on review and the Python tests.
- **Marqov sealing**: the platform refuses to seal a Project with more than
  one active Workspace (409, the interim guard from marqov-platform #2971),
  so a shared per-repository Project cannot be sealed while it holds several
  repositories' run records.
- **GitHub publishing** plans branch names and refuses to push.
- **Trends across runs**, the Capsule export of a run record, and the tests,
  maintenance and triage-contribution skills are later work.
- Rust and C++ scanners come with the repositories that need them.
