# Lane C: bugs and testing in quantum software

Literature search for quantum-oss-triage. Date: 2 November 2026. Scope: 2019 to November 2026.

**Read this first.**

- The single strongest finding for our harness: a test written by a model cannot be trusted until it has been shown to fail on the bug and pass without it. 2607.09007 found 54 of 402 case-version pairs where both buggy and fixed code passed the oracle, and it had to correct 15 inverted assertions in published benchmark tests. 2610.11835 found 8.4% of LLM-generated Qiskit tests enforce a fault, against 2.4% that reveal one.
- The second: output equivalence is the wrong oracle for a large share of the boundary bugs we care about. 2609.13839 finds 28% of merged Qiskit transpiler fixes repair faults that output equivalence cannot see, and that class clusters at representation boundaries.
- Most of the best evidence is less than three months old and unreviewed. Every "confirmed by developers" count is self-reported by tool authors. No paper in this lane measures a multi-model review harness like ours.

**Corrections to the brief.**

- 2607.09007 is not primarily a revalidation of Bugs4Q. It is a 4-page LLM repair benchmark that revalidates Bugs4Q on the way. The dedicated revalidation is 2606.27124 (Ohto et al., accepted at ICSME 2026 RENE). Both are useful, and they are listed separately below.
- MorphQ++ is not an extension by Paltenghi and Pradel. Search results attribute it to Kitt and Cohen (ASE 2024 RENE). I could not open the paper, so this is UNVERIFIED.

**How to read the status labels.**

- `peer` means the arXiv comment or journal-ref states acceptance at a named venue. I did not check the proceedings themselves.
- `preprint` means no venue is stated.
- `FULL` means I read the extracted full text for the claims given, in targeted sections.
- `ABS` means abstract only.
- `self` means bug or effectiveness numbers come from the tool's own authors.

All arXiv IDs below were checked against the arXiv abstract page or API title, except where marked.

---

## 1. Papers read

### 1a. Empirical bug studies and taxonomies

