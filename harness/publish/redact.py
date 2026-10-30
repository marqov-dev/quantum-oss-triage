"""Automated check for sensitive content before anything is written for sharing.

It blocks: code locations, titles or claims of sensitive findings, secret-like
values, exploit wording and email addresses. It is a backstop; a person still
reads every public title and summary.
"""

from __future__ import annotations

import re

from harness import secrets

EXPLOIT_WORDING = re.compile(r"(?i)\b(exploit(?:able|ation)?|payload|proof[- ]of[- ]concept|\bPoC\b|remote code execution|\bRCE\b|arbitrary code|privilege escalation|bypass(?:es|ed)? (?:auth|the))\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Reserved for examples and testing (RFC 2606, RFC 6761): such an address
# belongs to no one, and tests that make git commits often use one.
RESERVED_DOMAIN = re.compile(r"(?i)@(?:(?:[a-z0-9-]+\.)*example\.(?:com|net|org)|(?:[a-z0-9-]+\.)+(?:example|invalid|test|localhost))$")


def check(text: str, sensitive_findings: list[dict], allowed_emails: tuple[str, ...] = ()) -> list[str]:
    problems = []
    for hit in secrets.find(text):
        problems.append(f"secret-like value: {hit[:6]}...")
    for m in EXPLOIT_WORDING.finditer(text):
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
