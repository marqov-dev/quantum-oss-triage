# Literature lane B: accuracy of LLM bug and vulnerability finding, and how to measure it

Prepared 2 November 2026 for quantum-oss-triage.

**How to read this.** Papers were read through a fetch tool that extracts from arxiv.org HTML or abs pages, so I did not read every line myself. A long paper was usually read to about the first 100,000 characters. Numbers below come from those extractions unless marked UNVERIFIED. Check a number against the paper's table before quoting it publicly. Each arXiv ID below resolved to the stated title on arXiv. "Preprint" means no venue was shown on the page. Most of this field is unreviewed preprints. Items of mine (arithmetic, inference) are labelled "my calculation" or "my inference".

## Bottom line

1. **Model agreement is weak evidence.** The best measurements of LLM judge panels find about two effective votes from nine models. Nothing I found directly tests whether cross-model agreement predicts truth on code findings. That gap is real, and we can fill it cheaply by logging verdicts.
2. **Execution beats opinion, but a passing test is not proof.** Ten reviewers unanimously approved a nonexistent OpenSSL oracle, and one compile-and-run killed it. Yet 44% of runtime-valid proof-of-concepts in one study never reached the real vulnerable sink. The test step needs its own validity check.
3. **Reported precision is mostly a function of definition, prevalence and benchmark.** Field numbers run from 14% to 91% for reasons unrelated to the model. We need our own sampled estimate with intervals.
4. **Verifiers kill real bugs and framing moves verdicts.** Refutation lowers false positives, but several studies show true-positive loss, and context can collapse detection. Verifiers must be blinded, and their kills must be audited by sampling.

---

## 1. Papers and primary sources read

### 1a. LLM triage of static analysis alerts

| ID | Venue | Method and size | Key verified result |
|---|---|---|---|
| 2601.18844 Du et al. | Preprint; Tencent authors (self-reported, industrial) | 433 alarms from one analyzer (328 FP, 105 TP), 3 bug types, 4 LLMs, 6 techniques, 5 interviews | Hybrid LLM4PFA removes 94–98% of FPs, with recall 0.75–0.88 and precision 0.83–0.93. Basic prompts: precision 0.26–0.29. Failures concentrate in long functions and cascaded conditions. Authors estimate the raw FP rate exceeds 90% once excluded records are counted. $0.0011–$0.12 per alarm. |
| 2510.02534 ZeroFalse | Preprint, tool authors | CodeQL alerts on OWASP (1,974 cases, synthetic) and OpenVuln (58 alerts, 7 Java projects) | Best F1 0.912 and 0.955. Prompt comparison is confounded: the optimised prompt adds information. Gemini 2.5 Pro's OpenVuln F1 fell from 0.615 to 0.372 with the optimised prompt, recall 0.229. The 58-alert set cannot rank models. |
| 2607.09979 Klieber et al. (SEI) | Preprint | Juliet 100, FormAI 76 (hand adjudicated), SV-COMP 101. N=10 trials, 80% threshold, else "uncertain" and sent to a human | Recall ≥98%, specificity ≥94.8%. FormAI uncertain rate at 80%: about 11–12% of alerts for o4-mini. Juliet shows memorisation (68% exact variant recovery). Not real code and no real analyzer in the loop. Answer keys were revised after LLM disagreement. Triggers: 18/30 TPs valid, 0/27 FPs valid, so a valid trigger is strong and an absent one is weak. |
| 2601.22952 Sifting the Noise | Preprint; Monash | Aider, OpenHands, SWE-agent × 3 models. OWASP 2,740; Vul4J 50 alerts; OSS-Fuzz 50 alerts, κ=0.725, 86% raw agreement | Best OSS-Fuzz configuration 95.5% precision and FP recall on n=50. Removing cross-file navigation dropped accuracy to 44%. 314 of 1,411 true OWASP vulnerabilities mislabelled as FP (about 22%). Miss rates per CWE: 0.4–2.4% for injection, 50–85% for config and crypto classes. Authors conclude automatic suppression is unsafe. |
| 2506.10322 LLM4PFA | Preprint; tool authors | 364 warnings from CodeQL, Infer, CppCheck on Linux, OpenSSL, Libav; 45 real | Filters 72–96% of FPs, misses 3 of 45 real bugs. |
| 2608.09181 Memoir | Preprint | 865 CodeQL alerts; Tencent internal | FP-F1 98.82%, but TP-recall 0.50 (keeps 3 of 6). Test set has six true alerts. Illustrates FP metrics hiding TP loss. |
| 2610.23035 VulnSAGE | Preprint; tool authors; abstract read only | 187 labelled reports; 45,440 alerts on 200 C/C++ projects | 89/97 FPs rejected, 85/90 real kept. 104 defects reproduced at runtime from 45,440 alerts (0.23%, my calculation). Maintainers confirmed 24 of the 26 they answered. LLM claims are checked against program facts. |
| 2609.04535 Sajadi et al. | Preprint | 500 reviewed CodeQL FPs, CWE-Bench-Java | Query refinement removed 81.8% of reviewed FPs, keeping 49/56 TPs. Agents wrote working refinements 56–62% of the time when guided. Paper's text is inconsistent on the TP figure (7/8 vs 49/56). |
| 2504.11711 BugLens | Preprint on arXiv; ASE 2025 per the authors' repo (search result, not checked at IEEE) | Linux taint-style warnings | Precision 0.10 to 0.72. |
| 2405.17238 IRIS | Preprint | 120 Java CVEs | CodeQL 27, IRIS 55. Later study 2601.19239 measured its false discovery near 98%. |
| 2605.01885 QASecClaw | Preprint | OWASP, Semgrep | FPs 560 to 64, TPs 1,273 to 1,233. Synthetic. |

