# quantum-oss-triage literature lane D: usefulness to an overwhelmed team, and safety to fork

Search date 2 November 2026. Nothing was contacted and no repository was touched.

**Bottom line.** The maintainer problem moved during 2026. In January the complaint was false reports. By October, curl says the reports are mostly accurate and the problem is volume. So a report that is merely accurate can still add to the burden. It has to be short, reproducible, ranked, paced to the team's hours, and honest that it says nothing about what it missed. On safety, the strongest single finding is that running a hostile repository's tests is the worst-case agent task, and that repository config files beat prompt-level defences. Isolation, not model choice or rules text, has to carry the safety case.

**Conventions.**
- "Verified" means I read the number on the primary page or PDF. Most arXiv reads went through a page-summarising fetch, not line-by-line reading, so check any number quoted externally.
- UNVERIFIED means I saw it only in a snippet or secondary source.
- All 51 main arXiv IDs below were checked against the arXiv API and resolve to the claimed title. 2610.21914 appeared in an API search result with its title. 2510.18508 and 2605.02273 were confirmed from their abs pages.
- PR = peer reviewed or accepted at a peer-reviewed venue, as stated on the page. Pre = preprint. Several MSR'26 items are short Mining Challenge papers, not full research-track papers.
- "Tool authors" flags self-reported results.

---

## 1. Sources read

### Maintainer burden

- **2607.04003** Pre. Afroz et al. Mixed methods: 294 repos, about 1.2M PRs, causal time series, 11 interviews, 229 survey responses. PR volume +6.8%, merge ratio -1.1%, one-time contributors' merge rate -18.18%. Endorsement: CI gates 73%, no-review cutoffs 71%, understanding checks 67%, AI first-pass reviewers 48%, triage rotation 34%. Issue-side results are uncertain (placebo tests significant). No triage tool evaluated.
- **2603.26487** PR, ASE 2026. Yang, He, Zhou. Document analysis of 67 projects. 59.7% boundary-and-accountability, 20.9% prohibitionist, 19.4% tool-agnostic. Review capacity is the central pressure. Advice: diagnose the specific bottleneck before choosing a policy. Not a prevalence estimate.
- **2609.07542** Pre, under review at TOSEM. Hora, Robbes, Zacchiroli. 281 AI policies: 83.3% permit AI, 67.3% require high human involvement, 48.8% require disclosure.
- **2603.27249** Pre. Baltes, Cheong, Treude. 1,154 Reddit and HN posts, 15 codes. Qualitative, no prevalence. Frames slop as a tragedy of the commons.
- **2607.01904** Pre. He et al. One company, 802 developers, 196,212 merged PRs. Load per reviewer doubled; automated review overtook human review in coverage. No randomised assignment.
- **2602.23905** PR, MSR'26. 22,953 PRs. Low-experience vibe coders against high-experience: 2.15× commits, 4.52× review comments, 31% lower acceptance, 5.16× resolution time.
- **2605.02273** PR, EASE 2026. Abstract only. Most AI PRs get no review; review is mostly by agents. Review metrics may misstate human oversight.
- **Linux Foundation Research, Oct 2026** Foundation blog read. About 25% of incoming PRs estimated low-quality AI, 31% in larger projects; 64% of maintainers in projects over 50 contributors report longer review cycles; 35% have a permitting policy, 10% ban. Self-reported estimates. Sample of 234 is UNVERIFIED (snippet; the blog does not state it).

### Primary maintainer accounts