| ID | Venue | Method | Verified result | Read |
|---|---|---|---|---|
| 2108.09744 Bugs4Q | ASE 2021 NIER (short version) | Manual benchmark | 36 real Qiskit bugs in the abstract | ABS |
| 2110.14560 Paltenghi and Pradel | OOPSLA 2022, peer | Manual, 223 bugs, 18 platforms | 39.9% quantum-specific. 92 crashes; incorrect outputs 34.5%, more than deep learning compilers (26.26%) | FULL |
| 2201.08662 Luo et al. | preprint | Manual, 96 bugs, 4 languages | Over 80% quantum-specific (their definition) | ABS |
| 2204.11965 Bug characteristics | preprint | Bug reports of 125 projects | Quantum-specific bugs concentrate in compiler, gate operation, state preparation | ABS |
| 2306.06369 QML frameworks | QSW 2023, peer | Manual, 391 bugs, 22 repos, 9 frameworks | 28% quantum-specific | ABS |
| 2509.03280 Quetschlich et al. | To appear, Computing special issue | Experience report, 14 bugs | Most arose from several interacting causes. No clear link between debugging strategy and bug class. Names QORDER as a recurring class; qubit order and global phase called common sources of error | FULL (targeted) |
| 2512.24656 Yousuf and Sofi | preprint | 32,296 issues, 123 repos, rule classifier (accuracy 0.81 to 0.85) | 73% classical, 23% quantum. Testing "associated with" about 60% fewer bugs on 60 Python repos. Observational, with detection bias stated. I did not see the regression table, so the 60% stays at abstract level | FULL (partial) |
| 2603.22789 Upadhyay et al. | preprint (PACMSE template, placeholder DOI) | Manual, 394 bugs, 12 simulators | User reports found 78.4%; testing 10.7%; comparison testing 1.0% (4 issues, 3 of them wrong outputs). Incorrect results are the top manifestation at 111 issues. Text also says 104 plus 15, which does not sum to 111 | FULL (targeted) |
| 2608.03173 Yousuf et al. | ICCMC 2026 | Rule classifier, 12,910 Qiskit and 4,613 other issues | Classical 67%, quantum-specific 27 to 30% | ABS |
| 2606.27124 Ohto et al. | ICSME 2026 RENE, peer | 37 Bugs4Q artifacts, 21 Qiskit snapshots, 77,700 runs, 30 per configuration | Existence 16.2% on 2.x even with pinned stack. 82.0% of failures are source incompatibility; only 5.1% are probabilistic. Dependency updates alone fix 4.6%. Bugs4Q-Robust reaches 78.4%. Abstract cites 62.2% at v0.20.1, body gives 75.7%, not reconciled | FULL |
| 2610.22089 Saad et al. | preprint | 1,019 issues reduced to 410 verified bugs, 10 repos, Jul 2024 to Jul 2026; agent-assisted curation plus two authors | 354 of 410 (86.3%) are in families absent from all mutation tools and curated benchmarks. Compiler transformation 66, type handling 53, missing validation 47. Format conversion 20, serialization 18. Mitiq only 4 bugs | FULL (partial) |
| 2609.13839 Nasir et al. | preprint | Mined 68 Qiskit transpiler fixes, dual-coded (kappa 0.62 to 0.96), extended 104 | 19 of 68 (28%, CI 19 to 40) invisible to output equivalence. 29 of 104 on the extended corpus. tket 7 of 21. Cross-representation or conversion loss is 10 of 68 fixes, and 6 of 10 contract/metadata fixes are representation-boundary crossings | FULL (targeted) |
| 2512.18088 Kim et al. | JSS, accepted, peer | 10,000 runs across 23 Qiskit Terra releases | 62 flaky of 27,026 tests. Median failure probability 9e-4. 83.87% recur across releases. Suspected causes: floating point 48.4%, randomness 6.5% | FULL (targeted) |
| 2302.03256 flakiness | preprint | 14 repos | Flaky tests in 12 of 14 repos | ABS |
| 2506.17306 Zappin et al. | preprint | Survey of 26 developers plus interviews | 31% use quantum-specific test tools. Cited bug sources: library updates 81%, compatibility 62% | ABS |
| 2501.06443 Ramalho et al. | SANER 2025 ERA, peer | Test pattern analysis, Qiskit Algorithms | Seven patterns including fixed seeds and approximate assertions; research tools not adopted | ABS |

### 1b. Testing and fuzzing of SDKs

