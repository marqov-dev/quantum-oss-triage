# Evaluation set

Each folder is one evaluation case: a small repository plus `expected.yaml`
(see [CONTRIBUTING](../docs/CONTRIBUTING.md)). `qot evaluate` copies a case into
a run directory, makes it a git repository and runs the full pipeline on it.

**Every credential in these cases is fake.** They are planted test fixtures
for the secret scanners and the review skills. For example,
`planted-bugs/qtoy/config.py` contains a made-up token for a fictional
service (`api.qtoy.example`). None of them grant access to anything.

This README sits outside the case folders, so the reviewing models never see
it. A marker inside a case would give the planted defect away.
