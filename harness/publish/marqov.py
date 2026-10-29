"""Marqov publisher: Workspaces and Reports in two separately configured targets.

- **Per-repository target** (`publish.marqov.repos`): a Workspace
  "<org>/<repo>: run record" and a Report "<org>/<repo>: review" per
  repository. These can carry security rows, so they never go to the hub
  Project: the publisher refuses a configuration where a repository's Project
  is the hub Project. One Project for all repositories, or one per
  repository (`per_repo`).
- **Hub target** (`publish.marqov.hub`): the Reports "Round one: overview"
  and, when asked for, "Round one: public summary", counts only. The hub
  Project may be visible to a wider collaborators team.

Each target has its own Project id and API key file. Nothing is hardcoded; a
live run refuses to start until every target it needs is configured. Every
document is one markdown block.

Local files are always written. Uploading needs an explicit `--live`; without it
the publisher prints what it would create or update and never reads a key.
Key files live outside the repository (by default ~/.config/marqov/api-key),
are read only by `read_key()` below in live mode, and are never written
anywhere.

Every document passes the sensitive-content check on the exact text being
uploaded, immediately before upload, even though the caller has already
checked it. A document that fails is not uploaded.

The publisher only touches documents it created (recorded in
outbox/marqov-published.json) or, if that record is lost, an active document
of the same type with exactly the same title. It never edits a document that
was changed in the web app since its last upload, never archives or deletes,
and refuses the protected documents below outright.

Known platform limitation: sealing a Project returns 409 while it has more
than one active Workspace (marqov-platform #2971, interim guard), so a shared
per-repository Project cannot be sealed once it holds more than one
repository's run record.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from harness import secrets
from harness.paths import REPO_ROOT
from harness.publish import redact

HUB_PROJECT = "Quantum open-source review, round one (2026)"
API_KEY_PATH = Path.home() / ".config" / "marqov" / "api-key"
DEFAULT_BASE_URL = "https://app.marqov.ai"
# The real Project and document ids live outside this (public) repository, in
# this file, which is laid over publish.marqov from config/harness.yaml.
LOCAL_TARGETS_PATH = Path.home() / ".config" / "quantum-oss-triage" / "marqov-targets.yaml"
OVERVIEW_TITLE = "Round one: overview"
PUBLIC_SUMMARY_TITLE = "Round one: public summary"
_IDEMPOTENCY_NS = uuid.UUID("6f1d7c2e-3a8b-4c55-9d0e-2b7a51e4c9a1")


def workspace_document(manifest: dict, scan_summary: dict) -> dict:
    """The run-record Workspace: redacted manifest, commands, scanner summary, stage status."""
    redacted_scans = {k: {"status": v["status"], "version": v.get("version"),
                          "note": v.get("note", "") if v["status"] in ("ok", "not_applicable", "unavailable") else "",
                          "counts": {hk: hv for hk, hv in (v.get("hygiene") or {}).items() if not isinstance(hv, (list, dict))}}
                      for k, v in scan_summary.items()}
    return {
        "title": f"{manifest['repo']['name']}: run record",
        "blocks": [
            {"type": "markdown", "text": f"Commit `{manifest['repo']['commit']}`, run `{manifest['run_id']}`, "
                                         f"harness `{manifest['harness_revision']}`. Status: {manifest['status']}."},
            {"type": "script", "language": "bash",
             "text": f"qot run --repo {manifest['repo']['name']} --run-dir runs/{manifest['run_id']}"},
            {"type": "json", "name": "adapters", "data": manifest["adapters"]},
            {"type": "json", "name": "scanners", "data": redacted_scans},
            {"type": "json", "name": "stages", "data": manifest["stages"]},
            {"type": "json", "name": "tokens", "data": manifest["tokens"]},
            {"type": "json", "name": "completion", "data": {
                "reviewed": manifest["coverage"]["reviewed"], "not_reviewed": manifest["coverage"]["not_reviewed"],
                "incomplete_checks": manifest["coverage"]["incomplete_checks"]}},
        ],
    }


def write_local(outbox: Path, slug: str, workspace: dict, report: dict, report_md: str, report_html: str) -> Path:
    d = Path(outbox) / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspace.json").write_text(json.dumps({"project": HUB_PROJECT, **workspace}, indent=2))
    (d / "report.json").write_text(json.dumps({"project": HUB_PROJECT, **report}, indent=2))
    (d / "report.md").write_text(report_md)
    (d / "report.html").write_text(report_html)
    return d


# --- markdown for the platform's markdown blocks -----------------------------

def workspace_markdown(ws: dict) -> str:
    out = [f"# {ws['title']}", ""]
    for b in ws["blocks"]:
        if b["type"] == "markdown":
            out += [b["text"], ""]
        elif b["type"] == "script":
            out += ["Rerun:", "", f"```{b.get('language', '')}", b["text"], "```", ""]
        else:
            out += [f"## {b['name'].capitalize()}", "", "```json", json.dumps(b["data"], indent=2), "```", ""]
    return "\n".join(out)


# Security and advisory counts per repository stay off the hub (which a wider
# collaborators team can see) unless publish.marqov.hub.show_security_counts
# is true: a count next to a repository name says it has a vulnerability
# before the maintainers have been told.
SECURITY_COLUMNS = (("Security", "security_vulnerability"), ("Advisories", "dependency_advisory"))
OTHER_COLUMNS = (("Correctness", "correctness"), ("Docs, tests, maintenance", "docs_tests_maintenance"))
SECURITY_WITHHELD = "Security findings and dependency advisories are not shown per repository here."


def _count_columns(show_security: bool):
    return (SECURITY_COLUMNS if show_security else ()) + OTHER_COLUMNS


def _table(head: list[str], rows: list[list[str]], empty: str) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows] or ["| " + " | ".join([empty] + [""] * (len(head) - 1)) + " |"]
    return out


def overview_markdown(reports: list[dict], not_published: list[str], show_security: bool = False) -> str:
    cols = _count_columns(show_security)
    out = [f"# {OVERVIEW_TITLE}", "",
           "One Workspace (run record) and one Report (review) per repository. Counts are findings accepted "
           "after a person checked them; security findings appear only as counts until disclosed."
           + ("" if show_security else " " + SECURITY_WITHHELD), ""]
    rows = []
    for r in reports:
        h, c = r["header"], r["scorecard"]["counts"]
        rows.append([h["repository"], f"`{h['commit'][:12]}`", h["review_date"], h["completion"]]
                    + [str(c.get(k, 0)) for _, k in cols])
    out += _table(["Repository", "Commit", "Reviewed", "Completion"] + [n for n, _ in cols], rows, "(none yet)")
    if not_published:
        out += ["", "Not yet published (waiting for triage or blocked by the sensitive-content check): "
                + ", ".join(not_published) + "."]
    out += ["", "Method: https://github.com/marqov-dev/quantum-oss-triage", ""]
    return "\n".join(out)


def public_summary_markdown(summary: dict, show_security: bool = False) -> str:
    cols = _count_columns(show_security)
    out = [f"# {PUBLIC_SUMMARY_TITLE}", "",
           f"Counts are {summary['basis']}." + ("" if show_security else " " + SECURITY_WITHHELD), ""]
    rows = [[p["repository"], f"`{p['commit'][:12]}`", p["completion"]] + [str(p["counts"].get(k, 0)) for _, k in cols]
            for p in summary["projects"]]
    out += _table(["Repository", "Commit", "Completion"] + [n for n, _ in cols], rows, "(none yet)")
    return "\n".join(out) + "\n"


# --- planned documents ---------------------------------------------------------

@dataclass
class PlannedDoc:
    key: str               # stable identity within the hub Project, e.g. "org/repo:report"
    document_type: str     # "workspace" or "report"
    title: str
    content: str
    sensitive: list = field(default_factory=list)  # findings whose details must not appear
    share: bool = False    # list it among the share links David creates in the web app
    target: str = "repo"   # "repo" (per-repository Project) or "hub" (counts only)
    repo: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()

    def gate(self) -> list[str]:
        return redact.check(self.content, self.sensitive)


def idempotency_key(project_id: str, doc: PlannedDoc) -> str:
    return str(uuid.uuid5(_IDEMPOTENCY_NS, f"{project_id}\n{doc.document_type}\n{doc.key}\n{doc.title}"))


@dataclass
class Target:
    project_id: str | None
    key_path: Path


@dataclass
class Targets:
    base_url: str
    hub: Target
    repos: Target
    per_repo: dict = field(default_factory=dict)       # repository name -> Project id
    protected: dict = field(default_factory=dict)      # document id -> why
    retired: list = field(default_factory=list)        # Project ids (or id prefixes) never to publish to
    show_security_counts: bool = False                 # per-repository security counts on the hub
    # Per-repository documents may share the hub Project only when this is set
    # (repos.allow_hub), and then only while the hub's team has one member.
    allow_repos_in_hub: bool = False
    # The API key cannot list team members, so a person states it instead:
    # hub.single_member_confirmed, e.g. "2026-10-29 David Ryan, checked in the web app".
    single_member_confirmed: str | None = None

    @classmethod
    def from_settings(cls, m: dict | None) -> "Targets":
        m = m or {}

        def target(d):
            d = d or {}
            return Target(d.get("project_id") or None, Path(d.get("key_path") or API_KEY_PATH).expanduser())

        repos = m.get("repos") or {}
        return cls(m.get("base_url") or DEFAULT_BASE_URL, target(m.get("hub")), target(repos),
                   dict(repos.get("per_repo") or {}), dict(m.get("protected_documents") or {}),
                   [str(x) for x in m.get("retired_projects") or []],
                   bool((m.get("hub") or {}).get("show_security_counts", False)),
                   repos.get("allow_hub") is True,
                   (m.get("hub") or {}).get("single_member_confirmed") or None)

    def target_for(self, doc: PlannedDoc) -> Target:
        if doc.target == "hub":
            return self.hub
        return Target(self.per_repo.get(doc.repo) or self.repos.project_id, self.repos.key_path)

    def repo_in_hub(self, doc: PlannedDoc) -> bool:
        return doc.target == "repo" and bool(self.hub.project_id) and self.target_for(doc).project_id == self.hub.project_id

    def problems(self, docs: list[PlannedDoc]) -> list[str]:
        """Why a live run must not start. Empty means every needed target is set and safe."""
        out = []
        for doc in docs:
            t = self.target_for(doc)
            where = "publish.marqov.hub.project_id" if doc.target == "hub" else (
                f"publish.marqov.repos.per_repo[{doc.repo!r}] or publish.marqov.repos.project_id")
            if not t.project_id:
                out.append(f"{doc.title}: no Project configured ({where})")
            elif any(t.project_id.startswith(r) for r in self.retired):
                out.append(f"{doc.title}: Project {t.project_id} is retired (publish.marqov.retired_projects)")
            elif doc.target == "repo" and self.repo_in_hub(doc) and not self.allow_repos_in_hub:
                out.append(f"{doc.title}: per-repository documents must not go to the hub Project {t.project_id} "
                           "(set publish.marqov.repos.allow_hub only if the hub's team is you alone)")
            if _within(t.key_path, REPO_ROOT):
                out.append(f"{doc.title}: key file {t.key_path} is inside the repository")
        return sorted(set(out))


def merge_settings(base: dict | None, local: dict | None) -> dict:
    """publish.marqov from the repository with the local targets file laid over it."""
    out = dict(base or {})
    for k, v in (local or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge_settings(out[k], v)
        elif isinstance(v, list) and isinstance(out.get(k), list):
            out[k] = out[k] + [x for x in v if x not in out[k]]
        else:
            out[k] = v
    return out


def _within(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def plan_summary(docs: list[PlannedDoc], record: dict, targets: Targets | None = None) -> list[dict]:
    out = []
    for d in docs:
        project = targets.target_for(d).project_id if targets else None
        rec = record.get(d.key) if record.get(d.key, {}).get("project") in (None, project) else None
        out.append({"key": d.key, "type": d.document_type, "title": d.title, "target": d.target,
                    "project": project or "NOT CONFIGURED", "bytes": len(d.content.encode()),
                    "sha256": d.sha256[:12], "gate": d.gate() or "passed",
                    "action": ("unchanged" if (rec or {}).get("content_sha256") == d.sha256
                               else "update" if rec else "create or adopt by exact title")})
    return out


# --- live client ---------------------------------------------------------------

class ApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def read_key(path: Path | None = None) -> str:
    path = Path(path or API_KEY_PATH)
    if not path.is_file():
        raise FileNotFoundError(f"no Marqov API key at {path}")
    key = path.read_text().strip()
    if not key:
        raise ValueError(f"{path} is empty")
    return key


class MarqovClient:
    """The few Project endpoints the publisher needs (marqov-platform #2943, #2971)."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, key: str | None = None, opener=None, sleep=time.sleep,
                 key_path: Path | None = None):
        self.base = base_url.rstrip("/")
        self._key = key if key is not None else read_key(key_path)
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def _req(self, method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        h = {"Authorization": f"Bearer {self._key}", "Accept": "application/json", **(headers or {})}
        if data is not None:
            h["Content-Type"] = "application/json"
        for attempt in range(4):
            req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
            try:
                with self._open(req, timeout=60) as resp:
                    text = resp.read().decode() or "{}"
                    return json.loads(text)
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")[:500]
                if e.code in (429, 502, 503, 504) and attempt < 3:
                    self._sleep(min(float(e.headers.get("Retry-After") or 2 ** attempt), 30))
                    continue
                # Never let a response echo anything key-like into a log.
                raise ApiError(e.code, secrets.redact(text)) from None
        raise ApiError(0, "retries exhausted")

    def team_member_count(self) -> int | None:
        """Members of the key's team, or None when the API does not let a key see them.

        Read-only. On platform main, GET /api/team/members answers an API key
        with 403 api_key_not_supported ("Team governance routes require a user
        session"); no other route lists members to a key.
        """
        try:
            return len(self._req("GET", "/api/team/members").get("members", []))
        except ApiError as e:
            if e.status in (401, 403, 404):
                return None
            raise

    def list_documents(self, project: str, document_type: str, title: str) -> list[dict]:
        q = urllib.parse.urlencode({"type": document_type, "q": title, "limit": 100})
        return self._req("GET", f"/api/projects/{project}/documents?{q}").get("documents", [])

    def create_document(self, project: str, document_type: str, title: str, idem: str) -> dict:
        return self._req("POST", f"/api/projects/{project}/documents", {"document_type": document_type, "title": title},
                         {"Idempotency-Key": idem})["document"]

    def get_document(self, project: str, doc_id: str) -> dict:
        return self._req("GET", f"/api/projects/{project}/documents/{doc_id}")

    def patch_block(self, project: str, block_id: str, content: str) -> dict:
        return self._req("PATCH", f"/api/projects/{project}/blocks/{block_id}", {"content": content})

    def create_block(self, project: str, doc_id: str, content: str) -> dict:
        return self._req("POST", f"/api/projects/{project}/blocks",
                         {"document_id": doc_id, "block_type": "markdown", "content": content, "position": 0})


def doc_url(base: str, project: str, doc_type: str, doc_id: str) -> str:
    return f"{base.rstrip('/')}/projects/{project}/{'reports' if doc_type == 'report' else 'workspaces'}/{doc_id}"


def load_record(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2))
    tmp.replace(path)