| ID | Venue | Method and oracle | Verified result | Read |
|---|---|---|---|---|
| QDiff, Wang et al. (no arXiv; author PDF) | ASE 2021, peer | Differential, K-S test with threshold and confidence | 14,799 circuits; 4 crash bugs and 2 root causes for divergence on IBM hardware; filtering cuts time 66%; self | FULL (targeted) |
| 2206.01111 MorphQ | ICSE 2023, peer | Metamorphic, K-S at p under 5% | 8,360 program pairs; 13 bugs, 9 confirmed; all described as crashing; self | FULL (targeted) |
| MorphQ++ | ASE 2024 RENE | Reproduction of MorphQ | UNVERIFIED, paper not reachable | none |
| 2308.04748 Fuzz4All | ICSE 2024, peer | LLM fuzzer, nine systems including Qiskit | 98 bugs total, 64 confirmed new; self | ABS |
| 2503.17322 QITE | preprint | Import, transform, export through QASM on Qiskit, PennyLane, pytket, BQSKit. Crash plus QCEC oracle | 17 bugs, 14 confirmed or fixed; self. Found 3 bugs in QCEC itself. Examples: `cu` unitary mismatch in PennyLane, `u0` conversion in pytket | FULL (targeted) |
| 2602.00024 QSPE | preprint | Differential across optimisation levels, statevector dot product | 708 "miscompilations", 81 Qiskit and 627 pytket. **All 81 Qiskit cases trace to one missing statevector method, and only representative cases were filed.** Measurement oracle gave over 20,000 reports; 100 sampled were all false | FULL (targeted) |
| 2602.09942 QEMI | preprint | Equivalence modulo inputs | 11 crash bugs, 1 behavioural inconsistency; self | ABS |
| 2607.25647 KQFuzz | ASE 2026, peer | LLM seeds, mutation, **crash oracle only** | 13 bugs, all confirmed, 12 fixed; coverage 63.31% on Qiskit, 58.71% PennyLane, 73.79% Cirq; self | FULL (targeted) |
| 2610.11195 RetroQ | preprint | Adjoint identity, then controlled adjoint with ancilla | 6 bugs identified or replicated on 5 passes. Only 1 of 4 new ones stated as confirmed. Global phase in controlled context was sent as a feature request. No false positive rate reported | FULL via WebFetch |
| 2609.33255 N×M (Quanifi) | preprint | N implementations on M engines | 3 defects; 2 returned wrong answers with no error (negated Rx consistent on Tuna-17; Open Quantum QASM parsing). One provider confirmed and fixed. Hardware runs, small | FULL (targeted) |
| 2610.06142 Ye et al. | preprint | Controlled experiments on Qiskit, TKET, Cirq | After an OpenQASM 3 round trip, requested synthesis had no effect in all 360 delivered conditions, with compilation succeeding. OpenQASM 2 interchange raised two-qubit count 37.2% on an 8-qubit Grover | ABS |
| 2609.24230 Nasir et al. | preprint | Layout contract checker, MR-1, phase tracker, determinism runner | Fires on 9 of 9 real regressions; 675-configuration sweep had no false positive; 1.00 on 36 mutants per channel; contract check is 2 to 6 orders cheaper. Same authors as the corpus, so self | FULL (partial) |
| 2609.35834 Nasir et al. | preprint | Pre-registered regression test selection | Composite selector lost to diversity-only baseline, 0.721 vs 0.874 AUC. A published negative result | ABS |
| 2610.00255 Nasir et al. | preprint | Integrative survey | Published bug counts, mutation results and benchmarks "do not establish a common effectiveness ranking". Oracle timeout must be inconclusive, not pass | FULL (targeted) |
| 2609.07035 Shen and Zhong | Manuscript submitted to ACM TQC, not accepted | Conformance on 9 configurations, 5 decoder libraries | Docs answer 4 of 54 capability questions. Bounded-distance correctness declared by nobody. A 26% heavier correction under renumbering. A weight summation catches every injected corruption that logical error rate misses | FULL (partial) |
| 2610.31443 ConQEC | ICSE 2027, peer | Concolic testing of QEC code | Detects seeded bugs in every case; self, seeded only | ABS |
| OOPSLA 2025, Klimis et al., DOI 10.1145/3763100 | peer | Alloy model of QASM 3.0; cross-simulator unitary check modulo global phase | Over 800,000 circuits; 8 simulator bugs, 6 new; self. Conference abstract only, paper was blocked | ABS |

### 1c. Test oracles and shot budgets