- **curl, Stenberg, "Death by a thousand slops" (Jul 2025)** Verified. About 2 reports a week; 20% slop; 5% valid; each report takes 30 minutes to 3 hours of 3 to 4 people; team of 7, some with about 3 hours a week.
- **"The end of the curl bug-bounty" (Jan 2026)** Verified. Confirmed rate fell from above 15% to below 5%; ended 31 Jan 2026. Key line: PRs are not a major problem for curl because tests and CI catch low-quality contributions.
- **"curl summer of bliss" / "What the bliss taught us" (Jun, Aug 2026)** Verified for the August post; June via search excerpt. One-month intake pause in July. Possibly "best project decision in a long while"; maintainers reviewed queued PRs; no incidents identified yet. A backlog and more duplicates were expected.
- **"Mythos finds a curl vulnerability" (May 2026)** Verified. 5 claimed vulnerabilities; 1 real, 3 false positives (documented API behaviour), 1 "just a bug". About 20 other bugs, barely any false positives. Reviewing the five took the team several hours.
- **"A new breed of analyzers" (Oct 2025)** Verified. Over 400 suspected issues in total; about 50 fixes from one list of 200+ (roughly 25%). Valued format: title, file and line, short code quote, reachability and impact rationale. Weakness: stale comments misled the tool.
- **"ignore the slop" (22 Oct 2026)** Verified. Hundreds of recent reports, all AI-involved. Slop practically gone since spring. Reports run to hundreds of lines and are repetitive. AI still poor at bug-versus-vulnerability judgement and severity. Good reports open with a short human explanation.
- **"Do minor curl vulnerabilities in the open" (20 Oct 2026)** Verified. From 26 Oct, LOW and MEDIUM go to public GitHub issues; over 90% of submissions could be quickly assessed below HIGH.
- **"A curl audit by Aisle" (Oct 2026)** Verified. 35 CVEs from AI tooling plus human validation. No false-positive data given. Stenberg is positive.
- **Linux kernel security-bugs documentation** Verified. Short, plain text, verifiable facts only; tool must produce and test a reproducer; test any fix; AI-found bugs treated as public; reproducer shared only on request.
- **LWN 1070698 (May 2026)** Verified. Same flaws arriving independently inside embargoes; Dahlman puts LLM fixes in the "coin flip range"; Copy Fail (CVE-2026-31431) went public with no distro fixes ready.
- **QEMU security process** Verified. AI disclosures "highly likely to be independently re-discovered"; arbitrary embargoes generally rejected; AI may be used in triage.
- **rclone** via InfoQ. About 20 disclosures in 10 years, then over 40 in a month. Secondary quote of a primary HN post.
- UNVERIFIED, secondary only: Tarreau's 2 to 3 a week rising to 5 to 10 a day; tldraw closing external PRs; Ghostty's AI policy; Torvalds "almost entirely unmanageable" (LWN search excerpt only).

### Empirical studies of AI pull requests

- **2507.15003** Pre. Li, Zhang, Hassan. AIDev: 456,000+ PRs, 61,000 repos, 47,000 developers, 5 agents. Agents faster, accepted less; simpler code.
- **2602.04226** Pre. Nakashima et al. 654 rejected PRs. 7 agent-only rejection modes. 67.9% have no explicit reviewer feedback.
- **2602.02345** PR, MSR'26 Mining Challenge. Rahman et al. Qualitative in the abstract. Commit quality varies independently of acceptance.
- **2605.22534** PR, MSR'26. Peralta et al. 717 manually coded PRs. Rejections: 35.7% agent failure, 31.2% workflow, 33.1% unknown. Merged: 79.1% no feedback loop. Merge and reject labels are unreliable measures of agent performance.
- **2606.13468** PR, MSR'26. 3,225 fix PRs, 46.41% rejected, 306 coded (κ 0.605). Inactivity 17.3%, CI failure 6.9%, superseded 5.9%, incorrect fix 5.6%, no clear reason 49.3%.
- **2601.15195** PR, MSR'26. 33,596 PRs, 71.48% merged. 600 coded: abandoned 38%, duplicates 23%, CI or test failure 17%, incorrect implementation 3%. Each extra failed check lowered merge odds about 15%. Percentages are on 600 although 562 were accessible.
- **2607.21832** Listed as POMACS. 9,428 agentic PRs in Python repos; adjusted merge rates Claude 84.3%, Codex 73.5%, Devin 43.0%. Comparable or lower defect proneness stated in the introduction; RQ3 numbers not read.
- **METR note, 10 Mar 2026** Not peer reviewed. 296 PRs, 4 maintainers, blinded. Grader pass rate exceeds normalised maintainer merge by 24.2 points. About half of test-passing PRs would not be merged. Golden patches merged 68%. No CI, one attempt, newest model Sonnet 4.5.

### AI triage and code review tools

