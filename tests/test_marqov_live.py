"""Live Marqov publishing against an in-process fake of the Project API."""

import io
import json
import re
import urllib.error
import urllib.parse
import uuid

import pytest

from harness.publish import marqov
from harness.publish.marqov import MarqovClient, PlannedDoc, publish_live

PROJECT = "11111111-1111-4111-8111-111111111111"   # per-repository Project
HUB = "22222222-2222-4222-8222-222222222222"       # hub Project (collaborators can see it)
KEY = "mq_test_key_never_stored_0123456789"


class FakeAPI:
    """Documents start with one empty markdown block, as on the platform."""

    def __init__(self, fail_first_with: int | None = None, members: int | None = None):
        self.members = members  # None: the endpoint refuses API keys, as on platform main
        self.docs: dict[str, dict] = {}
        self.blocks: dict[str, dict] = {}
        self.idem: dict[str, tuple] = {}
        self.calls: list[tuple] = []
        self.fail_first_with = fail_first_with

    def add_doc(self, doc_type, title, content="", doc_id=None, project=PROJECT):
        doc_id = doc_id or str(uuid.uuid4())
        self.docs[doc_id] = {"id": doc_id, "document_type": doc_type, "title": title, "archived_at": None,
                             "project_id": project}
        bid = str(uuid.uuid4())
        self.blocks[bid] = {"id": bid, "document_id": doc_id, "block_type": "markdown", "content": content}
        return doc_id

    def __call__(self, req, timeout=0):
        assert req.get_header("Authorization") == f"Bearer {KEY}"
        body = json.loads(req.data) if req.data else None
        path = req.full_url.split("app.marqov.ai", 1)[1]
        self.calls.append((req.get_method(), path, body, req.get_header("Idempotency-key")))
        if self.fail_first_with:
            code, self.fail_first_with = self.fail_first_with, None
            raise urllib.error.HTTPError(req.full_url, code, "busy", {"Retry-After": "0"}, io.BytesIO(b"{}"))
        m = req.get_method()
        if m == "GET" and path == "/api/team/members":
            if self.members is None:
                raise urllib.error.HTTPError(req.full_url, 403, "api_key_not_supported", {},
                                             io.BytesIO(b'{"error": "api_key_not_supported"}'))
            return _resp({"members": [{"user_id": str(i)} for i in range(self.members)]})
        project = path.split("/")[3]
        if m == "GET" and re.fullmatch(r"/api/projects/[0-9a-f-]{36}/documents\?.*", path):
            q = dict(x.split("=", 1) for x in path.split("?", 1)[1].split("&"))
            title = urllib.parse.unquote_plus(q["q"]).lower()
            out = [d for d in self.docs.values() if d["document_type"] == q["type"] and title in d["title"].lower()
                   and not d["archived_at"] and d["project_id"] == project]
            return _resp({"documents": out, "total": len(out)})
        if m == "POST" and re.fullmatch(r"/api/projects/[0-9a-f-]{36}/documents", path):
            key = req.get_header("Idempotency-key")
            uuid.UUID(key)
            if key in self.idem:
                assert self.idem[key][0] == body, "same key, different body"
                return _resp({"document": self.docs[self.idem[key][1]]})
            doc_id = self.add_doc(body["document_type"], body["title"], project=project)
            self.idem[key] = (body, doc_id)
            return _resp({"document": self.docs[doc_id]})
        mm = re.fullmatch(r"/api/projects/[0-9a-f-]{36}/documents/([0-9a-f-]+)", path)
        if m == "GET" and mm:
            d = self.docs[mm.group(1)]
            assert d["project_id"] == project, "document read through another Project"
            return _resp({"document": d, "blocks": [b for b in self.blocks.values() if b["document_id"] == d["id"]]})
        mm = re.fullmatch(r"/api/projects/[0-9a-f-]{36}/blocks/([0-9a-f-]+)", path)
        if m == "PATCH" and mm:
            self.blocks[mm.group(1)]["content"] = body["content"]
            return _resp(self.blocks[mm.group(1)])
        if m == "POST" and re.fullmatch(r"/api/projects/[0-9a-f-]{36}/blocks", path):
            bid = str(uuid.uuid4())
            self.blocks[bid] = {"id": bid, "document_id": body["document_id"], "block_type": "markdown",
                                "content": body["content"]}
            return _resp(self.blocks[bid])
        raise AssertionError(f"unexpected {m} {path}")

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH", "PUT", "DELETE")]