### 1b. Detection on real repositories

| ID | Venue | Method and size | Key verified result |
|---|---|---|---|
| 2601.19239 Li et al. | Preprint | 265 known vulns; 24 live projects; 6,442 sampled warnings; 355 hand-inspected; stratified sampling (Cochran). LLM labels validated at 87.76%. Each configuration run once | Sampled false discovery rate: Codex 9.09% (C/C++), 31.82% (Java); Claude Code 74.07%, 81.82%; CodeQL 86.01%, 77.00%. Specialised tools 92–100%. Recall (Java): Claude Code 81.94%, Codex 63.87%, CodeQL 14.19%. About 63% of FPs were benign points misclassified. Codex averaged 2.44 warnings per project against CodeQL's 752.67 on C/C++. |
| Semgrep 2025 blog | Vendor | 11 Python web apps, 445 findings, all manually triaged | Claude Code 46/330 (14%), Codex 21/115 (18%). One app on repeat: 3, 6, 11 findings. Older models. |
| 2604.13764 RealVuln | Preprint; authors sell a ranked scanner, ground truth open | 26 deliberately vulnerable Python repos, 796 labels | Sonnet 4.6: P 0.785, R 0.498. Semgrep P 0.205, R 0.175. SonarQube P 0.611, R 0.065. Vendor's tool ranks first only under F3; sixth under F1. |
| 2606.21397 Neef et al. | Preprint | 4 WordPress plugins, 6 models, 360 reports | Detection 35–63%. Consistency 50–95%. Semgrep found none. No precision measured. |
| 2606.22263 Revelio (Berkeley) | Preprint; tool authors | 100 CyberGym projects; 7 OSS-Fuzz projects | Self-validation by sanitizer in a fresh subprocess. Claimed-to-valid: 175/175 vs Claude Code about 51%, Codex 40% (my calculation). 19 new vulns, all hand-validated, 10 fixed. Ablation credits programmatic enforcement over prompt wording. Memory safety only. |
| 2606.19149 OpenAnt | Preprint; authors maintain the tool | 8 projects, $1,461 | 376 flagged, 190 survive adversarial stage, 144 reproduced. No human adjudication, no CVE list. |
| 2609.05335 Bugstone-E2E (IBM) | Preprint; tool authors | 14 projects; wolfSSL 64 CVEs; Pillow 10 identical runs | 2,933 findings, 2,125 adjudicated, 644 with runtime evidence, 1,099 rejected. Ten-run union 243 locations, 56 in all ten. Three runs recover 75.8% of union (from a search extract). "Failure to construct or exercise an environment remains distinct from evidence that a finding is not exploitable." |
| 2606.15762 Snyk VulnBench | Preprint; vendor, reference set is its own tool | 10 small JS fixtures, 5 runs each | Of unmatched findings, 49.7% appear once in five. Of matched findings, 84.8% appear in all five. Best configuration was the cheaper one; 5.67x spend scored lower. |
| 2607.27030 HoF-Bench | Preprint; AISLE co-authors (vendor) | 95 AI-found CVEs, 10 non-frontier models | Best 68.4% over four passes. One pass recovers about 68% of four. 62% of successes were intermittent. Mixing models beat repeating one (70 CVEs for $66 vs 65 for $128). Three rounds plus arbiter barely moved results (974 to 1,007). C median recall 31%, JS 81%. Recall only. |
| 2610.33509 SecPRBench | Preprint; UIUC, FPT | 265 buggy tasks with fixed twins, real commits | Recall 32.5–78.1%. Top four statistically tied. Eight-agent union 91.3%. Logic bugs about 50% vs memory about 73%. Explicitly does not measure precision. No repeat runs. |
| 2607.03316 CodeRabbit | Preprint; abstract read | 31,073 review-feedback pairs, 239 repos | 36.4% accepted, 7.3% discussed, 56.3% rejected, mainly FP, redundant, out of scope, or against intent. |
| 2603.11078 CR-Bench | Preprint | 174 verified tasks | Precision 3–5% against one known bug; "usefulness" 48–84% by an LLM judge. Shows how much the definition matters. Preliminary. |
| 2603.23448 c-CRAB | Preprint | 234 human comments turned into tests | Tools pass 20–32%; union 41.5%. Manual check of 92 comments: 84% useful. |
| 2609.08040 VEX-Bench | Preprint; Purdue and Red Hat; see 1d | | |