- **2607.03316** Pre. Lin et al. 31,073 CodeRabbit review-feedback pairs, 239 repos. 36.4% accepted, 56.3% rejected, mainly false positives, redundancy, out of scope, or misaligned intent.
- **2607.21997** Pre. Cynthia et al. About 54,700 comments. Resolved: Copilot 72.9%, Cursor 67.2%, Codex 54.8%. Largest non-acceptance theme: intentional design decision (112 of 470). Inline suggestion strongest predictor (75.5% against 64.6%). AUC only 0.58.
- **2604.03196** PR, MSR'26 Mining Challenge. 3,109 PRs. CRA-only merge 45.20%, human-only 68.37%. 12 of 13 agents below 60% signal. Association only, keyword scoring. Rebuts vendor claims.
- **2603.23448** Pre, with a SonarSource coauthor. c-CRAB: 184 PRs, 234 tests. Claude Code 32.1%, Devin 24.8%, PR-Agent 23.1%, Codex 20.1%, union 41.5%. Manual check: 84% of comments useful (6 PRs only).
- **2509.01494** Pre. SWR-Bench, 1,000 PRs. Best F1 19.38%, precision 16.65%. Same-model aggregation at n=10 raised recall 118.83%, F1 43.67%.
- **2607.16740** Pre. 362 tasks. Only 1.37% to 5.81% of comments both localised and human-aligned. Cost per task for tracked phases: Rovo Dev $0.75 validation plus $0.44 exploration; Claude Code about $0.10 (phase unclear).
- **2608.09290** Pre, tool authors (Alibaba), benchmark shares authors. 200 PRs. SEM-F1 25.10% against 11.57%; precision 33.9% against 7.23%; recall 20.0% against 28.9%; 385K against 5,664K tokens on Opus 4.6.
- **2501.15134** Pre, ByteDance, tool authors. 12,000+ weekly users, 75.0% precision, 26.7% outdated rate for Go.
- **2609.37216** Pre. CRJudgeBench, 1,199 instances. Best baseline detects 20.77% of invalid comments; the authors' system 37.69%. Every model says "trustworthy" at least 85.52% of the time.
- **2511.18608** Pre. 9,942 HackerOne reports. GPT-5 caught about 28% of invalid reports at 0.82 accuracy. Reviewers more lenient to high-reputation reporters (59.26% against 31.21% on model-rejected reports).
- **2608.02685** KDD'27 listed in PDF metadata. BulkPR-Bench, 581 PRs, 18 repos. Critical-relation recall 35.2% to 57.7%; 8 of 324 runs completed a queue.
- **2601.00753** PR, MSR'26 Mining Challenge. 33,707 PRs. AUC 0.96, 20% budget captures 69% of high-effort PRs. Target is partly a size-like proxy; not checked further.
- **2607.12057** Pre. Same corpus family. Acceptance AUC 0.676, effort R² 0.20 and 0.12. Authors say advisory only.
- **2510.18508** Pre. 384 vulnerabilities, 165,000+ queries, SSVC decisions. All models over-predict risk.
- **Cloudflare Astro triage write-up** Project's own account. Reproduce, diagnose, verify, fix, in isolated subagents; open issues over 200 to about 30; reporter confirms before PR. LLMs force fixes where no bug exists. No costs.

### Bug reports, review load, automation bias

- **Bettenburg et al., FSE 2008** PR. Verified from PDF text. 466 responses (156 developers, 130 consistent; 310 reporters). Developers naming an item among the three most helpful: steps to reproduce 83%, stack traces 57%, test cases 51%. Errors in steps to reproduce were rated a severe problem by 79%; too-long text by 26%.
- **Sadowski et al., CACM 2018** PR. Verified from PDF text. Effective false positive: developers take no positive action. Review checks must be under 10%; Tricorder disables an analyzer if "Not useful" goes above 10%; results must be understandable and actionable.
- **2411.11401** Pre. Tufano et al. Controlled experiment, 29 experts, 50+ hours. Reviewers given an automated review focused on flagged locations and looked less elsewhere. More low-severity issues, no more high-severity ones, no time saved, no confidence gain.
- **2609.22610** Pre. 330,343 multi-file PRs. Each extra file cuts odds of any comment by about 8.7%; latent bug rate rises with file position, 56.7% to 61.5%.
- **2409.07670** IEEE S&P 2025 per a DOI on the page. 51 + 90 survey respondents, 17 interviews on huntr. Worst pain: money-driven hunters and pressure to review. Private disclosure valued.

### Agent-written tests

- **2607.22883** PR, ISSTA 2026 (PACMSE). 318 Defects4J methods, 11 LLMs. With buggy input, misguided tests 3.84% and effective tests 2.98%; with fixed input 0.46% and 8.51%. Generating from a derived docstring with the code removed: effective tests 4.50%, misguided 2.69%. Keeping the code alongside was worse. 15% to 21% of docstrings still inherited the bug.
- **2609.05978** Workshop POVC'26. 15 student repos. Tests run but are shallow; weak assertions dominate. Small sample.

### Cross-checking and cost

