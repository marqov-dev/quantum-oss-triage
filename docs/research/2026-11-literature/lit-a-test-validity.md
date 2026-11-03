# Lit search A: validity of LLM-written reproduction tests

Lane for quantum-oss-triage. Search date 2 Nov 2026. Covers arXiv 2023 to Oct 2026, plus older flakiness anchors.

**Headline.** No paper in this search validates an LLM-written reproduction test against intended behaviour without a golden fix. Every headline reproduction rate (SWT-Bench, TDD-Bench, Issue2Test, ReProAgent, DPIAgent, e-Otter++) uses a developer's fix as the hidden referee. We have no such referee, so those rates do not transfer to us. Our "fails at pinned commit, control passes" rule is weaker than the rule those benchmarks use, and that rule is itself shown to be coarse. The cheapest strong fixes are procedural: write the expectation blind, freeze it before first execution, tie it to an external source, and report tiers rather than one word "reproduced".

**How to read the numbers.** Numbers were read from the papers through a fetch tool that summarises the page. I checked these directly in the extracted paper text: 2607.19843, 2607.05139, 2508.06365, 2510.09907, 2608.19626, 2608.01000, 2607.22883, 2511.10865, 2606.16062, 2607.06636, 2604.11950 (design only), 2601.22832, 2209.11515, Molinelli ASE 2025. Treat the others as read but not double-checked. The arXiv API rate-limited my final ID sweep; each ID below was still confirmed by fetching its own abs, html or PDF page, and the title matched. Items only seen in search snippets are in section 1G, marked UNVERIFIED.

"PR" = peer reviewed or accepted at a named venue, as stated on the paper. "Pre" = preprint. "Self" = results reported by the tool's authors, with no independent replication. Nearly everything here is Self; I flag only the exceptions.

---

## 1. Papers read

### A. Reproduction tests: benchmarks and tools

