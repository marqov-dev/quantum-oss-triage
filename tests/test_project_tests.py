"""The project's own suite is recorded as ok only when it really ran."""

import pytest

from harness.scanners.project_tests import ProjectTests

P = ProjectTests()


@pytest.mark.parametrize("tail,exit_code,status,note", [
    ("===== 120 passed, 3 skipped in 4.10s =====", 0, "ok", ""),
    ("===== 2 failed, 118 passed in 4.10s =====", 1, "ok", ""),  # failing tests are a baseline
    ("!!! Interrupted: 55 errors during collection !!!\n55 errors in 5.32s", 2, "failed", "55 errors"),
    ("===== 3 failed, 90 passed, 2 errors in 9.0s =====", 1, "failed", "2 errors"),
    ("===== 1 error in 0.5s =====", 2, "failed", "1 errors"),
    ("no tests ran in 0.01s", 5, "failed", "no tests collected"),
    ("", 137, "failed", "could not read a pytest summary"),
])
def test_status(tail, exit_code, status, note):
    r = P.parse(tail, "", exit_code)
    assert r.status == status and note in r.note, (r.status, r.note)


def test_counts_and_output_are_kept():
    r = P.parse("FAILED tests/test_a.py::test_x\n===== 1 failed, 4 passed, 2 errors in 1s =====", "", 1)
    assert r.hygiene["errors"] == 2 and r.hygiene["failed"] == 1 and r.hygiene["passed"] == 4
    assert "test_a.py::test_x" in r.raw  # in the private evidence store, for the reviewer


def test_a_repository_can_give_its_suite_longer(tmp_path):
    from harness.controller.config import RepoSpec

    spec = RepoSpec.from_dict({"name": "o/r", "source": "x", "tests": {"timeout_s": 3600}})
    assert spec.tests_timeout_s == 3600 and RepoSpec.from_dict({"name": "o/r", "source": "x"}).tests_timeout_s is None