- **2604.19049** Pre, single author, retrospective, no recall measured. 171 candidates, about 79% killed. Ten OpenSSL reviewers unanimously backed a nonexistent oracle, killed by one empirical test. A unanimously killed lcms2 finding later became a CVE. Cross-family critic: about 3% of kills, but 3 of 19 same-family-approved fixes in libfuse had errors. About $250 subscription, 4 CVEs, 36+ outcomes.
- **2512.12536** Pre. Consensus reduces false positives on verification, raises false negatives on detection.
- **2604.21282** PR, AAMAS 2026. Synthetic Juliet only, 262 functions. Different-family verifier cut false-positive rate 91.5% to 60.0%. No same-family comparison.
- **2606.19149** Pre, tool authors (Knostic). 8 repos, $1,461.25, OpenSSL $442.66. 376 flagged, 190 after adversarial check, 144 reproduced. Filtering saved an estimated $23,700 full-analysis cost (93.8% by my division; a snippet said over 96%, unresolved).
- **2606.22263** Pre, Berkeley. $300 total, about an hour per project, 19 new memory-safety bugs, sanitizer-confirmed. Scope of the $300 across 7 projects plus 100 Arvo not clear from the abstract.
- **2501.18160** v1 read; venue ICML 2025 per snippet and poster page. 15 projects, $2.54 each, 38 true positives, 65.52% precision. The ICML listing gives 40 and 78.43%, so versions differ.
- **2603.13384** Pre. Self-reported. 3.1 false positives per repo, 2.9 alerts per true positive, precision 0.40 at default.
- **2610.21914** Pre, pre-registered. 465 PRs, 246 repos, 4 reviewers plus 1 fixer agent. Each CodeHealth point associated with 3.5% to 6.1% fewer tokens. Observational, low power; uses a CodeScene tool; author affiliation unknown to me.
- **Anthropic CVD dashboard, 2 Oct 2026** Vendor, and the maker of the model writing this. 6,157 disclosed, 591 projects, 516 patched upstream (8.4%). 29,439 candidates await human triage. 6,123 reviewed by six firms, 92.7% valid including won't-fix. 4,824 disclosed without independent triage.
- **Claude Code Review docs** Vendor. Read-only, no building or running code, instructions from the base branch only, never approves or blocks. The current cost page states no per-review figure; "$15 to $25" is UNVERIFIED and secondary only.

### Hostile repository

- **2608.30686** Pre. 1,920 runs, 20 repos. Attacker controls repo files, goal is exfiltration. Run-Tests 45.5%, Prepare-Env 24.9%, Fix-Feature 14.8%, Fix-Bug 8.6%. Security rules raised alerts without a significant fall in attack success; alerts often arrive after the payload ran.
- **2606.09935** Pre. GitInject: 4 providers, live workflows, 11 attacks, 5 runs each. Config-file injection succeeded on most models, PR-body on almost none. Opus 4.7 and GPT-5.4 0 of 2. A CLAUDE.md scope restriction suppressed a real finding. Attack PR about $1.11. AgentDojo simulation missed 71.2% of real successes. Judgment manipulation has no cheap fix.
- **2607.20759** Pre. 4,176 runs. Attack success 66.5%; Claude Code 41.1%, Cursor 66.5%, Codex Desktop 79.2%. Supply-chain attacks 96.6%. Boundary markers did not reliably help. All resistance came from model refusals or trust classification, none from agent frameworks.
- **2607.14611** Pre. 10 trials per configuration. Auto-loaded file, credential exfiltration: Haiku 80%, Opus 0%, GPT-5.2 30%, GPT-5.5 0%. Threat persists across sessions. Synthetic workspace.
- **2605.07135** Pre. 13,392 workflows; 496 confirmed exploitable of 519; 343 zero-days; 26 maintainer responses to 187 prioritised.
- **2601.17548** Pre, SoK of 78 studies. Adaptive attacks beat defences over 85%; most of 18 defences stop under half. Meta-analytic.
- **2607.05743** Pre, SoK of 39 papers. Denylists 69.0% to 98.6% bypassable. Isolation and access control never compared on shared benchmarks.
- **2606.08433** Pre. Five sandbox products. MicroVM, userspace kernel and containers separate cleanly by class, not by product. Downstream patch lag 0 to 471+ days.
- **2603.02277** Pre. LLMs can exploit seeded container flaws; no numbers in the abstract.
- **Pillar, "Week of Sandbox Escapes" (Jul 2026)** Vendor research, index page read. Seven posts. Sandboxes mostly held; agents wrote files that trusted tools outside then ran: hooks, venv interpreters, Git metadata, Docker socket, `.vscode` tasks. CVE-2026-48124 confirmed via NVD-derived snippets.
- **NVIDIA AI Red Team guidance** Vendor, verified. Mandatory: default-deny egress, no writes outside workspace, no writes to agent config. Recommended: microVM or full VM, secret broker, ephemeral lifecycle.