### 1c. Multi-model, agreement, refutation, framing

| ID | Venue | Method and size | Key verified result |
|---|---|---|---|
| 2506.07962 Kim et al. | ICML 2025 | 350+ LLMs | Two models that both err give the same wrong answer 60% of the time on one leaderboard dataset. More accurate models correlate more, across providers. Not code. |
| 2605.29800 Kohli (Apple) | Preprint; search shows a NeurIPS 2026 listing, not checked | 9 judges, 7 families, NLI and RewardBench, 1,000 items each | n_eff 1.99–2.48. Panel lost to the best single judge on 3 of 4 datasets (up to 6.5 points). Cross-family barely decorrelates (0.047); top three correlated pairs are cross-family; one-per-family gives n_eff 1.93. Best stable aggregator closes ≤11% of the gap. Not code. |
| Zhang & Martinez, neurips.cc listing (no arXiv ID) | NeurIPS 2026 listing | 52,500 decisions, 7 open judges | Ten repeated ratings equal 1.06–1.81 independent ones. Binomial latent class model: 0 of 42 cells' intervals contained the human value. Beta-binomial coverage 0.90. A few gold labels fix population estimates, not item verdicts. |
| 2601.22336 | Preprint; abstract | Theory plus 3 datasets | Conditional-independence aggregators stay strictly suboptimal as judges grow. |
| 2604.07650 | Preprint; abstract | 18 LLMs, 6 families | Hidden entanglement correlates with judge over-endorsement (rho about 0.5). De-entangled reweighting: +3.5 points accuracy. |
| 2607.13918 | Preprint; theory, synthetic only | Single independent author | Correlated gates decay polynomially, not exponentially. Recommends changing family, modality or evidence source over adding gates. |
| 2610.01471 | Preprint; single author, partly AI-generated | 30 artifacts (10 code), 150 seeded defects, automated matching not audited | Same-plus-cross review 56.7% vs two same-model 42.7%. Cross-model vs fresh same-model: not significant. On code, fresh same-model F1 40.7 vs GPT-5.4 37.2. |
| 2604.19049 Refute-or-Promote | Preprint; single operator, retrospective, no recall, no ablation | 7 targets, about 171 candidates, 31 days | Kills about 79% (83% prospective, n=30). 4 CVEs. Ten reviewers unanimously confirmed a false OpenSSL oracle; one compile-and-run killed it. Cross-model critic: about 5 kills (about 3% of kills), and found errors in 3 of 19 same-family-approved fixes. CVSS lowered in 8 of 9. |
| 2604.21282 | AAMAS 2026 | 262 Juliet functions | Verifier cut FPs 119 to 78, zero TPs lost, final precision only 0.629. Single expert beat three experts without verifier. Synthetic. |
| 2505.10961 VulTrial | Preprint plus unnamed DOI; abstract | Mock court | Claims near doubling of baselines. FPR 0.45 seen only in a search extract: UNVERIFIED. |
| 2603.18740 | Preprint (title changed across versions) | 497 files × 6 LLMs × 5 framings; 33 reintroduced CVEs | GPT-4o-mini detection 97.2% to 3.6% under strong bug-free framing. Opus 4.5 dropped 6.9 points. Neutral FP rate ≥88% on most models. Iterated PR framing got 32/33 reintroductions past Claude Code and CodeRabbit. Redacting PR description recovered 50%; also redacting commit message and comments recovered 12 of the remaining 16. |
| 2606.30587 | Preprint | 8 models, code held fixed | Mean susceptibility: framing 33.2%, anchoring 23.5%, halo 18.4%. Prompt defences only partial, and the strong one backfired on Claude. |
| 2503.05061 No Free Labels | Preprint | 1,200 responses | When the judge cannot answer the question itself, κ fell to 0.14 with self references vs 0.80 with human references. Applies directly to asking a model to confirm a claim it could not find. |
| 2609.20211 | Preprint (ID and listed date do not match; check) | Monitors, not code | Dropping "unverified" provenance raised risky approvals from 5% to 60%. |
| 2610.29379 Evron | Preprint; single author, co-maintains two studied tools; no prevalence claimed | 12 harnesses | 13 silent drop points. Errors and unparsable replies recorded as clean. |
| 2610.08406 | ICDA 2026; abstract; DAST | DVWA, WebGoat | Aggregated alerts bind true and false cases, so verify per case. |
| 2602.11619 | Preprint | HotpotQA | Run consistency predicts correctness, partly through task difficulty. Not code. |
| 2606.31159 | ICSME 2026; abstract | Generated code | Overconfidence prevalent. Calibration worsens in realistic repository settings. |