| ID | Venue | Method | Verified result | Read |
|---|---|---|---|---|
| 1905.09721 Huang and Martonosi | ISCA 2019, peer | Statistical assertions in simulator | Chi-square style assertions for classical, superposition, entangled states | ABS |
| 1811.05447 QDB | Dagstuhl proceedings per arXiv journal-ref | Bug taxonomy and assertions | Title verified only | ABS |
| 2507.17235 Miranskyy et al. | preprint | 1,796,880 original-mutant pairs, 9 test types | In their 400-pair motivating example at 10^5 shots, chi-square had FP 73 and FN 121. Statevector was perfect. At 10^7 shots and p under 0.05, chi-square still had 80 FP. The multinomial test had 200 of 200 FP | FULL (targeted) |
| 2510.22418 Miranskyy | preprint | Analytic, Chernoff bound | At F=0.999, error 0.01: inverse test 4,603 shots, swap about twice that, chi-square 1.12e4 to 7.18e8 | FULL (targeted) |
| 2509.16595 Ye et al. | ASE 2025 NIER, peer | Review of validation methods | Measurement suits existence checks; statevector suits behaviour checks | ABS |
| 2503.22641 QuCheck | preprint | Property-based, Qiskit, 5 programs | Mutation score 0.90 to 0.92 with three properties, FPR 0 to 0.04; 36.0% more faults than QSharpCheck; self. Adds statistical correction that QSharpCheck lacked | ABS, targeted |
| 2606.28742 MetaMorphQ | QSW 2026, peer | Five physics invariants for VQE; 500 circuits, 2,469 mutants | Zero false positives; Youden's J 0.57 vs 0.02; scope limited to diagonal Hamiltonians; self | ABS |
| 2605.15601 Zhang | preprint | Bayesian sequential verification on Bell and QAOA | Reduces shots when true success exceeds threshold; no hardware | ABS |
| 2610.04461 Qomino | preprint | Dominance oracle under noise | 85.65% accuracy over 6 programs, 30 buggy variants; self | ABS |
| 2605.19736 QUTest | preprint | Test framework, 12 assertion types | Evaluation only planned | ABS |
| 2601.08367 Li et al. | TOSEM 2026, peer | 59 primary studies | 93.0% used shot-based backends; only 4 used statevector simulators; only 9 used statistical tests to compare approaches | FULL (targeted) |
| 2610.25233 Yousuf et al. | preprint | 61 papers | 77.0% noise-oblivious; inferential tests in 16.4%; metamorphic and differential testing have no noise-aware work | ABS |
| 2606.26604 Campos and Miranskyy | preprint | Transpile and compare QASM | 348,299 survivors, 92,011 equivalent; found 32.1% with 100% precision | ABS |

### 1d. LLMs finding, testing or repairing quantum code