class _resp(io.BytesIO):
    def __init__(self, obj):
        super().__init__(json.dumps(obj).encode())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False



def docs(text="All fine.", sensitive=None):
    return [PlannedDoc("org/repo:workspace", "workspace", "org/repo: run record", f"# run\n{text}\n", sensitive or [],
                       repo="org/repo"),
            PlannedDoc("org/repo:report", "report", "org/repo: review", f"# review\n{text}\n", sensitive or [],
                       share=True, repo="org/repo")]


def client(api):
    return MarqovClient("https://app.marqov.ai", key=KEY, opener=api, sleep=lambda s: None)


def targets(tmp_path, repo_project=PROJECT, hub=HUB, **extra):
    return marqov.Targets.from_settings({"hub": {"project_id": hub, "key_path": str(tmp_path / "hub-key")},
                                         "repos": {"project_id": repo_project, "key_path": str(tmp_path / "key"),
                                                   **extra}})


PARTNER_OVERVIEW = "55555555-5555-4555-8555-555555555555"


def live(docs_, api, rec, tmp_path, **kw):
    t = targets(tmp_path, **kw)
    t.protected[PARTNER_OVERVIEW] = "hand-written overview for partners"
    return publish_live(docs_, t, lambda kp: client(api), rec)


def test_creates_fills_and_records(tmp_path):
    api = FakeAPI()
    rec = tmp_path / "marqov-published.json"
    out = live(docs(), api, rec, tmp_path)
    assert [r["status"] for r in out] == ["created", "created"]
    created = [c for c in api.calls if c[0] == "POST" and c[1].endswith("/documents")]
    assert [c[2]["document_type"] for c in created] == ["workspace", "report"] and all(c[3] for c in created)
    # The empty block the platform creates is filled in place, not added to.
    assert [b["content"] for b in api.blocks.values()] == ["# run\nAll fine.\n", "# review\nAll fine.\n"]
    record = json.loads(rec.read_text())
    assert record["org/repo:report"]["url"].endswith(f"/projects/{PROJECT}/reports/{out[1]['document_id']}")
    assert marqov.share_link_todo(record) == [f"org/repo: review: {record['org/repo:report']['url']}"]
    assert KEY not in rec.read_text() + json.dumps(out)


def test_rerun_is_unchanged_and_update_patches(tmp_path):
    api, rec = FakeAPI(), tmp_path / "r.json"
    live(docs(), api, rec, tmp_path)
    n = len(api.writes())
    assert [r["status"] for r in live(docs(), api, rec, tmp_path)] == ["unchanged", "unchanged"]
    assert len(api.writes()) == n
    out = live(docs("One finding."), api, rec, tmp_path)
    assert [r["status"] for r in out] == ["updated", "updated"] and len(api.docs) == 2


def test_lost_record_adopts_by_exact_title_and_keeps_web_edits(tmp_path):
    api = FakeAPI()
    api.add_doc("report", "org/repo: review (old draft)", "someone else's")
    edited = api.add_doc("report", "org/repo: review", "edited by hand in the web app")
    out = live(docs()[1:], api, tmp_path / "r.json", tmp_path)
    assert out[0]["status"] == "skipped" and out[0]["document_id"] == edited
    assert "not overwritten" in out[0]["reason"]
    assert api.blocks and all(b["content"] != "# review\nAll fine.\n" for b in api.blocks.values())


def test_edit_in_web_app_after_upload_is_not_overwritten(tmp_path):
    api, rec = FakeAPI(), tmp_path / "r.json"
    live(docs(), api, rec, tmp_path)
    for b in api.blocks.values():
        b["content"] += "\nA note added by a person."
    out = live(docs("Changed."), api, rec, tmp_path)
    assert [r["status"] for r in out] == ["skipped", "skipped"]


def test_protected_partner_overview_is_never_touched(tmp_path):
    api, rec = FakeAPI(), tmp_path / "r.json"
    protected = PARTNER_OVERVIEW
    api.add_doc("report", "org/repo: review", "x", doc_id=protected)
    rec.write_text(json.dumps({"org/repo:report": {"document_id": protected, "content_sha256": "0"}}))
    out = live(docs()[1:], api, rec, tmp_path)
    assert out[0]["status"] == "blocked" and api.writes() == []