| ID | Venue | Method | Key verified result |
|---|---|---|---|
| 2406.12952 SWT-Bench | PR: NeurIPS 2024 (per its repo; arXiv page gives none) | 1,983 Python instances, 276 in Lite. F→P on golden patch | Any error counts as failure, including ValueError and syntax. Failure type is not classified. Best on Lite then 20.3% (Pass@5); SWE-Agent+ 18.5%; LIBRO 14.1%. Filtering fixes by generated tests raised precision to 47.8% at about 20% recall |
| 2412.02883 TDD-Bench Verified | Pre (IBM) | 449 issues. failToPass × line adequacy | GPT-4o 23.6% F→P. Paper notes coverage does not indicate correctness: 35% of non-F→P tests had perfect coverage. Cause of failure not analysed |
| 2209.11515 LIBRO | PR per its text (ICSE 2023 from memory; confirm) | Codex, 750 Defects4J bugs | 251 reproduced (33.5%). Defines a reproducing test as failing "due to the bug specified in the report". Clusters tests by identical failure output and uses agreement size to decide whether to show results; authors report 71.4% accuracy at judging success and precision up to 0.84 at recall 0.42 |
| 2502.01821 BRT Agent | Pre (Google) | 80 Google bugs, 20 runs each | Plausible BRT rate 28% vs 10% LIBRO. **Best manual check in this lane:** two authors inspected plausible patches; 86% valid, so 14% of F→P patches were not. 25% of bugs had a valid BRT. "Semantically equivalent to the oracle BRT" is the validity test, so it needs a human reference. Gemini judge used; accuracy not reported |
| 2601.19066 Cogeneration | PR: FSE Companion 2026 (Google) | 120 bugs, Gemini 2.5 Pro, 20 runs | P(plausible BRT given it fails on bug and passes on the generated fix) is only 0.44 to 0.53. So a test that flips on the agent's own fix is close to a coin-flip for a test that flips on the true fix. Validity not measured |
| 2503.16320 Issue2Test | Pre (v4 Jan 2026) | SWT-bench-Lite 276 | 32.9% F→P. The LLM itself decides "failure matches issue". Paper shows cases where it was wrong (assertion failed before and after patch). Precision of that judgement not measured |
| 2507.17542 AssertFlip | Pre | Generate passing test, invert assertions. 433 Verified | 43.6% F→P; direct failing-test generation 24.2%. No check that inverted assertions match intended behaviour. Coverage of patched lines 78.4% resolved vs 26.1% unresolved |
| 2508.06365 e-Otter++ | PR: ICSE 2026 (IBM) | TDD-Bench 449. Rule-based selection using 5 model-generated surrogate patches | 63.0% F→P. **Surrogate patches lift random selection 44.7% to 61.8%** (Claude-3.7), 36.0% to 50.6% (GPT-4o). Ranks assertion failures above other failures above errors. LLM critic for "fails for the issue's reason" scores F 0.78 to 0.83 |
| 2605.04320 e-Otter++ Java | Pre (IBM) | 250 Java instances, 150 proprietary | 43.6 to 46.4% F→P; 4% (6/150) on proprietary code with default issue text. A warning about transfer from public benchmarks |
| 2607.09123 ReProAgent | Pre | SWT Lite and Verified | 58.43% and 70.30% F→P at $0.14 per instance. "Triadic review" not specified as LLM or rule. Removing feedback plus review drops Qwen3 from 56.88% to 18.84%. No audit of whether passing tests are meaningful |
| 2607.00990 SWE-Doctor | Pre | SWE-bench Verified and Pro | Keeps a BRT only if it fails by assertion or program exception **after reaching the localised code**; discards setup or dependency failures. Goal is repair, not test validity |
| 2608.23341 DPIAgent | Pre (Microsoft) | SWT Verified 433 | GPT-5 81.76%, with selection 86.17%. Surrogate-patch selection again helps. SWE-Agent: 80.12% coverage but 54.29% TDD score, i.e. coverage comes from tests that do not reproduce |
| 2609.34752 Multi-SWT-Bench | Pre | 1,963 instances, 8 languages | Best 65.29%. Over 80% of instances yield a failing test on buggy code for three methods, but far fewer reach F→P: failure is common and cheap. Named wrong-reason examples: omitted CLI flag, helper imposing unrelated condition, lint revision deleting the behaviour |
| 2607.19843 CoHarden | Pre (Microsoft) | 1,104 F→P pairs, 433 tasks | **About half of F→P tests were Lax** (median split, so "half" is partly by construction) against mutant fixes. Rigorous tests add +8.5 points Resolved, Lax add 0.0. Joint failure of co-generated test and fix was 1.87× independence. Mutants are LLM-written |
| 2610.18004 SWEPatchTest | Pre (Baidu) | 619 tasks, 82,579 candidate patches | Best joint validity 9.21% despite 59.29% reference reproduction. Accepts only 50.20% of correct patches on average. Tests that reproduce are often too narrow or too tied to one fix |
| 2607.28871 Validation Evidence | Pre | 3,730 events, 110 tasks, preregistered effect size | 46.0% of positive agent checks carry no bug-discriminating information. 26.9% of B-fail, S-pass events also fail on gold, so they are tied to the agent's own fix. Reminder alone gave a third of the gain |
| 2604.11950 AnyPoC | Pre | 192 reports; 12 systems. Analyzer, generator, independent checker | Baselines produce a claimed PoC on 85 to 96% of **false** reports. AnyPoC rejects 85 to 96% of them. Valid PoCs 64 to 65% vs 45 to 49%. **Rejected 28 to 33 of 96 true reports**. Most rejection is at analyzer (62.5 false reports on average), checker adds 6.5. Campaign: about 2,700 candidates, 121 bugs, 108 confirmed, 92 fixed. Cost about $2.6 to $5 per report. Labels by authors, no agreement reported; negatives sampled from reports AnyPoC rejected, which likely flatters it (my reading) |

### B. Oracle problem: actual versus intended