### Disclosure

- **Anthropic CVD policy (Mar 2026)** Vendor, verified. 90 days or patch; 7 days for active exploitation; 45-day hold on details; 30 days silent then escalate; human-confirmed; AI labelled; no bulk sends without an agreed pace.
- **OpenSSF wg-vulnerability-disclosures #178** Open, draft as of 8 Sep 2026. Thread suggestions, not adopted policy: PoC, exact version, starting privileges, source-to-sink trace, positive and negative controls, repeated runs from clean state.
- **2608.09567** Pre, one author, pre-registered. 104 papers; 20 of 30 patched-counterfactual audits still produced the claimed signal; 7 of 19 negative controls fired; 60% sensitivity, 45% specificity.
- **2608.25667** Pre, survey. Bottleneck shift claim is argument, not measurement.
- **2606.25973** Pre. Design and small pilot only; no results.

Not relied on: Phoenix 2606.20243 (snippets only, 42-issue pilot).

---

## 2. What the evidence says

**The burden is real, but measured effects are smaller than perceived ones.** Practitioners estimate 25% of PRs are slop (LF). The causal study finds PR volume up 6.8% and merge ratio down 1.1% across popular repos through 2025, with the sharpest effect on one-time contributors. These can both be true, since perception tracks attention cost and the causal window ends before 2026. Load concentrates: low-experience vibe coders draw 4.52× the review comments, and review load doubled per reviewer in one firm.

**The shape of the pain differs by channel, so diagnosis comes first.** curl says its PRs are fine because CI catches them, and that the security channel is the crisis. Elsewhere PR queues are the crisis. 2603.26487 explicitly advises diagnosing the bottleneck before acting. We should not assume community PRs are every team's problem.

**Slop has largely given way to accurate volume.** curl moved from 5% valid in 2025 to mostly accurate reports in 2026. Kernel and QEMU made the same shift. Most academic work uses 2025 AIDev data and lags this. Anthropic's dashboard shows the absorption limit: 516 of 6,157 disclosed findings patched, and 29,439 candidates untriaged. Caveat: it is vendor-reported, patching lags reporting, and these are snapshots.

**Rejection labels do not measure quality.** Between 33% and 68% of rejections have no observable reason, depending on the study. Abandonment and duplication outweigh incorrect code (38% and 23% against 3%). This supports the premise that upstream acceptance is not the test. METR adds the converse: test-passing is not mergeable either.

**AI review tools: disagreement that is mostly definitional.** Copilot comments are resolved 72.9% of the time, while CodeRabbit is accepted 36.4% and most agents score below 60% signal. Benchmarks report precision from 7% to 34% and test pass rates near 30%. One manual check found 84% useful. Different definitions of success drive much of this spread, and benchmark ground truth undercounts valid comments. The consistent parts: precision is the limiter, repository context is the missing input, and tool-author numbers run high.

**Can LLMs judge LLM output? Mostly no, and they lean towards accepting.** Judges catch 21% to 38% of invalid review comments and 28% to 44% of invalid bug bounty reports. Reviewers in 2607.04003 distrust them too. This directly limits "three models cross-check each other". Cross-checking removes some error but not correlated error.

**Cross-checking does help, but differently from how it sounds.** Union raises recall (c-CRAB 41.5% against 32.1%). Consensus lowers false positives and raises false negatives. Unanimity failed in both directions in Refute-or-Promote, and one empirical test settled what 80+ agents could not. The evidence for cross-family review over same-family is thin: one single-operator retrospective and one synthetic study with no same-family control. Evidence for execution as the final gate is much stronger.

**Reproducers are necessary but not sufficient.** Developers have wanted steps to reproduce since at least 2008, and every primary maintainer account repeats this. Yet 2608.09567 shows many published PoC oracles fire on patched builds, so a reproducer needs a counterfactual.

**People anchor on what the tool shows.** The one controlled experiment found reviewers look where the LLM points and find no more serious bugs. That experiment has 29 people and used an LLM review, not a three-model pipeline, but it points against a person simply confirming a list.

**Review capacity is poorly evidenced for this task.** I found no study of minutes per AI finding, of fatigue over a queue of LLM findings, or of a safe batch size. The 200 to 400 line and 60-minute rules come from a vendor study of 2006 (UNVERIFIED primary). The best usable numbers are curl's: 1.5 to 12 person-hours per report by my multiplication of its ranges, and "several hours" for five Mythos findings.