def _membership_problems(docs: list[PlannedDoc], targets: Targets, client_for, clients: dict) -> list[str]:
    """Per-repository documents in the hub only while its team is one person."""
    if not any(targets.repo_in_hub(d) for d in docs):
        return []
    kp = targets.hub.key_path
    clients.setdefault(kp, client_for(kp))
    try:
        n = clients[kp].team_member_count()
    except ApiError as e:
        return [f"team membership check failed ({e}); not uploading per-repository documents to the hub"]
    if n is not None and n > 1:
        return [f"the hub's team has {n} members; per-repository documents (which can carry security rows) "
                "go to the hub only while you are its only member"]
    if n is None and not targets.single_member_confirmed:
        return ["the API key cannot list team members (GET /api/team/members needs a user session), so the "
                "single-member condition cannot be checked; check it in the web app and record it as "
                "publish.marqov.hub.single_member_confirmed in the local targets file"]
    return []


def publish_live(docs: list[PlannedDoc], targets: Targets, client_for, record_path: Path) -> list[dict]:
    """Upload each document to its target. `client_for(key_path)` returns a MarqovClient.

    The caller must have checked `targets.problems(docs)` first; this checks again.
    """
    problems = targets.problems(docs)
    if problems:
        return [{"key": d.key, "title": d.title, "type": d.document_type, "status": "blocked",
                 "problems": problems} for d in docs]
    clients: dict = {}
    blocked = _membership_problems(docs, targets, client_for, clients)
    if blocked:
        return [{"key": d.key, "title": d.title, "type": d.document_type, "status": "blocked",
                 "problems": blocked} for d in docs]
    record = load_record(record_path)
    results = []
    for doc in docs:
        t = targets.target_for(doc)
        project = t.project_id
        res = {"key": doc.key, "title": doc.title, "type": doc.document_type, "target": doc.target, "project": project}
        problems = doc.gate()  # the hard gate, on exactly what would be uploaded
        if problems:
            results.append({**res, "status": "blocked", "problems": problems})
            continue
        if t.key_path not in clients:
            clients[t.key_path] = client_for(t.key_path)
        client = clients[t.key_path]
        rec = record.get(doc.key)
        if rec and rec.get("project") not in (None, project):
            rec = None  # recorded in another Project: this target starts fresh
        try:
            res.update(_publish_one(doc, client, project, rec, targets.protected))
        except ApiError as e:
            res.update(status="failed", error=str(e))
        if res.get("document_id"):
            entry = {"document_id": res["document_id"], "project": project, "target": doc.target,
                     "type": doc.document_type, "title": doc.title,
                     "url": doc_url(client.base, project, doc.document_type, res["document_id"]), "share": doc.share}
            if res["status"] in ("created", "updated", "unchanged"):
                entry["content_sha256"] = doc.sha256
            elif rec and "content_sha256" in rec:
                entry["content_sha256"] = rec["content_sha256"]
            record[doc.key] = entry
            _save_record(record_path, record)
            res["url"] = entry["url"]
        results.append(res)
    return results


