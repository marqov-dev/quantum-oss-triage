"""agy ends its turn when a command is refused. The harness names the refused command
and asks again, instead of losing the model's view of the item."""

import json

from harness.adapters.antigravity import AntigravityAdapter, refused_action
from harness.adapters.base import Adapter, Invocation, Parsed
from harness.adapters.sandbox import AGY_SETTINGS
from tests.test_schemas import GOOD_REVIEW

DENIED = {"status": "SUCCESS", "response": "", "conversation_id": "c1",
          "denied_actions": [{"action": "command", "display_name": "RunCommand"}]}


def _transcript(home, cid, steps):
    d = home / ".gemini/antigravity-cli/brain" / cid / ".system_generated/logs"
    d.mkdir(parents=True)
    (d / "transcript.jsonl").write_text("\n".join(json.dumps(s) for s in steps) + "\n")


def test_refused_command_read_from_the_transcript(tmp_path):
    _transcript(tmp_path, "c1", [{"type": "USER_INPUT", "status": "DONE"},
                                 {"type": "GENERIC", "status": "ERROR",
                                  "error": 'permission check failed for unsandboxed "nl -ba a.py | sed -n \'4,9p\'": '
                                           "user denied permission to run command: ..."}])
    assert refused_action(tmp_path, "c1") == "nl -ba a.py | sed -n '4,9p'"


def test_refused_call_with_no_error_step_uses_the_last_tool_call(tmp_path):
    _transcript(tmp_path, "c2", [{"type": "PLANNER_RESPONSE", "status": "DONE", "tool_calls": [
        {"name": "run_command", "args": {"CommandLine": '"find . | xargs grep -n x"'}}]}])
    assert refused_action(tmp_path, "c2") == "find . | xargs grep -n x"
    assert refused_action(tmp_path, "missing") is None


def test_parse_asks_again_naming_the_command(tmp_path):
    _transcript(tmp_path, "c1", [{"type": "GENERIC", "status": "ERROR",
                                  "error": 'permission check failed for unsandboxed "which uv": user denied'}])
    a = AntigravityAdapter()
    a.sandbox.home = tmp_path
    p = a.parse(Invocation(0, json.dumps(DENIED), "", False, 1.0))
    assert p.data is None and not p.failed_call
    assert "`which uv`" in p.retry_note and "head -n" in p.retry_note


def test_schema_file_is_readable_and_line_ranges_are_explained():
    allow = json.loads(AGY_SETTINGS)["permissions"]["allow"]
    assert "read_file(/out/schema.json)" in allow
    assert {"command(cut)", "command(tr)"} <= set(allow)
    # These can run other commands, which would get round the allow-list.
    assert not {"command(sed)", "command(xargs)", "command(awk)"} & set(allow)


class Refusing(Adapter):
    name = "refusing"

    def __init__(self, refusals):
        super().__init__()
        self.refusals, self.prompts = refusals, []

    def available(self):
        return True, ""

    def build_command(self, prompt, system, schema_name, cwd, out_file):
        self.prompts.append(prompt)
        return ["x"]

    def _invoke(self, cmd, cwd, timeout_s, out_file):
        return Invocation(0, "", "", False, 0.1, None)

    def parse(self, inv):
        if len(self.prompts) <= self.refusals:
            return Parsed(None, "m", {}, "agy refused a command outside the allow-list",
                          retry_note=f"refused #{len(self.prompts)}")
        return Parsed(GOOD_REVIEW, "m", {}, None)


def test_refusals_are_retried_with_the_note(tmp_path):
    a = Refusing(2)
    r = a.run("P", "S", "review-output", tmp_path)
    assert r.ok and r.attempts == 3
    assert "refused #1" in a.prompts[1] and "refused #2" in a.prompts[2] and "refused #1" not in a.prompts[2]


def test_refusals_stop_after_two_retries(tmp_path):
    r = Refusing(5).run("P", "S", "review-output", tmp_path)
    assert not r.ok and "allow-list" in r.error and r.attempts == 3