**Cost: models are cheap relative to people, with large spread.** Reported whole-repo figures run from $2.54 (RepoAudit, narrow bug classes, 2025 pricing) to $183 average and $443 for OpenSSL (OpenAnt). Filtering dominates savings. Tokens per PR differ 15× between freeform agents and bounded ones. Figures are not comparable across models and task scope.

**Hostile repositories: the attack surface is config and execution, and model choice is not a control.** Attack success varies hugely by model, and small models are worst (Haiku 80% against Opus 0%), which matters because cheap models are tempting for bulk reading. Results disagree across setups (Claude Code 41.1% in issue-delivered tasks, near 0 for PR-body in CI) because payloads and configs differ. The consistent result is that framework-level defences do little and prompt rules alert without preventing. Sandbox failures come mostly through trust handoff, not breakout. Simulation misses most real attacks, so any safety test should run live.

**Disclosure norms are unsettled and moving towards speed.** Kernel treats AI-found bugs as public. QEMU rejects arbitrary embargoes for them. curl now files LOW and MEDIUM publicly. Anthropic keeps a 90-day model; others call embargoes harmful; small projects may disagree (LWN). There is no finished standard; the OpenSSF guide is still a draft. Project policy must therefore be read per repository.

---

## 3. Ranked changes

Cost is rough engineering effort for the fork-and-run version. Ranks reflect impact and evidence together.

### Safety: do these before any external repository

**S1. Two-phase isolation, with execution treated as the danger.** Evidence: 2608.30686 (Run-Tests 45.5%), 2606.08433, NVIDIA, 2603.02277.
- Phase A, read-only analysis: no network except the model broker, no secrets, no running repository code.
- Phase B, tests and reproducers: disposable microVM or full VM per run, default-deny egress, no credentials at all, destroyed afterwards.
- Model keys stay in a broker outside. Pin and track sandbox version, since downstream lag is up to 471+ days.
- Containers are acceptable only for Phase A.
- Cost: 3 to 5 days. A sane default config is the main thing a fork inherits.

**S2. Strip agent-trusted files before agents see the tree.** Evidence: GitInject, Bad Memory, Pillar, Claude Code Review's base-branch rule.
- Remove from the agent's working copy: `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.claude/`, `.mcp.json`, `.vscode/`, `.devcontainer/`, skills and hooks. Keep them available only as quoted data.
- Run agents with a clean HOME and our own config, read from our harness.
- Analyse a `git archive` export rather than a live `.git`. Where Git is needed, disable hooks and `core.fsmonitor`, avoid recursive submodules, and check for embedded bare repos.
- Cost: 1 day. Highest value per hour on this list.

**S3. Agents propose; a deterministic step writes.** Evidence: GitInject, 2605.07135, 2607.05743 (denylists), Pillar.
- No GitHub token, no write access, in any agent process. A non-LLM script assembles the report and pushes to the private repo after human sign-off.
- Use allowlists, never denylists. Never mount the Docker socket.
- Keep Actions disabled on the private PR repo, and never open agent output in an IDE with auto-run tasks on a host with credentials.
- If a fork insists on CI: `persist-credentials: false`, restricted tools, no `pull_request_target`, author filtering. Document this as weaker than the default.
- Cost: 1 to 2 days.

**S4. Assume judgment manipulation survives; make it visible.** Evidence: GitInject (no cheap fix), 2608.30686.
- Keep the system advisory, and record every model's raw output.
- Sample: on a few repos, run one reviewer with and without suspect files or comments, and diff findings. This is my proposal, adapted from GitInject's paired controls, and is untested.
- Red-team the harness with live poisoned fixtures in CI of the harness itself, since simulation missed 71.2% of attacks. Seed from GitInject and pikit-style payloads.
- Cost: 2 days for fixtures, plus a small token overhead.

**S5. Do not rely on cheap models on raw repository text without isolation.** Evidence: Bad Memory, IssueTrojanBench. Also add hard per-repo token, time and dollar caps, as an attack can burn budget (about $1.11 per PR in GitInject). Cost: under 1 day.

**S6. Separate tenants when we run it for teams.** No shared memory, rules or caches across customers, and fresh environments per repository. Evidence: Bad Memory persistence; the isolation literature gives no direct test. Any cross-repo lesson goes through human review. Cost: mostly process.

### Report and process