| ID | Venue | Method | Verified result | Read |
|---|---|---|---|---|
| 2401.14913 Guo et al. | Q-SE 2024, peer | ChatGPT on Bugs4Q | 29 of 38 repaired. Not comparable to later work, see section 2 | ABS |
| 2607.09007 Brahmbhatt et al. | preprint, 4 pages | 67 defects, 6 Qiskit versions, 4 models, 10 candidates | Only 4 of 67 valid on all six. 57 of 402 pairs: buggy passes, including 54 where both pass. 105 pairs: fix runs but fails its own test. 15 tests had inverted assertions. 384 of 599 passes (64.1%) on invalid pairs. Valid cases at 2.3.1: 7 of 67. Internal inconsistency: text says GPT-5o-mini 86.1% incompatible, table says 55.7% | FULL |
| 2610.11835 Charoosaei et al. | preprint | 145 PRs in SciPy, Qiskit, pandas; injected faults | Qiskit: 8.4% fault-enforcing [5.6, 11.6], 2.4% fault-revealing [1.7, 3.3], 69.5% weak, 19.7% invalid; 3,355 pairs. 82.8% of Qiskit fault-enforcing pairs persist to end of history. Developer tests caught 13.8% of pool members on Qiskit. Only Qiskit's PR-level result applies here; faults are injected | FULL (targeted) |
| 2610.13811 QTestBench | QAI 2026, peer | 5 models, 18 tasks, scored against official checkers | Executability about 1.0, yet best Qiskit Config C test quality is 0.34. GHZ task TQS 0.13 despite 0.78 input coverage. Text and table disagree on Qiskit bug detection scores | FULL via WebFetch |
| 2610.28678 Seefried et al. | preprint | 15 models, 530 tasks, evaluator audit | Removing checks for unspecified quantities moved GPT-6 Astra from 0% to 94.1%, unchanged outputs. Found unexecuted tests, leakage of canonical functions, reference import failures. 17 QuanBench tasks defective | FULL (targeted) |
| 2610.10258 QuSema Song et al. | preprint, 7 Oct 2026 | Agent on source and docs; 20 historical silent bugs; 3 runs | Mean relocated: QuSema+Opus 5 16.00 ($1,603), QuSema+DeepSeek 15.67 ($162), Claude Code+Fable 5 14.67 ($425), Codex 13.33 ($117). On Qiskit 2.4.1 and PennyLane 0.45.0: 40 new bugs confirmed, 30 silent, 5 silent ones out of reach for differential and metamorphic testing per the authors. Self. No count of rejected reports given | FULL (targeted) |
| 2606.07314 QBugLM | QSW 2026, peer | Injected bugs in OpenQASM 3, 2 models, TV distance check | One retry takes Pass@1 from under 25% to over 80%. Injected, not real | FULL (targeted) |
| 2601.12273 Yoshida et al. | SANER 2026 ERA, peer | 18 buggy programs, GPT-5, mutation context | 94.4% success, n=18 | ABS, targeted |
| 2605.03943 Cassieri et al. | preprint | 55 Qiskit programs, manual | LLM F1 0.70 and 0.68 vs LintQ 0.41; self | ABS |
| 2607.04072 Rasyidi et al. | preprint | 17 models, 50 tasks, 3 Qiskit versions | Diagonal Pass@1 from 0.02 to 0.85; doc-guided repair 0.19 to 0.59 | ABS |
| 2610.34841 Li et al. | preprint | Qiskit to PennyLane and Q#, 43 tasks, 4 configurations | Zero-shot Pass@1 up to 72.33%. Built on QuanBench, which 2610.28678 flags | FULL (targeted) |
| 2512.08245 Cardinal et al. | preprint | QAOA migration report | Same circuits gave different results; root cause was a changed sampling default, 10,000 shots captured only 23% of the state space; 250,000 restored it | ABS, targeted |
| 2603.09029 Sivaloganathan et al. | preprint | LLMs classify flaky reports | F1 0.9420 detection, 0.9643 root cause, vs 0.8871 and 0.5839 in its earlier 2410.23578 version | ABS |
| 2310.00718 LintQ | FSE 2024, peer | Static analyses on 7,568 programs | 91.0% precision with six best analyses; 92.1% missed by prior work; self | ABS |
| 2609.30313 HyQDB | Not checked | Tiered agent adds deterministic evidence to LLM repair; own benchmark | Repair success on held-out human programs from 45% to 75%; self | ABS |

### 1e. Seen late, abstract only, no numbers used

2610.29053 (symmetry oracles for variational algorithms, a candidate Tier F check), 2610.22275 SynDebug (assertions inside fault-tolerant programs), 2608.24320 QisMC (model checker for Qiskit), 2609.38883 QSA (quantum-aware harness, but for evolving software, not reviewing it), 2605.07525 Q-SAGE (checks LLM solvers against classical results), 2103.16968 QBugs (benchmark position paper), 2001.10870 (early debugging tactics), 2106.01099 (equivalence checking for non-unitary circuits, relevant if dynamic circuits enter scope), 2009.02376 (equivalence checking of the Qiskit flow).

---

## 2. What the evidence says

**Silent wrong results are common, and standard testing rarely finds them.** Incorrect results are the most common simulator failure manifestation (2603.22789). They are 34.5% of platform bugs (2110.14560). In simulators, users found 78.4% of bugs and comparison testing only 1.0%, yet 3 of those 4 comparison finds were wrong outputs. That reads as under-use, not low value. It is a small count.