| ID | Venue | Method | Key verified result |
|---|---|---|---|
| 2410.21136 Konstantinou et al. | Stated "JACM" in the page; confirm | 24 Java repos, up to 1,000 records per case | Classification accuracy for assertions falls on buggy code, e.g. DeepSeek V3 55.17% to 39.02%. Overall 52 to 69%. Hiding names cost up to 15.4 points, so identifiers are a main signal. Reasoning model same pattern |
| 2607.05139 Coding before testing | Pre | HumanEval+, MBPP, BigCodeBench; 5 models | Fault detection 25% from a fresh session vs 14% after seeing faulty code. CoT did not help; prompt-only beat CoT and CoVe |
| 2607.22883 Misguidance | PR: PACMSE/ISSTA 2026 | 318 methods, 233 defects, 11 LLMs | Effective tests 8.51% from fixed code vs 2.98% from buggy; misguided 3.84% vs 0.46%. Docstring replacing code improves effective tests to 186.77 to 230.23 (from 104.15). False-alarm rate on bug-free code stays about 37 to 39%. Authors argue earlier aggregates overstate the effect |
| 2610.11835 Risks for regression | Pre | 145 PRs from SciPy, **Qiskit**, pandas | 8 to 17% of generated tests are fault-enforcing, 2.4 to 4.8% fault-revealing. Developer suites detect only 14 to 30% of the enforcing ones |
| 2607.10277 Requirements to assertions | PR: ESEM 2026 track; pilot | 10 Defects4J Lang bugs, no code shown | 4 of 5 models closer to requirement than to SUT. Very small; no bug detection or false alarms measured |
| 2608.17214 Oracle anchoring | Pre, single author | 366 mutants, TypeScript. No LLM subject | If expected value derives from the code under test, a fault moves both sides; no input can expose it. Re-anchoring on published procedure raised score 26.09% to 45.65%. A self-referential oracle can score perfectly on oracle-adequacy metrics |
| 2608.19626 Feedback under oracle problem | Pre | Competitive-programming tasks, Qwen models, 2,836 real faults | Model-proposed outputs match a 3-program panel only 27.79 to 50.12%. Single-reference inflates evolution gain by 9.46 to 14.85 points. Panel disagreement is evidence, not proof (94.41% invalid on review). Narrow task class |
| 2608.01000 Judging vs enumerating | Pre | Constructed ground truth | Models judging at F1 0.74 to 0.90 author suites admitting only 19 to 42% of correct solutions; errors are mostly wrong expected values. Dropping any suite that rejects a known-correct probe cuts false rejection from 58 to 92% to ≤5%, but only 5 to 39% of suites survive. Asking for the predicate rather than cases gave F1 about 0.99 |
| 2606.18168 All Smoke, No Alarm | Pre | 86,156 test patches | 80.2% weak or no oracle signal. Regex classifier, 86.7% agreement with labels |
| Molinelli et al. (no arXiv found) | PR: ASE 2025 | 13,866 oracles, 135 Java projects, post-cutoff | Mean mutation score 43% vs 45% human. Extra code context adds little. Measures strength, not correctness |
| 2305.17047 | PR: ISSTA 2023 | TOGA, realistic setting | Fixed-version prefixes inflate bugs found by 61.8%. TOGA precision 0.38%. **NoException baseline finds 61% of TOGA's bugs at twice the precision** |
| 2607.05031 Source-of-authority SLR | Pre (v3) | PRISMA review. v1: 54 studies; v3: 83 | Taxonomy of seven authority sources. Spec-derived 35 of 83, implementation-derived 17 of 83 (v3). Regression-from-prior-version and implicit-intrinsic were never primary LLM sources in v1. Counts differ by version |

### C. Mutation and adequacy

| ID | Venue | Method | Key verified result |
|---|---|---|---|
| 2609.09315 Traditional criteria | Pre | 6,066 non-trivial faults | Tests trigger 32 to 62% of faults, detect 3 to 8%. Mutation only marginally beats branch and statement coverage. Spec-guided oracles help, up to about 30% detection. Main gap is assertions, not exercising code |
| 2607.22880 Replicability | PR: PACMSE/ISSTA 2026. A replication | 318 methods, 8,268 suites | Mutation versus detection r about 0.5 pooled; good for comparing models, **unreliable within a model**. On buggy code, mutation analysis does not apply |
| 2610.13065 TestSuiteBench | Pre (ETH) | 165 apps, requirement-targeted mutants | Best agent 55.5% mutation score, 96.1% validity. Validity rises with an executable but mutation score does not move. So suites are valid but weak |
| 2605.22175 SWE-Mutation | Pre | 2,636 agentic mutants | Detection falls from 71.04% to 39.81% against harder mutants: rule-based mutants flatter tests |
| 2603.00520 SWE-ABS | Pre | 500 + 150 instances, 11,041 patches | Rejects 19.78% of previously passing patches; top agent 78.80% to 62.20%. Manual check found 53 of 500 instances with overfit tests |
| 2503.15223 "Solved issues" | PR: ICSE 2026 | 77 of 260 flagged patches manually read | 28.6% incorrect, 5.2% correct, **66.2% uncertain, mostly under-specified issues** |
| 2610.32548 BlindSpotEval | Pre | 14,320 Java tests | 15.6% of failures are wrong-oracle. Coverage of null, negative, empty inputs 24 to 39% |
| 2501.12862 Meta ACH | PR: FSE Companion 2025 | 10,795 classes, 571 tests | Uses current version as regression oracle; states it "cannot detect existing faults". Equivalence detector precision 0.95 with preprocessing |