def test_sensitive_gate_runs_before_any_request(tmp_path):
    api = FakeAPI()
    leak = {"id": "QOT-1", "title": "Token written to the log", "claim": "submit logs the bearer token",
            "file": "q/client.py", "line_start": 7}
    out = live(docs("See q/client.py:7 for the Token written to the log.", [leak]), api, tmp_path / "r.json", tmp_path)
    assert {r["status"] for r in out} == {"blocked"} and api.calls == []


def test_busy_server_is_retried(tmp_path):
    api = FakeAPI(fail_first_with=503)
    out = live(docs()[:1], api, tmp_path / "r.json", tmp_path)
    assert out[0]["status"] == "created"


def test_idempotency_key_is_stable_per_document():
    a, b = docs()
    assert marqov.idempotency_key(PROJECT, a) == marqov.idempotency_key(PROJECT, a)
    assert marqov.idempotency_key(PROJECT, a) != marqov.idempotency_key(PROJECT, b)


def test_live_without_key_reports_and_does_not_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(marqov, "API_KEY_PATH", tmp_path / "missing-key")
    with pytest.raises(FileNotFoundError):
        MarqovClient()


def hub_doc():
    return PlannedDoc("round:overview", "report", marqov.OVERVIEW_TITLE, "# overview\ncounts only\n", target="hub")


def created_in(api):
    return [(c[1].split("/")[3], c[2]["title"]) for c in api.calls if c[0] == "POST" and c[1].endswith("/documents")]


def test_hub_and_per_repo_documents_go_to_their_own_projects(tmp_path):
    api = FakeAPI()
    out = live(docs() + [hub_doc()], api, tmp_path / "r.json", tmp_path)
    assert {r["status"] for r in out} == {"created"}
    assert created_in(api) == [(PROJECT, "org/repo: run record"), (PROJECT, "org/repo: review"),
                               (HUB, marqov.OVERVIEW_TITLE)]


def test_per_repo_override(tmp_path):
    api = FakeAPI()
    own = "33333333-3333-4333-8333-333333333333"
    live(docs(), api, tmp_path / "r.json", tmp_path, per_repo={"org/repo": own})
    assert {p for p, _ in created_in(api)} == {own}


@pytest.mark.parametrize("kw,why", [({"repo_project": HUB}, "must not go to the hub"),
                                    ({"repo_project": None}, "no Project configured"),
                                    ({"hub": None}, "no Project configured"),
                                    ({"per_repo": {"org/repo": HUB}}, "must not go to the hub")])
def test_live_refuses_unsafe_or_missing_targets_before_any_request(tmp_path, kw, why):
    api = FakeAPI()
    out = live(docs() + [hub_doc()], api, tmp_path / "r.json", tmp_path, **kw)
    assert {r["status"] for r in out} == {"blocked"} and api.calls == []
    assert any(why in p for p in out[0]["problems"])


def test_key_file_inside_the_repository_is_refused(tmp_path):
    from harness.paths import REPO_ROOT

    t = marqov.Targets.from_settings({"hub": {"project_id": HUB, "key_path": str(REPO_ROOT / ".marqov_key")},
                                      "repos": {"project_id": PROJECT}})
    assert any("inside the repository" in p for p in t.problems([hub_doc()]))


def test_a_record_from_another_project_is_not_reused(tmp_path):
    api, rec = FakeAPI(), tmp_path / "r.json"
    live(docs(), api, rec, tmp_path)
    other = "44444444-4444-4444-8444-444444444444"
    out = live(docs(), api, rec, tmp_path, repo_project=other)
    assert [r["status"] for r in out] == ["created", "created"]
    assert {e["project"] for e in json.loads(rec.read_text()).values()} == {other}


def test_nothing_is_hardcoded():
    t = marqov.Targets.from_settings({})
    assert t.hub.project_id is None and t.repos.project_id is None and not t.show_security_counts


def test_shipped_config_holds_no_project_or_document_ids():
    import re

    import yaml
    from harness.paths import REPO_ROOT

    text = (REPO_ROOT / "config" / "harness.yaml").read_text()
    cfg = yaml.safe_load(text)["publish"]["marqov"]
    t = marqov.Targets.from_settings(cfg)
    assert t.hub.project_id is None and t.repos.project_id is None and not t.show_security_counts
    assert t.protected == {} and t.retired == []
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text)  # the repository is public
    src = (REPO_ROOT / "harness" / "publish" / "marqov.py").read_text()
    ids = set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", src))
    assert ids == {str(marqov._IDEMPOTENCY_NS)}  # only the idempotency-key namespace