**Crash oracles dominate fuzzing, so fuzzing counts say little about our target.** MorphQ's bugs were crashes. KQFuzz uses a crash oracle only. QEMI found 11 crashes and 1 inconsistency. QITE's equivalence oracle is the main exception among fuzzers. QuSema's authors argue that crash and comparison oracles cannot reach many silent bugs. This is a claim from authors with a tool to promote, though it rests on 5 specific bugs listed in the paper.

**Conversion boundaries are a recognised class, and the evidence is now direct.**
- Cross-representation or conversion loss is 10 of 68 transpiler fixes (2609.13839).
- Format conversion 20 and serialization 18 of 410 in-the-wild bugs (2610.22089), and neither family is covered by any mutation tool.
- QITE's ITE loop found conversion bugs across four platforms.
- 2610.06142 shows functional equivalence can pass while OpenQASM routes drop the high-level operations a later step depends on.

I found no study focused on silent results from qubit order or gate phase across frameworks. QORDER appears only as a category in 2509.03280 and 2110.14560. **That gap is real, and our findings could fill it.**

**Disagreements.**

1. *Share of quantum-specific bugs:* over 80% (2201.08662), 39.9% (2110.14560), 28% (2306.06369), 23% (2512.24656), 27 to 30% (2608.03173). Definitions and classifiers differ. Rule-based classifiers on all issues run low, and manual studies of fixes run high. I would not cite any single number.
2. *Measurement or statevector oracles:* QSPE reports all 100 sampled measurement alarms false. Yet its statevector oracle produced 81 "bugs" with one root cause, and its false alarms rest on its own K-S setup. 2507.17235 shows chi-square is unreliable even at 10^7 shots in a hard small-difference case, but that table is a motivating example, not the main experiment. The statevector oracle also cannot test a simulator with itself, and 2603.22789 shows simulators fail silently. Neither oracle alone is enough.
3. *Global phase:* most tools compare modulo global phase. RetroQ shows a dropped phase becomes a real error once controlled. PennyLane treated that as a feature request. 2609.13839 counts phase bookkeeping as a fault class of its own (5 of 68). Whether a phase finding is a bug depends on the stated contract, so triage needs a rule for this.
4. *LLM repair rates:* 29 of 38 (2401.14913), 94.4% of 18 (2601.12273), 48.8% pass@10 (2607.09007). These cannot be compared. The last paper shows most passes in unvalidated runs sit on invalid benchmark entries.
5. *Does the benchmark measure the model?* 2607.09007 concludes version effects "live primarily in the benchmark", but the valid denominators are 7 to 12 with wide intervals (47 to 91%). The direction is believable. The size is not settled.
6. *Does testing reduce bugs?* The 60% figure in 2512.24656 is associational, and tested projects also report more. 2603.22789 shows tests catch few bugs in simulators. Do not cite it as causal.
7. *What flaky means:* quantum papers stress shot noise, but in Qiskit Terra suspected floating-point tolerance is 48.4% against randomness 6.5% (2512.18088), and in Bugs4Q probabilistic variation is 5.1% of failures (2606.27124). Tolerance and API drift matter more than sampling.

**Weak spots in the evidence itself.**
- "Confirmed" often means acknowledged. QSPE's 708 is a count of witnesses, not root causes.
- QuSema gives no rejected count, and its RQ1 gaps (16.00 vs 14.67, three runs, 20 bugs) are small enough that a plain coding agent is not clearly beaten.
- Four of the most useful papers come from one author group (Nasir et al.) and have not been reviewed. The tool paper validates on that same group's corpus.
- Several papers contain figures that disagree with themselves, noted in section 1.

---

## 3. Recommended changes, ranked

Costs assume one engineer. Items 1 to 4 are the ones I would do before expanding beyond mitiq.