### D. Checking a claim, LLM judges, cross-checking

| ID | Venue | Method | Key verified result |
|---|---|---|---|
| 2601.22832 Meta JiT Catching | PR: FSE Companion 2026 | 22,126 tests, 231 weak catches, 41 reports | **Weak catch = fails; strong catch = should fail.** 8 of 41 confirmed strong (19.5%). Assessors cut review load 70%. Reach-out as a one-line sense check ("used to be true, now false; expected?") took minutes. Paper's body also says "7 issues", an inconsistency. Ensemble of LLM judges plus rule patterns |
| 2511.10865 Rubric judge | Pre (Google) | 115 patches, 50 bugs | Humans κ 0.31 with self-authored rubrics, 0.66 with shared ones. 88% of draft rubrics needed revision, 10 of 50 overfit to fix. Judge vs consensus κ 0.57, precision 0.65, recall 0.93. Patches, not tests |
| 2606.16062 Reward hackability | Pre, single author | Docker gate | Judge endorsed 10 of 11 broken tasks without execution. Gate rejected 65 of 105 (61.9%) LLM tests for failing on gold. Re-check n=8 is small |
| 2604.19049 Refute-or-Promote | Pre, single operator | About 171 candidates, about 135 killed | Ten reviewers endorsed a false OpenSSL oracle; one empirical test refuted it. One real CVE was unanimously killed. **PoC self-contamination**: PoC measured its own artefact. Different-family critic killed about 5 survivors. Single rater, no ablation. External acceptance signals are the strongest part |
| 2610.32876 Asymmetric deference | Pre; submitted IEEE | 16,572 audits, 11 configs | True evidence barely helps (+0.02). False assurance cost up to 19 points. Fabricated alarms did not. Verifying each claim in a separate call gained 12 points on one model, not significant on another |
| 2510.09907 Agentic PBT | PR: workshop (DL4C, NeurIPS 2025) | 100 packages, 984 reports, sample of 50 | **56.0% valid (95% CI 42.2 to 69.8); κ = 0.31 between two authors.** Top-rated 21: 86% valid. Main failure is intent ambiguity (agent cannot tell design from bug). $5.56 per report |
| 2610.10258 QuSema | Pre | Qiskit 2.4.1, PennyLane 0.45.0 | Doc-based oracle. A trigger through a documented input = bug; unclear docs = "potential bug". **40 reported, 40 confirmed by maintainers**, 30 silent, 10 crash. But 54 to 72 reports per run before manual screening, so the 100% is after a human filter; no false-positive rate reported. Cost $117 to $1,603 for three runs |
| 2605.07678 Linux false positives | PR: PACMSE/FSE 2026 | 2,006 human reports | 24.78% were false positives, 39.2% from misunderstanding features or limits. Useful human baseline and a source of negatives design |
| 2607.28587 PAIChecker | PR: ASE 2026 | SWE-bench Verified and others | 13.6 to 44.3% misalignment between issue and PR. Benchmarks themselves contain tests asserting things the issue did not state |

### E. Crashes and harness validity

| ID | Venue | Method | Key verified result |
|---|---|---|---|
| 2512.03420 Harness gaps | Pre | 11 projects | 15 true, 43 false crashes. Causes: state-machine, ownership, invalid arguments, i.e. the harness misusing the API |
| 2605.21824 QuartetFuzz | Pre | OSS-Fuzz audit | P1, P2 checks stopped 58 harness-induced crashes. The "94%" headline comes from prior work, not this paper |
| 2607.25647 KQFuzz | PR: ASE 2026 | Qiskit, PennyLane, Cirq, crash oracle | 13 bugs, all confirmed. Oracle relies on heuristics, per its threats section |

### F. Flakiness and quantum

