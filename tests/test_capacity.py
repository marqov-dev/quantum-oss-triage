"""A provider at capacity is retried with backoff; a usage limit is not."""

import json
from pathlib import Path

from harness.adapters.base import Adapter, Invocation, Parsed
from tests.test_schemas import GOOD_REVIEW

BUSY = "Selected model is at capacity. Please try a different model."


class Scripted(Adapter):
    name = "scripted"

    def __init__(self, errors):
        super().__init__()
        self.errors, self.slept = list(errors), []
        self.sleep = self.slept.append

    def available(self):
        return True, "scripted"

    def version(self):
        return "scripted 1"

    def build_command(self, prompt, system, schema_name, cwd, out_file):
        return ["scripted"]

    def _invoke(self, cmd, cwd, timeout_s, out_file):
        err = self.errors.pop(0) if self.errors else ""
        return Invocation(1 if err else 0, "" if err else json.dumps(GOOD_REVIEW), err, False, 0.1, None)

    def parse(self, inv):
        if inv.exit_code:
            return Parsed(None, None, {}, inv.stderr, failed_call=True)
        return Parsed(json.loads(inv.stdout), "m-1", {}, None)


def adapter(*errors):
    return Scripted(errors)


def test_capacity_refusal_is_retried_after_backoff(tmp_path):
    a = adapter(BUSY, BUSY)
    r = a.run("p", "s", "review-output", Path(tmp_path))
    assert r.ok and r.capacity_retries == 2 and a.slept == [30, 120]


def test_capacity_refusal_gives_up_after_the_last_backoff(tmp_path):
    a = adapter(*[BUSY] * 10)
    r = a.run("p", "s", "review-output", Path(tmp_path))
    assert not r.ok and r.capacity_refused and not r.usage_limited and a.slept == [30, 120, 300]


def test_usage_limit_is_not_retried(tmp_path):
    a = adapter("You have hit your usage limit; resets at 5pm.")
    r = a.run("p", "s", "review-output", Path(tmp_path))
    assert r.usage_limited and not r.capacity_refused and a.slept == []