**1. Add a two-sided validity gate on every reproduction test. Cost: 2 to 3 days.**
A test counts only if it fails on the affected code and passes on a control: the upstream fix, a minimal local patch, or an independent reference. Record the verdict per (claim, version). Reject any test whose assertion mirrors current behaviour without an independent source.
*Evidence:* 2607.09007 (54 non-discriminating pairs, 105 fixes failing own test, 15 inverted assertions), 2610.11835 (fault-enforcing outnumber fault-revealing 3.5 to 1 on Qiskit, and they persist), 2610.13811 (runs almost always, discriminates poorly). This is the highest-value change because it addresses our exact failure mode, a model writing the test for its own claim.
*Caveat:* with no upstream fix, the local patch is itself a model output. The person triaging should read it, and the oracle should come from a different model than the claim, as 2607.09007 did.

**2. Ship a small tiered oracle library and require each test to name its tier and what it cannot see. Cost: 3 to 5 days.**
Use the cheapest exact tier available, and sampling only when the claim is about sampling.

| Tier | Check | Blind spot | Evidence |
|---|---|---|---|
| A | Exact unitary or statevector, modulo global phase, on two independent simulators | Phase in controlled use, layout, simulator shared by both sides | 2507.17235, QSPE, OOPSLA 2025 |
| B | Controlled version of the same check with an ancilla, where the circuit may be used as a subroutine | Cost | 2610.11195 |
| C | Inverse test or swap test on hardware or when only sampling is possible | Noise baseline | 2510.22418 |
| D | Distribution tests with stated effect size | Expensive, can be unreliable | 2507.17235, 2510.22418 |
| E | Contract checks: layout, permutation, recorded phase, determinism | Only the stated contract | 2609.24230 |
| F | Domain invariants, such as syndrome explanation and weight sum for decoders, or VQE invariants | Narrow scope | 2609.07035, 2606.28742 |

Verdicts must be pass, fail or inconclusive, and a timeout is inconclusive (2610.00255). Use two equivalence checkers where stakes are high, because QITE found 3 bugs in QCEC. I would start from Qiskit's `Operator.equiv` plus MQT QCEC, but that specific pairing is my judgment, not a tested result.

**3. Add a boundary contract test for every conversion path. Cost: about 1 week.**
For each adapter, run an asymmetric circuit through import, transform and export, and compare both semantics and records: qubit order, parameter binding, classical bits, global phase, layout, retained high-level operations. Round trip alone is not enough.
*Evidence:* 2609.13839, 2609.24230, 2610.06142, 2503.17322, 2609.33255. These match our best findings so far. Check whether QITE's artifact can be forked; I did not confirm its availability, and the paper anonymises some details.

**4. Pin and sweep versions, and report "reproduces on" as a set. Cost: 1 to 2 days of setup, then CPU.**
Run each confirmed finding on latest release, previous major line and main. Record a lockfile. Record defaults that can change silently, especially shot counts.
*Evidence:* 2606.27124 (pinning alone is insufficient, 4.6% fixed by updates), 2607.09007 (only 4 of 67 valid across six versions), 2512.08245 (default shots silently changed results), 2607.04072 (give the model the target version and docs).

**5. Set a statistics rule for any test that samples. Cost: 1 day.**
- Fix alpha, effect size and shots before running, and derive shots from the target (2510.22418 gives formulas).
- Correct for multiple assertions with Holm-Bonferroni (QuCheck criticises QSharpCheck for omitting it; 2601.08367 reports one study that used it).
- Rerun each test at least 30 times over different seeds before filing, as 2606.27124 did.
- Never compare seeded counts across frameworks. QSPE reports seeds do not carry across platforms.
- Declare numeric tolerance explicitly, since that is the main flake source (2512.18088).
Worked warning: Bugs4Q artifact 26 failed on correct code at p about 0.024 with 1,024 shots and a 0.05 threshold (2606.27124).