**R1. Evidence gate: no reproducer, no top-tier finding.** Evidence: Bettenburg (83%), kernel, curl, OpenAnt, Refute-or-Promote, 2608.09567, OpenSSF thread.
- Each top-tier finding must have: pinned commit; a failing reproducer from clean state, run at least twice; and a counterfactual, meaning it passes after the candidate fix or on a negative control.
- Unexecutable findings go to a clearly labelled, capped "unproven" appendix.
- Cost: 2 to 3 days to build; compute is modest. Hardware-dependent quantum code will need simulator-based reproducers, and some findings will never pass this gate. No source addresses that, so test it on mitiq early.

**R2. One-page front, strict cap, and a named hour cost.** Evidence: kernel, curl (long, repetitive reports), 2607.21997, curl's hour figures.
- Page one: bottleneck summary, top findings (cap at 10, default 5), total estimated team hours, and what we did not check.
- Planning figure: 2 person-hours per finding, an inference from curl with no study behind it. Calibrate after real triage sessions.
- Everything else sits in an appendix to pull from, never pushed.
- Cost: under 1 day.

**R3. Finding card with fixed fields.** Evidence: ZeroPath format as praised by Stenberg, kernel doc, OpenSSF thread, Sadowski, 2607.21997.
Fields: three-sentence human-written summary; version and commit; file and line with short quote; reachability rationale, including checks for upstream guards; demonstrated impact only, not speculation; reproducer command; what was run and outcome; severity with a conservative reasoned tier; "intended behaviour?" check citing docs; suggested disposition; optional tested fix labelled by provenance. Plain text first. Cost: under 1 day.

**R4. Measure success per finding by team disposition, not merges.** Evidence: 2605.22534, 2606.13468, 2602.04226, Sadowski. Five outcomes: confirmed and fixed, confirmed and deferred, intended behaviour, invalid, not worth it. Report effective false positive rate by finding class, target under 10% of the top tier, and disable classes above it for that repository. A single form or issue template. Under 1 day. Note 10% is Google's bar for review checks on a mature tool; we may not reach it at first, and should say so.

**R5. Team context pack before analysis.** Evidence: 2607.21997 (intentional design the top theme), Mythos (3 of 5 false positives were documented behaviour), 2607.03316, ZeroPath's stale comments.
Collect docs, threat model, security policy, a few closed-won't-fix items, and known non-goals. Supply it from the team or default branch, never from PR content. The 30-minute intake call may be worth more than any model tuning. That judgement is mine. Cost: 2 hours per repository.

**R6. Change what "cross-check" means.** Evidence: Refute-or-Promote, 2512.12536, c-CRAB, 2609.37216, 2511.18608.
- Union for discovery, independent contexts.
- Adversarial refutation for filtering, with a filter-only reflector seeing minimal context (2608.09290 is the design source, tool-author results).
- Execution decides. Agreement is never reported as evidence of truth, and the report should not say "three models agree".
- Use disagreement to route attention to the human.
- Cost: redesign of 2 days. Cross-family is worth keeping but is not proven; test by ablation on our own data.

**R7. Protocol for the one person.** Evidence: 2411.11401, 2609.22610, 2511.18608, weak evidence on session length.
- Before reading findings, the triager spends a fixed slice of time on hot areas chosen independently, such as git churn and security-sensitive paths.
- Hide which model found each item.
- Shuffle or risk-order rather than present file-alphabetical order.
- Keep sessions to about an hour, as cautious practice and not as a proven limit.
- Seed a few known-invalid findings into the queue to measure vigilance. Untested, but cheap and it gives the missing number.
- Cost: half a day, and it creates data nobody has published.

**R8. Measure recall on every repository.** Evidence: Refute-or-Promote (no recall), Code Review docs' "no findings doesn't mean error-free", SWR-Bench. Replay past fixed bugs by checking out pre-fix commits, or plant known mutations, and report how many were re-found. State the number on page one. Cost: 1 to 2 days; adds tokens per repo.

**R9. Add a queue-hygiene section from deterministic signals.** Evidence: 2601.15195 (abandonment, duplicates), 2606.13468, 2607.04003 (CI gates and cutoffs most endorsed), curl (CI catches weak PRs), 2607.12057, BulkPR-Bench.
List stale PRs, likely duplicates, CI-failing PRs, size outliers, and suggest specific CI gates. This may be the quickest relief, and it is mostly `gh` and scripts. Keep any ML risk score advisory; the 0.96 and 0.676 AUC results disagree. Do not auto-close; BulkPR-Bench shows queue-level judgement is not ready. Cost: 2 days.

**R10. Test generation: spec first, kill test second.** Evidence: 2607.22883, 2609.05978, METR.
Derive a spec, generate tests from it with the code removed, keep a test only if it fails on the buggy state and passes on the fixed state or kills planted mutants. Human-check specs, since 15% to 21% inherit the bug. PRs in the private repo should state that passing tests do not imply mergeability. Cost: 2 days plus about one extra model call per target.