| ID | Venue | Method | Key verified result |
|---|---|---|---|
| 2101.09077 Gruber et al. | Venue not on page | 22,352 PyPI projects, 200 + 200 runs | 0.86% of tests flaky; 59% order-dependent, 28% infrastructure. About 1 rerun confirms a failure was flaky (3 if order-dependent); about 170 to be 95% confident a passing test is not flaky |
| 2601.08998 LLM test flakiness | PR: ICSE SEIP 2026 | 4 DBMS, 30 reruns | Generated tests slightly more flaky than existing. 63% of 115 inspected were unordered-collection assumptions. Flakiness transfers from prompt context |
| 2512.18088 Qiskit flakiness | Accepted JSS (v4) | 10,000 runs × 23 releases | **v4: 62 flaky of 27,026, median failure probability 9×10⁻⁴.** v1 said 290; parallelism was reduced after developer feedback. Cite v4. At p=10⁻³, 1,000 runs detect about 63% |
| 2302.03256 Flakiness in quantum | Pre | 14 repos | 12 of 14 have flaky tests. Causes led by assertions (22.5%) and random seeds (20%). Fixing seeds can hide real bugs |
| 2503.22641 QuCheck | Pre | 5 programs, mutation | False positive rate 0 to 0.04, falling with shots. Three properties reach 0.90 to 0.92 |
| 2609.13839 + 2609.24230 | Pre | 68 and 104 Qiskit transpiler fixes | **About 28% of fixes are invisible to output-equivalence oracles** (layout, phase, determinism). Matched oracles caught 9 of 9 regressions. Same authors for both |
| 2606.27124 Bugs4Q reproducibility | Pre | 37 artefacts | Reproducibility falls from 62.2% to 16.2% across Qiskit versions; pinning alone is not enough |
| 2606.07314 QBugLM | Pre | 5 circuits | Example oracle: TVD ≤ 0.05 at 1,024 shots plus gate-count match |
| 2610.04461 Qomino | Pre | 30 buggy variants, simulated noise | 85.65% accuracy across six programs |

### G. Seen but not verified (search snippet or abstract only)

UNVERIFIED: FlakeFlagger detection at 10, 100, 1,000 reruns (26, 45, 67%, quoted second-hand in 2512.18088 v1). iDFlakies 10,000 reruns missing some tests. Meta blog 29 Oct 2026 claiming 60% TP. STING 2604.01518. EvilGenie 2511.21654. RHB 2605.02964 and SWE-Marathon 2606.07682 (13.8% rollouts). FLIMsiness via 2603.28452. To Kill a Mutant (crash kills, no arXiv ID found). QDiff, QCross, MorphQ. Abstain and Validate 2510.03217. Nexus 2510.26423 (abstract only: execution-validated oracle accuracy 46.30% to 57.73% on LiveCodeBench). TestExplora 2602.10471 read in part: best F2P 16.06%, docs as intent, no false-positive measure. SpecBench 2605.21384 read, tangential.

---

## 2. What the evidence says

**F→P is necessary, not sufficient, and we do not have it.**
- Direct human check at Google: 14% of plausible F→P patches invalid (2502.01821).
- About half of F→P tests are Lax against mutant fixes, and Lax tests add nothing (2607.19843). Treat "half" with care, since the split was at the median.
- F→P tests accept only about half of correct patches on average (2610.18004).
- Our rule lacks the fix half of F→P. A model-written control does not replace it: it tests that the setup works, not that the behaviour differs for the right reason.

**Model-written expected values are the weak link.**
- Seeing faulty code cuts fault detection by roughly 40 to 65% (25 vs 14%; 8.51 vs 2.98%). Effect appears across models, reasoning included.
- Self-referential expectations cannot fail, and adequacy metrics do not notice (2608.17214).
- Generated oracles are often simply wrong: 28 to 50% match in a narrow setting (2608.19626), and suites reject 58 to 92% of correct solutions (2608.01000).

**Disagreement: how bad is the actual-behaviour bias?**
- Konstantinou et al. say LLMs are "prone" to capturing actual behaviour.
- Zhao et al. (peer reviewed) find misguided tests at only 3.84% and argue earlier numbers are overstated, while still finding effective tests drop threefold.
- Charoosaei et al. find 8 to 17% fault-enforcing, on Qiskit among others.
- Ma and Eisty find requirement-prompted oracles closer to spec, but on 10 bugs with no code shown.
- These fit together. The bias is strong when code is visible and much weaker when it is hidden. It shows mostly as lost detection rather than as outright locked-in bugs.