def _publish_one(doc: PlannedDoc, client: MarqovClient, project: str, rec: dict | None, protected: dict) -> dict:
    doc_id, adopted = None, False
    if rec:
        doc_id = rec["document_id"]
    else:
        same = [d for d in client.list_documents(project, doc.document_type, doc.title)
                if d.get("title") == doc.title and not d.get("archived_at")]
        if len(same) > 1:
            return {"status": "blocked", "problems": [f"{len(same)} active documents are titled {doc.title!r}"]}
        if same:
            doc_id, adopted = same[0]["id"], True
    if doc_id in protected:
        return {"status": "blocked", "problems": [f"{doc_id} is protected ({protected[doc_id]})"]}
    if doc_id is None:
        created = client.create_document(project, doc.document_type, doc.title, idempotency_key(project, doc))
        doc_id = created["id"]
        if doc_id in protected:  # cannot happen; refuse rather than write
            return {"status": "blocked", "problems": [f"{doc_id} is protected"]}
    full = client.get_document(project, doc_id)
    meta, blocks = full.get("document") or {}, full.get("blocks") or []
    if meta.get("archived_at"):
        return {"status": "skipped", "document_id": doc_id, "reason": "archived in the web app; not republished"}
    if meta.get("document_type") and meta["document_type"] != doc.document_type:
        return {"status": "blocked", "problems": [f"{doc_id} is a {meta['document_type']}, not a {doc.document_type}"]}
    if not blocks:
        client.create_block(project, doc_id, doc.content)
        return {"status": "created", "document_id": doc_id}
    if len(blocks) != 1 or blocks[0].get("block_type") != "markdown":
        return {"status": "skipped", "document_id": doc_id,
                "reason": f"has {len(blocks)} blocks (edited in the web app); not overwritten"}
    current = blocks[0].get("content") or ""
    if current == doc.content:
        return {"status": "unchanged", "document_id": doc_id}
    last = (rec or {}).get("content_sha256")
    ours = current == "" or (last is not None and hashlib.sha256(current.encode()).hexdigest() == last)
    if not ours:
        why = "adopted by title, and its content is not ours" if adopted else "edited in the web app since the last upload"
        return {"status": "skipped", "document_id": doc_id, "reason": f"{why}; not overwritten"}
    client.patch_block(project, blocks[0]["id"], doc.content)
    return {"status": "updated" if current else "created", "document_id": doc_id}


def share_link_todo(record: dict) -> list[str]:
    return [f"{e['title']}: {e['url']}" for e in record.values() if e.get("share")]