**R11. Budget and report cost honestly.** Evidence: OpenAnt, 2608.09290, 2607.16740, 2610.21914.
- Estimate $100 to $500 of model spend for a mid-size repository with three models, verification and tests. This is an inference from OpenAnt and Refute-or-Promote, not a measurement. Very large C repos may run higher.
- Human triage will likely exceed model cost once the hours are priced.
- Prefilter with deterministic reachability, churn or scope rules. Bound tools and file lists rather than letting agents wander.
- Print tokens, dollars, wall time and person-hours in every report so forks can compare.
- Cost: under 1 day.

### Disclosure

**D1. Separate security track, with a per-repo policy read first.** Evidence: kernel, QEMU, curl, Anthropic. Read `SECURITY.md` before any delivery. Security items go through that channel, not the general report, and only to people the team named. Default to prompt delivery rather than holding findings for a polished report, because rediscovery is routine. Cost: a half-page process.

**D2. Pace, label, keep a human accountable.** Evidence: Anthropic policy, OpenSSF thread, 2409.07670, Stenberg. Agree pace before sending. Label AI involvement, name the human who verified, and give conservative severity, as AI and humans both misjudge it and models over-predict risk (2510.18508). Send reproducers privately. Mention fixes only if tested. Cost: none.

**D3. Publish a timeline default that a fork can change.** 90 days or patch, 7 days for active exploitation, with a note that the team's own policy overrides. Mention downstream notification for widely packaged software, given Copy Fail. Do not imply we can assign CVEs. Cost: a page of text.

**D4. Never accumulate findings across unaffiliated repositories.** If we scan repos that have not opted in, the "private report" premise fails and the Anthropic pacing rule and maintainers' stated preferences apply. Keep scope to opted-in teams, or get agreement first. My judgement from the sources above.

### What I would not do

- Do not build slop or AI detection. Maintainers report LLMs detect LLMs poorly, and accurate reports make this moot.
- Do not make auto-merge or auto-close features.
- Do not use model refusal or security rule text as a safety claim.
- Do not advertise cross-model agreement or a fixed acceptance rate.

---

## 4. Search coverage and gaps

**Searched.**
- About 35 WebSearch queries covering AIDev, maintainer burden, curl, kernel, policy, code review evaluation, ensembles, automation bias, fatigue, bug report quality, cost, injection, sandboxing, CI attacks and disclosure.
- arXiv API title sweeps on review, triage, automation bias, cognitive load, prompt injection, vulnerability reports, token cost and AI slop. A later batch of API sweeps returned empty files after apparent rate limiting and was not repeated: duplicates, over-reliance, security report maintainers, automation bias in review.
- Citation trails from CRJudgeBench and search results.
- Direct reads of daniel.haxx.se, docs.kernel.org, LWN, QEMU, OpenSSF, NVIDIA, Pillar, METR and Anthropic pages.
- I did not browse arXiv daily listings, so October 2026 is thinner than earlier months.

**Thin or empty.**
- No deployment evaluation of AI triage with maintainers as subjects. The closest are the Astro account and surveys.
- No study of minutes per AI finding, batch limits, fatigue on LLM findings, or anchoring beyond 2411.11401.
- No evidence comparing report formats. Recommendations R2 and R3 rest on maintainer statements and old surveys.
- No cross-family against same-family trial on real code.
- Nothing specific to quantum software repositories, scientific code, or hardware-dependent reproducers in this lane.
- No per-repo cost for a three-model pipeline with test generation.
- No comparative study of isolation mechanisms for agents reading hostile repositories.
- Most AI PR data is from 2025 agents.
- Kemerer and Paulk's PSP paper could not be fetched (certificate error). SmartBear/Cisco, Heelan's ksmbd numbers, MetaMateCR, Kononenko, DARPA's $152 per task, the GitHub maintainer survey and Debian's triage experiment were seen only in snippets and are UNVERIFIED, so none is used for a recommendation except as flagged.

**Process notes.**
- The fetcher reported an embedded instruction block at the end of the 2607.14611 page text and treated it as page content. I did not act on it and cannot say whether it is a sample payload. Literature fetching itself is untrusted input.
- One API sweep briefly ran on the system `python3` with `-I`, against the global Python rule. It produced nothing, was stopped and confirmed dead, and the parse then ran through `uv`.
- Scratch files sit in the session scratchpad only.
