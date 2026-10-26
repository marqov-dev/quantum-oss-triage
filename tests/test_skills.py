import pytest

from harness.controller import schema, skills


@pytest.mark.parametrize("name", skills.available())
def test_skill_parses_and_names_a_real_schema(name):
    s = skills.load(name)
    assert s.output_schema in schema.NAMES
    assert len(s.sha256) == 64


@pytest.mark.parametrize("name", skills.available())
def test_skill_treats_repository_as_untrusted(name):
    assert "untrusted data" in skills.load(name).body


def test_required_skills_exist():
    assert set(skills.REVIEW_SKILLS + ("verify-finding", "propose-fix", "verify-fix")) <= set(skills.available())


def test_quantum_checks_state_when_they_apply():
    body = skills.load("review-quantum").body
    assert body.count("*Applies") == 6
