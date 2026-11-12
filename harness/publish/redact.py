"""Automated check for sensitive content before anything is written for sharing.

It blocks: code locations, titles or claims of sensitive findings, secret-like
values, exploit wording and email addresses. It is a backstop; a person still
reads every public title and summary.

A person may approve an exact sentence that uses a listed word in its ordinary
sense (for example "payload" for an API message body). Approvals live in the
run directory's publish-approvals.yaml, one per repository and phrase, each with
who approved it and when. An approved phrase is exempt from the exploit-wording
check only; every other check still reads it, and the same word anywhere else
still blocks.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from harness import secrets

APPROVALS_FILE = "publish-approvals.yaml"

EXPLOIT_WORDING = re.compile(r"(?i)\b(exploit(?:able|ation)?|payload|proof[- ]of[- ]concept|\bPoC\b|remote code execution|\bRCE\b|arbitrary code|privilege escalation|bypass(?:es|ed)? (?:auth|the))\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Reserved for examples and testing (RFC 2606, RFC 6761): such an address
# belongs to no one, and tests that make git commits often use one.
RESERVED_DOMAIN = re.compile(r"(?i)@(?:(?:[a-z0-9-]+\.)*example\.(?:com|net|org)|(?:[a-z0-9-]+\.)+(?:example|invalid|test|localhost))$")


def load_approvals(run_dir: Path, repo: str) -> tuple[str, ...]:
    """The phrases a person approved for this repository's shared documents."""
    path = Path(run_dir) / APPROVALS_FILE
    if not path.is_file():
        return ()
    out = []
    for a in (yaml.safe_load(path.read_text()) or {}).get("approvals") or []:
        missing = [k for k in ("repo", "phrase", "approved_by", "approved_on") if not a.get(k)]
        if missing:
            raise ValueError(f"{path}: approval {a.get('phrase')!r} lacks {', '.join(missing)}")
        if a["repo"] == repo:
            out.append(str(a["phrase"]))
    return tuple(out)


def approved_used(text: str, approved_phrases: tuple[str, ...]) -> list[str]:
    return [p for p in approved_phrases if p in text]


def check(text: str, sensitive_findings: list[dict], allowed_emails: tuple[str, ...] = (),
          approved_phrases: tuple[str, ...] = ()) -> list[str]:
    problems = []
    for hit in secrets.find(text):
        problems.append(f"secret-like value: {hit[:6]}...")
    worded = text
    for phrase in approved_phrases:
        worded = worded.replace(phrase, " " * len(phrase))
    for m in EXPLOIT_WORDING.finditer(worded):
        problems.append(f"exploit wording: {m.group(0)!r}")
    for m in EMAIL.finditer(text):
        if m.group(0) not in allowed_emails and not RESERVED_DOMAIN.search(m.group(0)):
            problems.append(f"email address: {m.group(0)}")
    for f in sensitive_findings:
        for label, needle in (("title", f["title"]), ("claim", f["claim"][:60])):
            if needle and len(needle) > 3 and needle in text:
                problems.append(f"{f['id']}: sensitive {label} appears in shared output")
        # The same file may hold a separate, non-sensitive finding; the exact
        # location of the sensitive one must not appear.
        if re.search(rf"{re.escape(f['file'])}:{f['line_start']}\b", text):
            problems.append(f"{f['id']}: code location appears in shared output")
    return sorted(set(problems))
