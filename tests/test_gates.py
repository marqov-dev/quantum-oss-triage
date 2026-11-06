"""Automatic gates: evidence class, rerun stability and the default-branch check."""

from harness.stages import gates

HEAD = "QOT_CONTROL_RC=0\nQOT_REPRO_RC=1\n---CONTROL---\n1 passed\n---REPRO---\n"
ASSERT = HEAD + "E       assert -1 == 5\n/inputs/test_qot_repro.py:9: AssertionError\n1 failed\n"
CRASH = HEAD + ("E           ValueError: shape (2, 2) but it has (4, 4) at 0x10ab\n"
                "mitiq/rem/inverse_confusion_matrix.py:188: ValueError\n1 failed\n")
DEP_CRASH = HEAD + ("E   ValueError: Measuring an empty set of qubits.\n"
                    "/deps/venv/lib/python3.12/site-packages/cirq/ops/measurement_gate.py:75: ValueError\n1 failed\n")


def test_evidence_classes():
    assert gates.evidence(ASSERT, False) == "assertion"
    assert gates.evidence(CRASH, False) == "crash"
    # The exception was raised inside a dependency, and no project frame shows.
    assert gates.evidence(DEP_CRASH, False) == "none"
    assert gates.evidence(CRASH.replace("QOT_CONTROL_RC=0", "QOT_CONTROL_RC=1"), False) == "none"
    assert gates.evidence(HEAD + "E   ModuleNotFoundError: No module named 'x'\nmitiq/a.py:1: E\n", False) == "none"


def test_signature_ignores_addresses():
    assert gates.signature(CRASH) == "ValueError: shape (2, 2) but it has (4, 4) at 0x"


def _runs(rows):
    return "\n".join(f"QOT_RUN {i} {c} {r} E       {e}" for i, (c, r, e) in enumerate(rows, 1))


def test_stability_needs_every_run_to_match():
    want = "assert -1 == 5"
    good = gates.stability(_runs([(0, 1, want)] * 3), want, 3)
    assert good["passed"] and good["runs"] == 3
    flaky = gates.stability(_runs([(0, 1, want), (0, 0, ""), (0, 1, want)]), want, 3)
    assert not flaky["passed"] and flaky["inconsistent_runs"] == [2]
    assert not gates.stability(_runs([(0, 1, want)] * 2), want, 3)["passed"]  # a run went missing


def test_timed_out_reruns_are_inconclusive_not_unstable():
    st = gates.stability("", "x", 3, timed_out=True)
    assert gates.verdict("assertion", st, "still_fails")[0] == "inconclusive"
    st = gates.stability(_runs([(0, 0, "")]), "x", 3, timed_out=True)
    assert gates.verdict("assertion", st, "still_fails")[0] == "failed"


def test_rerun_keeps_a_literal_backslash_n_on_one_line(tmp_path, monkeypatch):
    import subprocess
    fake = tmp_path / "fake.sh"
    # The control passes; the reproduction fails with a repr holding a literal backslash-n.
    fake.write_text("case $1 in *control*) exit 0;; esac\nprintf '%s\\n' 'E       assert a\\n]'; exit 1\n")
    monkeypatch.setattr(gates, "_PYTEST", f"sh {fake}")
    script = gates.rerun_script(2).replace("/tmp/", f"{tmp_path}/")
    out = subprocess.run(["sh", "-c", script], capture_output=True, text=True).stdout
    assert gates.stability(out, "assert a\\n]", 2)["passed"]


def test_still_present():
    sig = gates.signature(ASSERT)
    assert gates.still_present(ASSERT, False, "assertion", sig) == "still_fails"
    assert gates.still_present(HEAD.replace("REPRO_RC=1", "REPRO_RC=0"), False, "assertion", sig) == "passes"
    assert gates.still_present(ASSERT.replace("-1 == 5", "-2 == 5"), False, "assertion", sig) == "inconclusive"
    assert gates.still_present(ASSERT, True, "assertion", sig) == "inconclusive"


