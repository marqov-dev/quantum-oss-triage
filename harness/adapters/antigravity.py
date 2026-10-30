"""Google Antigravity CLI (agy) adapter.

agy -p "<prompt>" --output-format json --json-schema <file> --mode plan
--sandbox --disable-slash-commands --print-timeout 20m, always inside a hard
process timeout: print mode has a reported headless hang (issue #318, closed in
September 2026 and reported again since).

Flags checked against `agy --help` for agy 1.4.7. agy reads files with shell
commands, so it runs in a reviewer sandbox (harness/adapters/sandbox.py) by
default, with a harness-owned home: the operator's ~/.gemini (user settings,
permission rules, MCP servers, plugins) is never visible to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.adapters.base import Adapter, Invocation, Parsed, extract_json, model_schema
from harness.adapters.sandbox import ReviewerSandbox
from harness.controller import cleanenv

HARD_TIMEOUT_S = 25 * 60


class AntigravityAdapter(Adapter):
    name = "antigravity"
    binary = "agy"
    max_timeout_s = HARD_TIMEOUT_S
    reads_with_shell = True

    def __init__(self, model=None, binary=None, extra_args=None, sandbox: bool | dict = True, effort=None):
        # agy has no effort flag: the level is part of the model name (gemini-3.8-flash-medium).
        if effort:
            raise ValueError("antigravity: put the effort level in the model name, e.g. gemini-3.8-flash-medium")
        super().__init__(model, binary, extra_args)
        if sandbox:
            self.sandbox = ReviewerSandbox("agy", **(sandbox if isinstance(sandbox, dict) else {}))

    def env(self) -> dict[str, str]:
        if self.sandbox is not None:
            return cleanenv.base_env()  # for the docker client; the container gets its own
        return cleanenv.base_env(cleanenv.binary_dir(self.binary))

    def build_command(self, prompt: str, system: str, schema_name: str, cwd: Path, out_file: Path) -> list[str]:
        # No system-prompt flag: the harness text leads the prompt.
        schema_file = out_file.parent / "schema.json"
        schema_file.write_text(json.dumps(model_schema(schema_name)))
        cmd = [self.resolved_binary() or self.binary, "-p", f"{system}\n\n{prompt}", "--output-format", "json",
               "--json-schema", str(schema_file), "--mode", "plan", "--sandbox", "--disable-slash-commands",
               "--print-timeout", "20m"]
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
        model_id = doc.get("model") or self.model
        usage = doc.get("usage") or {}
        if usage:
            tokens["input"] = usage.get("input_tokens", 0)
            tokens["output"] = usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)
            tokens["cache_read"] = usage.get("cache_read_tokens", 0)
        # Older builds reported per-model stats instead.
        for name, m in ((doc.get("stats") or {}).get("models") or {}).items():
            t = (m or {}).get("tokens") or {}
            tokens["input"] += t.get("prompt", 0)
            tokens["output"] += t.get("candidates", 0)
            tokens["cache_read"] += t.get("cached", 0)
            model_id = name
        if doc.get("error") or doc.get("status") == "ERROR":
            return Parsed(None, model_id, tokens, json.dumps(doc.get("error") or doc.get("status"))[:500],
                          failed_call=True)
        payload = doc.get("structured_output")
        if isinstance(payload, dict):
            return Parsed(payload, model_id or "agy-default", tokens, None)
        text = next((doc[k] for k in ("response", "result", "output", "text") if isinstance(doc.get(k), str)), None)
        data = extract_json(text) if text is not None else (doc if "findings" in doc or "verdict" in doc else None)
        return Parsed(data, model_id or "agy-default", tokens, None if data else "no JSON in response")
