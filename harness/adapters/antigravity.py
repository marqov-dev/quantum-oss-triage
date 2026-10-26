"""Google Antigravity CLI (agy) adapter.

agy -p "<prompt>" --output-format json --mode plan --sandbox --print-timeout 20m,
always inside a hard process timeout: print mode has a reported headless hang
(issue #318, closed in September 2026 and reported again since).

The flags come from a third-party reference and were not checked against a real
install (agy was not installed when this was written). Confirm with `agy --help`
and run `qot doctor` before trusting it.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.adapters.base import Adapter, Invocation, Parsed, extract_json
from harness.controller import cleanenv
from harness.controller import schema as schemas

HARD_TIMEOUT_S = 25 * 60


class AntigravityAdapter(Adapter):
    name = "antigravity"
    binary = "agy"
    max_timeout_s = HARD_TIMEOUT_S
    runs_shell_on_host = True

    def env(self) -> dict[str, str]:
        return cleanenv.base_env(cleanenv.binary_dir(self.binary))

    def build_command(self, prompt: str, system: str, schema_name: str, cwd: Path, out_file: Path) -> list[str]:
        # No documented schema flag: the schema travels in the prompt and the
        # harness validates the reply.
        schema_text = json.dumps(schemas.load(schema_name))
        full = f"{system}\n\n{prompt}\n\nReturn only a JSON object matching this JSON Schema:\n{schema_text}"
        cmd = [self.resolved_binary() or self.binary, "-p", full, "--output-format", "json",
               "--mode", "plan", "--sandbox", "--print-timeout", "20m"]
        if self.model:
            cmd += ["--model", self.model]
        return cmd + self.extra_args

    def parse(self, inv: Invocation) -> Parsed:
        try:
            doc = json.loads(inv.stdout)
        except json.JSONDecodeError:
            data = extract_json(inv.stdout)
            return Parsed(data, self.model, {}, None if data else "stdout was not JSON",
                          failed_call=data is None and inv.exit_code not in (0, None))
        if not isinstance(doc, dict):
            return Parsed(None, self.model, {}, "unexpected JSON shape")
        tokens: dict = {"input": 0, "output": 0, "cache_read": 0}
        model_id = self.model
        stats = (doc.get("stats") or {}).get("models") or {}
        for name, m in stats.items():
            t = (m or {}).get("tokens") or {}
            tokens["input"] += t.get("prompt", 0)
            tokens["output"] += t.get("candidates", 0)
            tokens["cache_read"] += t.get("cached", 0)
            model_id = name
        if doc.get("error"):
            return Parsed(None, model_id, tokens, json.dumps(doc["error"])[:500], failed_call=True)
        text = next((doc[k] for k in ("response", "result", "output", "text") if isinstance(doc.get(k), str)), None)
        data = extract_json(text) if text is not None else (doc if "findings" in doc or "verdict" in doc else None)
        return Parsed(data, model_id, tokens, None if data else "no JSON in response")