**Disagreement: do specs fix it?**
- For: 2607.06636 (0% vs 33% false alarms, 30 of 30 detection), 2608.17214, 2607.05139, 2609.09315.
- Against: 2607.22883 finds docstrings leave false alarms at about 37 to 39%. 2609.09315 caps at about 30% detection. 2608.01000 shows spec-informed authoring still rejects correct code.
- 2607.06636 is 26 small Python functions with hand-enumerated rules, from a bank's team; its headline does not transfer to a quantum library. Sparse specs are the normal case for us.
- 2608.00884 (older small models) finds @throws text hardly drives exception oracles.
- Net: spec grounding clearly reduces wrong expectations when a real spec exists. It does not make a test correct, and it raises a new failure: false alarms from over-reading docs.

**Mutation is not a validity check for us.**
- Positive results compare test suites written against a known-good reference (SWE-ABS, TestSuiteBench, SWE-Mutation).
- Our code is, by hypothesis, buggy, and 2607.22880 says mutation does not apply there, and is unreliable within a model anyway.
- 2609.09315 finds it barely better than branch coverage on LLM code.
- 2608.17214 shows an anchored oracle scoring perfectly.
- Mutation measures sharpness, not whether the expectation is right. The useful variant mutates a candidate fix (2607.19843), not the codebase.

**Checks by reading are poor; checks by running are good; agreement is weaker than it looks.**
- Judge alone endorsed 10 of 11 broken tasks; execution gate caught 61.9% (2606.16062).
- Ten reviewers agreed on a false finding; one test refuted it (2604.19049).
- Yet the analyzer stage did most false-report rejection in AnyPoC, at a cost of rejecting about 30% of true reports. So pre-test checking has value, but it is lossy.
- Errors correlate: co-generated test and fix fail together 1.87× chance (2607.19843).
- Models accept false assurances and doubt false alarms (2610.32876). Do not pass "verified" labels between our agents.

**The human step is noisier than assumed.**
- Two authors on bug validity: κ 0.31 (2510.09907). Shared rubrics raised κ to 0.66 (2511.10865).
- With a clear definition of correct, 66.2% of manual reads were still uncertain (2503.15223).
- Human bug reports are themselves 25% false (2605.07678). "A person triages everything" is not a ground truth unless the rubric is shared and agreement is measured.