### 1d. Dependency reachability

| Source | Status | Result |
|---|---|---|
| 2609.08040 VEX-Bench | Preprint; 75 cases, 67 CVEs, Go/Java/Python; 5 annotators, no κ reported | 70.7% of cases not affected; 50.7% of the benchmark is code_not_reachable. Opus 4.6 P76.3 R87.9; GPT-5.5 P88.7 R72.7. OSV-Scanner precision 27.4, Trivy 26.0. $0.08–$1.08 per case. Opus over-calls vulnerable; GPT-5.5 tends to requires_configuration. govulncheck completed 19 of 30; extraction lacked column headers so its figures are not usable. Python worst (status F1 71.3). |
| GitHub changelog, 28 Oct 2026 | Primary | Dependabot reachability public preview: JS/TS only, Enterprise Cloud only, verdicts do not close alerts. "Potentially reachable" should be treated as reachable. |
| Semgrep 2022 blog | Vendor, primary for its own number | 31 of 1,614 Dependabot alerts reachable (1.9%) across 1,000 forked repos. Treat as upper-end marketing. |

### 1e. Large real-world efforts

| Source | Status | Result |
|---|---|---|
| DARPA AIxCC results, 8 Aug 2025 | Primary | 63 synthetic (corrected from 70), 54 discovered, 43 patched; 18 real vulns, 11 patched. About $152 per task, 54M+ LoC. |
| 2602.07666 AIxCC SoK | Preprint; authors include organisers and teams; winning team's lead is senior author | "Stability and accuracy were deciding factors." Theori lost second place through the accuracy penalty. Proofs of vulnerability were the main ground truth. Manual review found 37.7% and 45.6% of baseline patches passing automated checks were wrong or incomplete. Coarse crash dedup merged distinct bugs. A strict PoV-only SARIF strategy could not confirm invalid reports. |
| 2603.08566 OSS-CRS | Preprint; Atlantis team | AIxCC systems "largely unusable outside their original teams". Port: 10 new bugs across 8 projects, $50 per campaign; 3 fixed, 6 pending. Ensemble gain unquantified. |
| Anthropic Glasswing update | Primary, vendor | Open source: 23,019 findings, 6,202 estimated high or critical, 1,752 assessed, 1,587 valid (90.6%), 1,094 confirmed high or critical (62.4%). 75 of 530 disclosed patched. Maintainers asked to slow down. Validity is of assessed findings after an internal pipeline. |
| Anthropic Mythos Preview | Primary, vendor | ASan "perfectly" separates memory bugs from hallucinations; a final "real and interesting" pass; humans validated every report. Severity matched exactly in 89% of 198. Authors say logic bugs lack such an oracle. |
| Anthropic zero-days | Primary, vendor | 500+ high-severity validated, no FP rate published. |
| Big Sleep (Project Zero, 2024) | Primary | One SQLite underflow, verified by assertion failure; no success rates; "highly experimental". 2025 count of 20 bugs: news only, UNVERIFIED. |
| Heelan 2025 | Primary, individual | o3: CVE found in 8 of 100 runs, 28 FP. At 12k LoC: 1 of 100, about 1:50 signal to noise. |
| Stenberg, Jan 2026 | Primary | curl confirmed rate fell from above 15% to below 5%. Bounty ended. PRs are less of a problem because CI filters them. |