def test_verdict():
    ok = {"passed": True}
    assert gates.verdict("assertion", ok, "still_fails")[0] == "passed"
    assert gates.verdict("crash", ok, "passes")[0] == "failed"
    assert gates.verdict("assertion", {"passed": False}, "still_fails")[0] == "failed"
    assert gates.verdict("none", None, None)[0] == "no_evidence"


def test_best_attempt_prefers_assertion_over_crash(tmp_path):
    for i, out in enumerate([CRASH, ASSERT]):
        (tmp_path / str(i)).mkdir()
        (tmp_path / str(i) / "output.txt").write_text(out)
    d, _, ev = gates._best_attempt(tmp_path)
    assert ev == "assertion" and d.name == "1"
    assert gates._best_attempt(tmp_path / "missing") == (None, "", "none")


def _git(*args, cwd):
    import subprocess
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def _commit(repo, name, tag=None):
    (repo / name).write_text(name)
    _git("add", ".", cwd=repo)
    _git("commit", "-qm", name, cwd=repo)
    if tag:
        _git("tag", tag, cwd=repo)


def test_checkout_follows_upstream_on_every_run(tmp_path):
    """The head and release checks must use upstream as it is now, not a clone from an earlier run."""
    from types import SimpleNamespace
    up = tmp_path / "upstream"
    up.mkdir()
    _git("init", "-q", "-b", "main", cwd=up)
    _commit(up, "a", tag="v1")
    ctx = SimpleNamespace(repo_dir=tmp_path / "run", spec=SimpleNamespace(source=str(up)))
    head1 = gates._checkout(ctx, "head")[1]
    rel1 = gates._checkout(ctx, "release")[1]
    assert head1 == rel1
    _commit(up, "b", tag="v2")
    _commit(up, "c")
    head2 = gates._checkout(ctx, "head")[1]
    rel2 = gates._checkout(ctx, "release")[1]
    assert head2 != head1 and (ctx.repo_dir / "gates" / "head" / "source" / "c").exists()
    assert rel2 not in (rel1, head2)  # the newest tag, v2


def test_cached_gate_rechecks_only_the_trees_that_moved(tmp_path):
    """A rerun with a new upstream head repeats the head check, not the twenty reruns."""
    from types import SimpleNamespace
    from harness.controller.ledger import Ledger
    from harness.workers.base import WorkerResult
    run_dir = tmp_path / "run"
    attempt = run_dir / "o__r" / "evidence" / "repro" / "QOT-1" / "0"
    attempt.mkdir(parents=True)
    (attempt / "output.txt").write_text(ASSERT)
    scripts = []
    reruns = "".join(f"QOT_RUN {i} 0 1 E       assert -1 == 5\n" for i in range(1, gates.RERUNS + 1))

    def run(script, src, inputs=None, timeout_s=0):
        scripts.append(script)
        if "seq" in script:
            return WorkerResult(0, reruns, "")
        fixed = "new" in str(src)
        return WorkerResult(0, HEAD.replace("REPRO_RC=1", "REPRO_RC=0") if fixed else ASSERT, "")

    ctx = SimpleNamespace(run_dir=run_dir, repo_dir=run_dir / "o__r", spec=SimpleNamespace(name="o/r"),
                          ledger=Ledger(tmp_path), worker=SimpleNamespace(run=run), source_dir=tmp_path)
    f = {"id": "QOT-1", "validation": {"status": "reproduced"}}
    first = gates.gate_one(ctx, f, {"head": (tmp_path / "old", "c1")})
    assert first["verdict"] == "passed" and len(scripts) == 2
    again = gates.gate_one(ctx, f, {"head": (tmp_path / "old", "c1")})
    assert again == first and len(scripts) == 2
    moved = gates.gate_one(ctx, f, {"head": (tmp_path / "new", "c2")})
    assert len(scripts) == 3 and "seq" not in scripts[2]
    assert moved["head"] == {"commit": "c2", "outcome": "passes"} and moved["verdict"] == "failed"