**6. Tie each claim to a stated source of truth, and add a triage class for undocumented behaviour. Cost: 1 day.**
Each claim cites a doc sentence, a published convention or a physics invariant. If none exists, label it "undocumented contract" rather than a bug.
*Evidence:* 2609.07035 (docs answer 4 of 54 questions), RetroQ's phase case became a feature request, QuSema's stated threat that docs may be wrong. This should also protect maintainers' time.

**7. Calibrate the harness on real silent bugs, and report detection and false alarm separately. Cost: 1 to 2 weeks.**
Use known bugs at their buggy commits, not mutants alone. Candidates: QuSema's 20 historical bugs (Table 1), the released 2609.13839 corpus, Bugs4Q-Robust, and RetroQ's cases. Add clean code to measure false alarms. Report uncertainty and audit the evaluator: confirm tests really ran and that reference code cannot leak.
*Evidence:* 2610.22089 (mutants and benchmarks miss 86.3% of recent bug families), 2610.13811, 2610.28678 (scoring choices moved a result from 0% to 94.1%).

**8. Count root causes, and state the oracle beside every number. Cost: under 1 day.**
Publish root causes, witnesses and maintainer status as separate figures, plus rejected reports, which almost no paper gives. QSPE shows why. This would also differentiate our reporting.

**9. Try a verification step inside the review loop before adding more review models. Cost: 3 to 5 days of work. Model cost is unknown at our scale; QuSema reports $162 for three runs over 20 targets and gives no cost for its full-library run.**
QuSema's own component test showed the hypothesis verification stages filter candidates. Its cost table suggests a cheap model in a good loop is close to an expensive one. Treat this as a test to run, not a settled result.

**Not recommended for now.**
- Building a fuzzer. Crash oracles are not our gap, and generating valid programs is costly. Revisit only with Tier A or E oracles attached.
- Bayesian sequential testing (2605.15601) and output dominance (2610.04461). Too new, and aimed at hardware budgets we do not face.
- Citing bug share percentages as if settled.

---

## 4. What I searched, and where it was thin

**Searched.**
- arXiv API, 33 abstract queries sorted by date, 375 records to 29 October 2026. Terms covered bugs, fuzzing, metamorphic, differential, property-based, oracle, mutation, flaky, repair, LLM, Qiskit, compiler, simulator, static analysis, qubit ordering, OpenQASM, PennyLane, Cirq, decoder conformance.
- A second batch of 40 queries added miscompilation, endianness, round trip, Mitiq, deprecation, title-field queries and others. All were completed after rate-limit retries.
- About 13 web searches, including arxiv.org-restricted ones.
- About 75 full texts downloaded and read in targeted sections with keyword extraction. I did not read each paper end to end. Tables above distinguish full from abstract.

**Thin or incomplete.**
- **Semantic Scholar citation trails failed.** Six of eight lookups returned HTTP 429. Only Bugs4Q (74 citers) and one other returned. The Bugs4Q list was not analysed, so citation trails are effectively missing.
- **Paywalled or blocked:** the OOPSLA 2025 simulator paper (conference abstract only) and MorphQ++ (nothing beyond search snippets, UNVERIFIED). Fuzzing-Based Differential Testing for Quantum Simulators (SSBSE 2024) and QuteFuzz (PLanQC 2025) are snippet-only, so I left their numbers out.
- **Non-arXiv venues** are under-sampled, including ACM and IEEE-only papers and QSharpCheck.
- **Error mitigation:** I found no dedicated testing or bug study of mitiq or similar libraries. 2610.22089 has only 4 mitiq bugs. **This is either a real gap or a search miss, and I lean to a real gap.**
- **QEC decoders:** only 2 relevant papers.
- **Hardware noise:** deliberately light, since the harness works on software.
- **Multi-model review:** no study in this lane compares several models reviewing the same quantum code. Other lanes may cover it from general software engineering.
- **Model names** such as GPT-6 Astra and Fable 5 are as stated in the papers. I did not verify them independently.
- Numbers from `ABS` rows come from the abstract only and were not checked against the paper's tables.