### 1f. Measurement without ground truth

- 2301.09633 Prediction-Powered Inference (preprint, Angelopoulos et al.): valid intervals from a small labelled sample plus many model predictions, with no assumption on the model. Abstract read.
- 2403.18624 PrimeVul (ICSE 2025): F1 68.26% on BigVul fell to 3.09% on a cleaned, realistic set.
- 2507.17093 (ICSME'25 registered report): abstract only states the protocol, so no result to cite.
- 1803.02130 STADS (Böhme) and the fuzzing residual-risk line: search extract only.
- Capture-recapture in inspections: Petersson et al. review and related critiques, search extracts only.
- 2512.01609 GPTrace (ICSE 2026): LLM embedding crash dedup beats stack hashing on 300,000+ crashes, 50 labels. Crash inputs, not findings.
- 2601.17471 PatchIsland: separates crash-side from patch-side duplicates (search extract).
- 2601.14455 (preprint, abstract): 9 Actions workflow scanners on 2,722 workflows differ greatly. Needs a full read by whoever covers scanners.

### UNVERIFIED (seen only in search extracts or secondary sources; do not cite without checking)

Google's 10% effective false positive threshold (the research.google page does not state it; book and survey summaries do). OpenAI Aardvark 92% recall and Codex Security counts. VulAgent FPR 39.76%. MultiVer. 2509.12629 ensemble results (PDF undecodable). Dawid-Skene 90.7% vs 71.0% (ACL 2026 workshop). Thornton 2026 and Sun, Oprea and Wong 2026 (cited in 2610.29379). Stenberg's "several hundred bugs fixed" from ZeroPath and Aisle. PoCGen, V2E, SEC-bench Pro figures. PrimeVul's 24–60% label accuracy (secondary).

---

## 2. What the evidence says

### Precision on real code

Reported precision ranges widely, and most of that spread is not model quality.

- **Raw agent output:** 14–18% (Semgrep, 2025 models); sampled false discovery of 9–82% (2601.19239); 36% developer acceptance for a commercial reviewer (2607.03316).
- **After pipeline and human assessment:** 90.6% validity (Glasswing, self-reported, memory-heavy, frontier unreleased model).
- **The definition does most of the work.** CR-Bench shows 3–5% against one known bug and 48–84% "useful" on the same outputs. SecPRBench and HoF-Bench refuse to score precision at all, because unmatched findings are unknown, not wrong. Our FP definition must be stated explicitly.
- **Prevalence changes precision.** Tencent's LLM4PFA with Opus 4: recall 0.88, FP elimination 0.94, precision 0.83 at 24% true alarms. At 10% true alarms the same rates give precision 0.62 (my calculation). Benchmarks with balanced classes flatter everything.
- **Volume is a real trade-off.** Codex's low false discovery in 2601.19239 came with about 2.44 warnings per project, compared with Claude Code's higher FDR but better Java recall. Per-model rankings flip across studies (VEX-Bench, Semgrep, RealVuln, 2601.19239), and SecPRBench's top four tie. Do not fix a model hierarchy from the literature.
- **Bug class matters as much as model.** Memory-safety bugs have sanitizers. Logic bugs have lower recall (SecPRBench) and no oracle (Anthropic). Quantum Python libraries will sit mostly in the harder half (my inference).

### Does agreement predict truth?

**No direct evidence on code findings. Adjacent evidence says weakly at best.**

- Kim, Kohli, Zhang & Martinez, 2601.22336 and 2604.07650 all point the same way, in non-code settings.
- Refute-or-Promote gives one vivid code instance: ten unanimous and wrong. It is one anecdote.
- Self-consistency has more support. 2607.09979 gets strong results from a 10-trial threshold, and Snyk finds real matches recur more than noise. Against this, Zhang & Martinez find repeats carry little independent information, and 2607.09979 used synthetic code. Reconciling view: recurrence is useful as an **uncertainty flag** that routes to a human, not as confirmation.

### Does a second model help?

**Disagreement by purpose.**

- **For finding (recall): yes.** HoF-Bench (mixing beats repeating), SecPRBench (union 91.3% vs best 78.1%, though top four capture nearly all), 2610.01471 (56.7% vs 42.7%).
- **For verifying (precision): thin.** Refute-or-Promote's cross-model critic made about 3% of kills. HoF-Bench's extra triage rounds changed little. 2610.01471 found no significant gain on code. Kohli finds family diversity barely decorrelates.

### Refutation and debate

Refutation stages clearly kill candidates (79–83%; about 50% in OpenAnt; 41 of 119 FPs in AAMAS). No study has a clean design measuring both FPs and TP loss on real code at scale. Refute-or-Promote does not measure recall. Separately, triage filters clearly lose real bugs: about 22% in Sifting the Noise, 0.72–0.94 recall in Tencent, 3 of 6 in Memoir. Loss concentrates in config and crypto rules, where "reachable and exploitable?" is the wrong question. Tension: the Tencent 94–98% headline vs Sifting's "automatic suppression is unsafe" is not a real conflict, since Tencent recall is also well below 1.

### Framing and adversarial context

This is the most consistent and striking finding in the lane. Metadata and prior verdicts move results by large margins even with code fixed. Prompt defences are partial and model dependent. Redaction works better than instruction. The review target itself is an attack surface (2603.18740, 2606.30587, 2610.29379).

### Executable validation

All large efforts converge here: AIxCC, Anthropic, Revelio, Bugstone, OpenAnt, VulnSAGE. Limits:

- PoC-Gym: 116 of 338 runs runtime-valid, 65 survive location checks. 44% false.
- AIxCC SoK: 37.7–45.6% of test-passing baseline patches were wrong or incomplete.
- 2607.09979: 0 of 27 FPs yielded valid triggers, but only 18 of 30 TPs did. Asymmetric: a good test confirms; no test proves nothing.
- Bugstone: only 644 of 2,125 got runtime evidence.

The apparent conflict between 2607.09979 and PoC-Gym depends on validator strictness. The test's validity rule is the critical design choice.

### Dependencies

Reachability filtering is valuable. Roughly two-thirds or more of alerts are not affected on the evidence available, though VEX-Bench's sample was mined, not random, and Semgrep's figure is a vendor claim. LLM agents beat plain SCA on 75 cases, at a precision of only about 76–89%. Authors stress reachability is not exploitability. No function-level benchmark exists for Python, because CVE-to-function data is reliable only for Go per VEX-Bench. For libraries, "reachable from user code" needs redefining as "exposed through public API" (my inference).

### Human labels are noisy too

Humans are a noisy reference too: κ=0.725 on 50 alerts in the best-reported case, and Klieber revised keys after LLM disagreement. VEX-Bench and the extracted part of 2601.19239 report no κ.

---

## 3. Ranked changes to our method

Costs are rough, for one engineer, excluding LLM spend unless stated.

### 1. Make test validity a separate gated check, and tier findings by evidence. Cost: 3–5 days.

The test must (a) fail on the code as is, (b) pass on a minimal fix or mutated version, (c) be run by the harness in a fresh process, not reported by the model, (d) reach the claimed line, shown by coverage or a trace, and (e) fail with the claimed error, not an import or setup error.

Tiers: **reproduced**, **argued only**, **test not constructible**. Never read "no test" as refuted.

Evidence: PoC-Gym, Refute-or-Promote, Revelio's subprocess re-run, AIxCC SoK, 2607.09979, Bugstone's quote. For logic bugs, state the oracle explicitly in the finding and have the person review it.

### 2. Blind the verifiers. Cost: 2 days.

Give the refuter the claim, the code and entry points. Withhold the finder's reasoning, model name, prior verdicts, PR descriptions, commit messages. Strip or test with and without comments for security-claim checks. Keep the repo's threat model as separate trusted input.

Evidence: 2603.18740 (redaction beats instruction), 2606.30587 (anchoring 23.5%), Refute-or-Promote (asserted, no ablation), No Free Labels. Delimit target text as data. Keep verifier prompts neutral: "determine whether" rather than "refute", and record both. Whether an adversarial mandate biases toward false kills has not been isolated in the literature.

### 3. Log every verdict, and report effective independence rather than vote counts. Cost: 1–2 days.

Agreement should be a routing signal only. Publish per-pair error correlation and Kish n_eff once 100+ findings are human-adjudicated. Publish precision by agreement level with intervals. If agreement does not separate outcomes on our data, drop it from the UI.

Evidence: Kim, Kohli, 2604.07650, 2601.22336. This is also a publishable result, since I found no direct study on code findings. Do not use unmodified Dawid-Skene or majority vote as a truth estimate.

### 4. Estimate precision by stratified random sampling. Cost: 2 days tooling, then person time per batch.

- Sample within each stratum: model, scanner, tier, bug class. Do not review only top-ranked items.
- Report Wilson or Clopper-Pearson intervals with raw counts. For scale: 45 of 50 true gives 90%, 95% interval about 79–96%. Zero FPs in 30 still allows up to about 10%. (My calculations.)
- Two independent raters on at least 50 items, report κ, resolve by discussion (2601.22952's design). Blind raters to model and verdict.
- Define three levels and report each: **technically true**, **actionable under the repo's threat model**, **maintainer accepted**.

Evidence: 2601.19239 SFDR design, CR-Bench, 2607.03316, Zhang & Martinez (a few gold labels suffice for population estimates). Prediction-powered inference is an optional extension for using LLM labels on the unsampled remainder, but it has not been tested on this task.

### 5. Audit kills. Cost: 1 day, plus sampling time.

Move killed findings to a queryable pile, never delete. Sample about 20–30 per batch, stratified by killing stage and bug class, for human review. This gives verifier false-kill rate, which almost no paper reports well. Since a false positive costs more than a miss, tolerate some loss, but know its size.

Evidence: Sifting (22%), Memoir, Tencent, 2610.29379 class 7.

### 6. Require a threat model and an attacker story. Cost: 0.5 day per repo; 1 day for the template.

Each security claim names attacker, entry point, boundary crossed and impact. The final filter asks whether it is real and of interest to this project. Research libraries may treat many input issues as non-security, so route these as ordinary bugs (as Revelio did with NULL dereferences).

Evidence: Revelio, OpenAnt's harm requirement, Anthropic's final pass, CVSS lowered 8 of 9, CodeRabbit's rejection reasons, 2610.29379 "wrong threat model".

### 7. Route alerts by class before LLM triage. Cost: 2–3 days.

Keep config, crypto and hardening rules out of "exploitability" filtering. Report them through rule-level policy. Give the LLM trace, cross-file navigation and a CWE rubric for dataflow rules. Suppress recurring FPs in the rule or config, not with model memory.

Evidence: Sifting per-CWE rates and navigation effect, Tencent hybrid vs prompt, 2609.04535. ZeroFalse's rubric gain is confounded, so try it but measure it.

### 8. Record coverage and treat failures as not analysed. Cost: 1–2 days.

Emit a manifest of files and units scanned, skipped and why. Timeouts, refusals and unparsable output become "not analysed". Key caches on harness version and model.

Evidence: 2610.29379 (prevalence unknown), AIxCC SoK's finding that stability decided results. Cheap, and protects every other metric.

### 9. Dependency advisories: staged VEX output. Cost: 3–5 days; about $0.10–$1 per advisory (VEX-Bench's range).

1. Scanner match.
2. Deterministic call graph where one exists; treat incomplete results as unknown.
3. For Python, an agent with a required evidence path: import, call site, version, configuration.
4. Output a VEX status and justification. "Not reachable" lowers priority and never closes.
5. For libraries, ask about public-API exposure.

Sample "not affected" verdicts, since this is where models err. Evidence: VEX-Bench, GitHub's verdict semantics.

### 10. Use cheap repeats as a triage signal only. Cost: 2–3× LLM spend on the finding stage.

Run each model 2–3 times. Rank findings seen once lower, and route split verifier verdicts to "uncertain" with a threshold. Do not treat recurrence as confirmation, and do not delete singletons, since real findings can be intermittent (HoF-Bench 62%).

Evidence: Snyk, Bugstone, 2607.09979, Zhang & Martinez. Given our FP priority, more value comes from the routing than the extra recall.

### 11. Dedup conservatively, and verify one claim at a time. Cost: 2 days.

Key on rule or CWE plus file and enclosing function, then let an LLM propose merges for a person to accept. Prefer under-merging. Keep raw findings. Compute agreement after dedup and report sensitivity to matching rule. Never send bundled findings to a verifier.

Evidence is thin: AIxCC SoK, 2610.08406, Bugstone's 93.7%-calibrated matcher, GPTrace by analogy only. Hand-check a dedup sample.

### 12. Seed known bugs to measure recall and catch regressions. Cost: 3–5 days, then per release.

Reintroduce real post-cutoff bugs from the same repos' history, paired with fixed versions (SecPRBench, c-CRAB designs). Avoid well-known public benchmarks, which show memorisation (2607.09979). Also seed a few plausible false findings to measure whether the verifier and test stage reject them.

### 13. Treat capture-recapture as a rough lower bound. Cost: 0.5 day, in analysis notebooks.

I found no application to LLM findings. Overlap between models violates independence and equal catchability. Positive dependence typically makes estimates too low (standard result, not verified from a paper in this search). Use Chao-style bounds across runs only as a descriptive "how much is left" indicator, labelled as such, and never as a recall claim.

### Not recommended

- Adding more verifier rounds. HoF-Bench shows little gain; theory predicts plateaus.
- Debate protocols as a precision mechanism, without an execution stage.
- Self-reported model confidence as a filter (2606.31159; related work).
- Citing benchmark F1 or vendor precision as an expected rate for our harness.

---

## 4. What I searched, and where the search was thin

**Searched:** about 30 extended and standard web searches, mostly restricted to arxiv.org, across: triage, refutation, agreement, correlated errors, AIxCC, reachability, code review, capture-recapture, seeded bugs, dedup, calibration, repeat runs, PoC validation, framing, latent class models, and maintainers' outcomes. Direct fetch of arXiv search pages (5 queries) returned only 1–5 results each, so the listing route was weak and I relied on web search and citation trails. Citations were followed from 2604.19049, 2609.05335, 2610.29379 and 2609.26550.

**Thin or null:**
- Direct test of cross-model agreement against truth on code findings: **none found**.
- Capture-recapture on LLM findings: **none found**.
- Dedup of agent findings at different locations: **none found**; only crash dedup.
- Maintainer rejection rates for AI vulnerability reports at scale: none; only small disclosure counts and Glasswing patch data.
- Function-level reachability benchmark for Python: none found. GitHub's feature has no published accuracy.
- Scanner accuracy for Actions workflows: only 2601.14455's abstract; no zizmor or actionlint precision obtained.
- Scientific or quantum Python code: nothing specific. All precision figures transfer poorly.
- Papers read past the first 100,000 characters: 2601.19239, 2609.08040 and 2607.09979 only. Tail sections of others, including AIxCC SoK's appendices, were not read.
- PDFs that failed to decode: resolved through HTML where possible. 2509.12629, 2606.18619 (Code-Augur) and 2606.30653 stayed unread.
- Peer review is uncommon here. Reviewed or accepted items in this report: Kim (ICML), PrimeVul (ICSE), GPTrace (ICSE), 2604.21282 (AAMAS), 2606.31159 (ICSME), 2610.08406 (ICDA). BugLens at ASE and two NeurIPS listings need checking.
- Vendor and self-report caution: Anthropic, Snyk, Semgrep, Kolega, AISLE, IBM, Knostic, Tencent. Anthropic sources concern a model family used in our harness and were produced by its maker. Several 2026 results involve models we may not use, so absolute rates should not transfer.