**Crash versus assertion: our rule's asymmetry is questionable.**
- We treat assertion failure as evidence and exceptions as blocked. The literature mostly says the reverse about oracle risk: an uncaught exception needs no model-authored expectation (Meta: the implicit oracle captures failures known to be true; 2305.17047: NoException twice TOGA's precision; e-Otter++ ranks assertion first only as a selection heuristic).
- But crashes carry harness risk: 43 false vs 15 true when the harness misuses the API (2512.03420).
- So they have different failure modes. Assertion failures fail on expectation, crashes fail on input validity. I found no study that directly compares them for LLM reproduction tests. This is the largest gap in the lane.

**Reruns.**
- Failure-side checks are cheap: most flaky tests pass most of the time, so few reruns expose them (Gruber).
- Pass-side checks are expensive: 170 or more, and rare quantum flakes (median p about 10⁻³) need thousands (2512.18088). No paper gives a validated number for LLM reproduction tests.
- Arithmetic (mine): with 0 passes in n runs, 95% upper bound on pass probability is 26% at n=10, 14% at n=20, 9.5% at n=30, 3% at n=100.

**Feedback loops are a hazard.** Execution feedback drives most reported F→P gains (ReProAgent ablation), but refinement raises overfitting (2511.16858: 21.8% to 25.5%, 33.0% to 35.9%) and single-reference scoring inflates gains (2608.19626). AssertFlip's "pass then invert" gets more F→P by starting from what the code does. That is effective on a golden-fix metric and is the exact opposite of what we need. For a tool with no golden referee, iterating until the test fails is a form of p-hacking. That last sentence is my inference; no paper tests it directly.

**Quantum.** Output-equivalence oracles miss about 28% of Qiskit transpiler fixes. Silent bugs are the majority of what QuSema found. Seeds are a known flake source and fixing them can hide bugs. Evidence comes from small author groups; treat as direction, not rates.

---

## 3. Recommended changes, ranked

Costs are my estimates, assuming $2 to $5 per agent run, the range AnyPoC and e-Otter report.

**Proposed rule.** "Behaviour confirmed" replaces today's "reproduced". A finding is "reproduced" only with changes 1, 2 and 4 passing. It stays "unsupported expectation" if 2 fails, and goes to "uncertain" in triage if the source is ambiguous.

1. **Freeze a blind expectation before first execution.** A fresh session writes the expected behaviour from docs, API signature and the claim, with no implementation in view. Hash it. Later repair may change setup, imports and fixtures, never expected values. Any edit to an expected value restarts the finding and is logged.
   Evidence: 2607.05139, 2607.22883, 2410.21136; 2608.19626 and 2511.16858 on loops; AnyPoC checker states its signal first.
   Cost: config change, near zero run cost. Risk: more false alarms from docs-only writing, which 2 and 7 catch. Highest return.

2. **Require an external authority for every expected value.** Each assertion cites one source class from the 2607.05031 taxonomy: docs, paper or formula, reference implementation, prior version, or implicit. A script checks the quote exists verbatim at the pinned commit. No source: "unsupported expectation", never "reproduced". Also adopt QuSema's test: did the trigger use input the docs permit? Unclear means "potential bug".
   Evidence: 2510.09907 (intent ambiguity), 2608.17214, 2607.06636, 2610.10258.
   Cost: 1 to 2 days for script and schema. Limit: docs are evidence, not truth, and a quote can be misread.

3. **Report tiers, and an "uncertain" outcome.** Use Meta's terms: weak (fails) vs strong (should fail). Suggested ladder: behaviour confirmed; expectation sourced; fix-discriminated; human accepted; maintainer confirmed. Publish the ladder rung, never "bug found", below human accepted.
   Evidence: 2601.22832, 2503.15223 (66.2% uncertain), 2607.28871.
   Cost: under a day. It directly addresses the known weakness in how results read.

4. **Require a flip on an independent surrogate fix.** A different model and session, not shown the test or expectation, writes a minimal fix from the claim. The test must pass, the control must pass, and the existing suite must stay green. Ideally 3 fixes, as e-Otter++ uses 5 and DPIAgent 3.
   Evidence: 2508.06365 (the strongest non-golden signal in the lane), 2608.23341. Warnings: 2601.19066 (0.44 to 0.53 conditional) and 2607.19843 (1.87× correlation), hence hiding the test.
   Cost: 1 to 3 agent runs per finding. It shows behaviour is local and changeable, not that it is wrong. If the surrogate fix does not flip the test, record "no flip"; that may mean the fix was wrong, not the test.

5. **Measure the harness on a calibration set.** About 50 items: 25 real fixed bugs from the target repos, 25 reports closed as not-a-bug, wontfix or user error, each at its pinned commit. Run blind. Report false-discovery rate with a Wilson interval, per rung. Sample what the harness rejects, too.
   Evidence: AnyPoC's four-cell design and its own bias lesson (draw negatives independently of the tool); 2510.09907's interval of 30 to 58% FDR; 2605.07678. 2606.27124 warns old quantum artefacts rot, so use recent commits.
   Cost: 3 to 5 person-days plus about $300 to $800, rerun on method changes. Without this, accuracy claims have no denominator.

6. **Give triage a shared rubric, and measure agreement.** Fixed questions; two raters on a random 20%; report κ. Lead with a one-line check: "this input returns X, doc Y says Z; expected?". Keep the test code second. Don't let an LLM draft per-finding rubrics unreviewed.
   Evidence: 2511.10865, 2510.09907, 2601.22832. Cost: half a day, plus second-rater time.

7. **Add a deterministic failure-site gate.** Rerun in a clean container and require: failure at the named assertion, stack or coverage shows the target code was reached, no setup or import error. Add an anchoring lint: flag any expected value computed by calling the code under test, and any measurement of the test's own artefact.
   Evidence: 2607.00990, 2604.11950, 2604.19049, 2608.17214, 2606.16062. Cost: 1 to 2 days. Run only this gate before spending on 4.

8. **Make the cross-check a separate adversarial refutation, grounded in code and execution.** One claim per call. Reviewer's task is to refute, including searching docs, changelog and closed issues for intended behaviour. A refutation must cite code or a run. Strip confidence labels and earlier "verified" tags. Use a different model family for the last check. Sample killed claims for a person.
   Evidence: 2604.11950, 2604.19049, 2610.32876, 2605.07678. Cost: modest, and it reduces downstream runs. Accept that about a third of true claims may die (AnyPoC).

9. **Rerun protocol.** Per failing test: 20 runs in fixed order, then 10 in random order, in the sealed container. Any pass means flaky. Control: same count, and state in the report that this bounds nothing below about 10%. For stochastic targets: at least 30 seeds, report failure rate with a Wilson interval, and require the assertion margin to exceed sampling noise. Also keep one seed-pinned run for replay.
   Evidence: 2101.09077, 2601.08998, 2512.18088, 2302.03256, 2503.22641. Counts are my judgement, not validated. Cost: compute only, unless the suite is slow.

10. **Split exceptions out of "blocked".** Uncaught exception inside target code, on documented valid input, with no test-side cause: new class "crash candidate", gated by the input-validity check in 2. Keep setup, import and environment errors as blocked. Note: "blocked" currently hides the lowest-oracle-risk evidence you have.
    Evidence: 2305.17047, 2601.22832, 2512.03420, 2610.10258 (10 of 40 were crashes). Cost: under a day. No direct study; pilot on calibration set.

11. **Triangulate on history.** Run the frozen test on earlier releases and upstream HEAD. Passing earlier means a behaviour change, an external fact not authored by a model. Passing at HEAD means it may be fixed already. Failing everywhere gives no information.
    Evidence: authority class in 2607.05031; Meta's fail-on-child, pass-on-parent definition. Note Meta's weak catches were still only 19.5% strong, so this is a signal, not proof. Limit: 2606.27124, old versions rot. Cost: hours to script.

12. **Add quantum-specific oracles once the generic rule works.** Second simulator or library as reference implementation where available; metamorphic relations; contract checks for layout, global phase and determinism on transpiler code. Evidence: 2609.13839, 2609.24230, QuSema. Cost: per-repo, days. Note QuSema argues some functions have no differential counterpart.

13. **Optional: grade sharpness by mutating the surrogate fix.** Ask whether the test rejects wrong-but-plausible fixes. Use after 4, only as a ranking signal. Evidence: 2607.19843. Cost: 3 to 5 extra runs per finding. Skip until 4 and 5 run.

**Do not adopt:**
- Mutation score as a test adequacy gate.
- An LLM judge reading tests without running them.
- Agreement between models as evidence that a finding is true.
- Iterating until the test fails.
- AssertFlip-style inversion, which starts from actual behaviour.
- Benchmark F→P percentages as estimates of our accuracy.

---

## 4. Search coverage and thin spots

**Searched.**
- WebSearch, about 25 query variants across all listed topics.
- arXiv API sorted by date, about 12 queries across test oracle, oracle problem, fail-to-pass, bug reproduction, false alarm, mutation plus generated tests, flaky, PoC, intended behaviour, quantum oracle and quantum flaky, viewing about 250 titles. A final group of 6 queries returned nothing because of rate limiting: "wrong reason", "not a bug", "fault-enforcing", "reproduction script" hallucination, title-only oracle queries, claim verification. Treat those phrases as unsearched on the API; some were covered by WebSearch.
- Citation trails: partial, through related-work sections and listings, not a systematic forward-citation search (no Semantic Scholar or Google Scholar).
- The listing page route (arxiv.org/list) was not used; API listing stood in for it.

**Thin.**
- Crash vs assertion validity for LLM reproduction tests: no direct study.
- Validating reproduction without a golden fix: nothing direct; only surrogate-patch selection.
- LLM reproduction tests in quantum software: QuSema and KQFuzz only, both bug-finding.
- Rerun counts for LLM tests specifically: one empirical (30), no derivation.
- Metamorphic relations by LLMs with false-positive rates: searched once, nothing usable.
- Sycophancy to bug claims: only code-smell analogue 2607.10411, unread.
- Maintainer rejection studies of AI reports: nothing rigorous; curl and HackerOne appear only as anecdotes in 2604.19049.
- Independent replication is rare. Only 2607.22880 is a replication. Most 2026 items are unreviewed preprints, and many show model-name and date claims I could not check beyond the paper itself. Several sit in the same few groups (Papadakis/Konstantinou; IBM Ahmed/Hirzel; Google Cheng/Tufano; Microsoft Liu/Luo), so "many papers agree" overstates independence.
- Venue fields for SWT-Bench, LIBRO, Gruber and 2410.21136 need confirming before citation.