def test_local_targets_file_is_laid_over_the_shipped_config(tmp_path):
    import yaml

    from harness.paths import REPO_ROOT
    from harness.publish.__main__ import _marqov_targets

    local = tmp_path / "marqov-targets.yaml"
    local.write_text(yaml.safe_dump({"hub": {"project_id": HUB, "key_path": str(tmp_path / "k")},
                                     "protected_documents": {PARTNER_OVERVIEW: "partners"},
                                     "retired_projects": ["deadbeef"]}))
    t = _marqov_targets(REPO_ROOT / "config" / "harness.yaml", local)
    assert t.hub.project_id == HUB and t.hub.key_path == tmp_path / "k"
    assert t.repos.project_id is None and not t.show_security_counts  # kept from the shipped config
    assert t.protected == {PARTNER_OVERVIEW: "partners"} and t.retired == ["deadbeef"]
    assert _marqov_targets(REPO_ROOT / "config" / "harness.yaml", tmp_path / "missing").hub.project_id is None


def test_retired_project_is_refused(tmp_path):
    t = marqov.Targets.from_settings({"hub": {"project_id": "deadbeef-0000-4000-8000-000000000000"},
                                      "repos": {"project_id": PROJECT}, "retired_projects": ["deadbeef"]})
    assert any("retired" in p for p in t.problems([hub_doc()]))


def test_hub_documents_withhold_security_counts_by_default():
    report = {"header": {"repository": "org/repo", "commit": "a" * 40, "review_date": "2026-10-29",
                         "completion": "complete"},
              "scorecard": {"counts": {"security_vulnerability": 3, "dependency_advisory": 2, "correctness": 5,
                                       "docs_tests_maintenance": 7}}}
    summary = {"basis": "accepted findings", "projects": [{"repository": "org/repo", "commit": "a" * 40,
                                                           "completion": "complete",
                                                           "counts": report["scorecard"]["counts"]}]}
    for md in (marqov.overview_markdown([report], []), marqov.public_summary_markdown(summary)):
        assert "Security |" not in md and "Advisories" not in md and "| 3 |" not in md and "| 2 |" not in md
        assert "| 5 | 7 |" in md and marqov.SECURITY_WITHHELD in md
    shown = marqov.overview_markdown([report], [], show_security=True)
    assert "| 3 | 2 | 5 | 7 |" in shown


def hub_for_everything(tmp_path, confirmed=None):
    t = marqov.Targets.from_settings({"hub": {"project_id": HUB, "key_path": str(tmp_path / "k"),
                                              "single_member_confirmed": confirmed},
                                      "repos": {"project_id": HUB, "key_path": str(tmp_path / "k"), "allow_hub": True}})
    return t


def test_repo_documents_in_the_hub_need_the_explicit_opt_in(tmp_path):
    shared = {"hub": {"project_id": HUB}, "repos": {"project_id": HUB}}
    assert any("must not go to the hub" in p for p in marqov.Targets.from_settings(shared).problems(docs()))
    shared["repos"]["allow_hub"] = "yes"  # only a literal true counts
    assert any("must not go to the hub" in p for p in marqov.Targets.from_settings(shared).problems(docs()))
    assert hub_for_everything(tmp_path).problems(docs() + [hub_doc()]) == []


@pytest.mark.parametrize("members,confirmed,ok", [
    (None, None, False),        # the key cannot see members and nobody has confirmed it
    (None, "2026-10-29 David Ryan, checked in the web app", True),
    (1, None, True),
    (2, None, False),
    (2, "2026-10-29 David Ryan", False),  # a count the API reports beats a stale statement
])
def test_repo_documents_in_the_hub_only_while_the_team_is_one_person(tmp_path, members, confirmed, ok):
    api = FakeAPI(members=members)
    out = publish_live(docs() + [hub_doc()], hub_for_everything(tmp_path, confirmed), lambda kp: client(api),
                       tmp_path / "r.json")
    assert ({r["status"] for r in out} == {"created"}) is ok
    if not ok:
        assert api.writes() == [] and all(c[0] == "GET" for c in api.calls)


def test_hub_only_documents_skip_the_membership_check(tmp_path):
    api = FakeAPI(members=5)
    out = publish_live([hub_doc()], hub_for_everything(tmp_path), lambda kp: client(api), tmp_path / "r.json")
    assert out[0]["status"] == "created" and ("GET", "/api/team/members", None, None) not in api.calls
