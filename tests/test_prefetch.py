"""Host-side prefetch of commit-pinned source archives, and the per-repository install options
that use them (local packages, omissions, source builds, another Python)."""

import hashlib
import io

import pytest

from harness.controller.config import RepoSpec
from harness.stages import deps, prefetch
from harness.workers.docker import DockerWorker
from tests.test_deps import fake_venv

C = "a" * 40
URL = f"https://codeload.github.com/o/r/tar.gz/{C}"


def entry(data=b"tree", **kw):
    return {"name": "dep", "url": URL, "sha256": hashlib.sha256(data).hexdigest(), **kw}


class Response(io.BytesIO):
    def __init__(self, data, final=URL):
        super().__init__(data)
        self.final = final

    def geturl(self):
        return self.final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(data, final=URL, calls=None):
    def opener(req, timeout):
        if calls is not None:
            calls.append(req.full_url)
        return Response(data, final)
    return opener


@pytest.mark.parametrize("bad", [
    {"url": "http://codeload.github.com/o/r/tar.gz/" + C},            # not https
    {"url": "https://example.com/o/r/" + C + ".tar.gz"},             # host not allowed
    {"url": "https://codeload.github.com/o/r/tar.gz/main"},          # a branch, not a commit
    {"sha256": ""},                                                  # no hash
    {"name": "../x"},
    {"extract_to": "../outside"},
    {"extract_to": "/abs"},
    {"fetchcontent": "bad name"},
    {"extract_to": "a", "fetchcontent": "b"},
])
def test_entries_outside_the_rules_are_refused(bad):
    with pytest.raises(ValueError):
        prefetch.validate({**entry(), **bad})


def test_fetch_checks_the_hash_and_reuses_a_good_file(tmp_path):
    calls = []
    recs = prefetch.fetch([entry(extract_to="pybind11")], tmp_path, opener=opener_for(b"tree", calls=calls),
                          log=lambda m: None)
    assert recs[0]["commit"] == C and recs[0]["bytes"] == 4 and (tmp_path / "dep.tar.gz").read_bytes() == b"tree"
    prefetch.fetch([entry()], tmp_path, opener=opener_for(b"tree", calls=calls), log=lambda m: None)
    assert len(calls) == 1  # second time the file on disk already matched


def test_a_hash_mismatch_stops_and_leaves_nothing(tmp_path):
    with pytest.raises(prefetch.PrefetchError, match="does not match"):
        prefetch.fetch([entry(b"expected")], tmp_path, opener=opener_for(b"tampered"), log=lambda m: None)
    assert list(tmp_path.iterdir()) == []


def test_a_redirect_off_the_allowed_hosts_is_refused(tmp_path):
    with pytest.raises(prefetch.PrefetchError, match="redirected"):
        prefetch.fetch([entry()], tmp_path, opener=opener_for(b"tree", final="https://evil.example/x"),
                       log=lambda m: None)


def test_a_prefetch_the_snapshot_no_longer_declares_is_refused(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("GIT_TAG release-1.12.1\n")
    ok = entry(fetchcontent="googletest", declared_in={"file": "CMakeLists.txt", "contains": "release-1.12.1"})
    prefetch.check_declared([ok], tmp_path)
    bumped = {**ok, "declared_in": {"file": "CMakeLists.txt", "contains": "release-1.17.0"}}
    with pytest.raises(prefetch.PrefetchError, match="no longer contains"):
        prefetch.check_declared([bumped], tmp_path)
    sub = entry(extract_to="pybind11", declared_in={"submodule": "pybind11"})
    prefetch.check_declared([sub], tmp_path, submodule_commit=lambda s, p: C)
    with pytest.raises(prefetch.PrefetchError, match="submodule"):
        prefetch.check_declared([sub], tmp_path, submodule_commit=lambda s, p: "b" * 40)
    with pytest.raises(ValueError):
        prefetch.validate(entry(declared_in={"file": "../x", "contains": "y"}))


def test_unpacking_happens_in_the_worker_and_cmake_is_pointed_at_it():
    lines = prefetch.script_lines([prefetch.validate(entry(name="pybind11", extract_to="pybind11")),
                                   prefetch.validate(entry(name="googletest", fetchcontent="googletest"))])
    s = "\n".join(lines)
    assert "tar -xzf /prefetch/pybind11.tar.gz -C /work/pybind11" in s
    assert "-DFETCHCONTENT_SOURCE_DIR_GOOGLETEST=/tmp/qot-prefetch/googletest" in s
    assert "-DFETCHCONTENT_FULLY_DISCONNECTED=ON" in s and "exit 92" in s


def test_install_worker_mounts_prefetch_read_only(tmp_path, monkeypatch):
    seen = []

    class P:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return P()
    monkeypatch.setattr("harness.workers.docker.subprocess.run", fake_run)
    (tmp_path / "pf").mkdir()
    DockerWorker().install_deps("true", tmp_path, tmp_path / "deps", prefetch_dir=tmp_path / "pf")
    run = next(c for c in seen if "qot-deps-" in " ".join(c) and c[1] == "run")
    assert f"{(tmp_path / 'pf').resolve()}:/prefetch:ro" in run


def test_python_variant_image_and_record(tmp_path):
    w = DockerWorker(image="qot:dev")
    v = w.variant(python="3.10")
    assert v.image == "qot:dev-py310" and v.python == "3.10" and w.image == "qot:dev"
    assert w.variant(platform="linux/amd64", python="3.10").image == "qot:dev-py310-amd64"
    assert w.for_platform("linux/amd64").image == "qot:dev-amd64"
    with pytest.raises(ValueError):
        w.variant(python="3.1; rm")
    assert RepoSpec.from_dict({"name": "o/r", "source": "s", "worker": {"python": "3.10"}}).worker_python == "3.10"
    with pytest.raises(ValueError, match="quoted"):
        RepoSpec.from_dict({"name": "o/r", "source": "s", "worker": {"python": 3.10}})


def test_local_packages_install_with_the_project_and_go_first_on_the_path(tmp_path):
    (tmp_path / "setup.py").write_text("")
    (tmp_path / "src" / "pkg-core" / "pkg").mkdir(parents=True)
    (tmp_path / "libs" / "other" / "src").mkdir(parents=True)
    p = deps.plan(tmp_path, local_packages=["src/pkg-core[tests]", "libs/other"])
    assert p["local_packages"] == ["src/pkg-core[tests]", "libs/other"]
    s = deps.script(p)
    assert "pip install --report /tmp/report.json  './src/pkg-core[tests]' ./libs/other ." in s
    assert deps.python_path(tmp_path, p) == ["src/pkg-core", "libs/other/src"]
    fake = tmp_path / "d"
    fake_venv(fake)
    cmd = DockerWorker().with_deps(fake, deps.python_path(tmp_path, p)).command(
        "x", tmp_path, inputs=None, network=False, writable_copy=True, name="n")
    assert "PYTHONPATH=/work/src/pkg-core:/work/libs/other/src:/work/src:/work" in cmd
    with pytest.raises(ValueError):
        deps.plan(tmp_path, local_packages=["../escape"])
    assert "local_packages" not in deps.plan(tmp_path)  # unchanged plan when not configured


def test_built_files_are_kept_and_linked_into_later_copies_only(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    s = deps.script(deps.plan(tmp_path))
    assert "rm -rf /deps/generated" in s and "QOT-GENERATED" in s and "file:///work" in s
    fake_venv(tmp_path / "d")
    run = DockerWorker().with_deps(tmp_path / "d").command("x", tmp_path, inputs=None, network=False,
                                                           writable_copy=True, name="n")
    wrapper = run[-1]
    assert "cp -Rns /deps/generated/. /work/" in wrapper and 'QOT_INSTALL:-0}" != 1' in wrapper
    assert "QOT_INSTALL=1" not in run  # only the install container skips the links


def test_omitted_and_source_built_packages_leave_the_locked_set(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (tmp_path / "uv.lock").write_text('version = 1\n[[package]]\nname = "PyQubo"\nversion = "1.5.0"\n')
    p = deps.plan(tmp_path, omit=[{"package": "pyqpanda3", "reason": "no arm64 wheel"}],
                  source_builds=[{"package": "pyqubo", "prefetch": "pyqubo", "reason": "no arm64 wheel"}])
    assert p["omit"] == [{"package": "pyqpanda3", "reason": "no arm64 wheel"}]
    assert p["source_builds"][0]["version"] == "1.5.0"
    pf = [prefetch.validate(entry(name="pyqubo"))]
    s = deps.script(p, pf)
    assert "--no-emit-package pyqpanda3" in s and "--no-emit-package pyqubo" in s
    assert "pip install --no-deps /tmp/qot-prefetch/pyqubo" in s and "1.5.0" in s
    assert s.index("source-build pyqubo") < s.index("QOT-STEP lock")
    with pytest.raises(ValueError, match="no prefetch entry"):
        deps.script(p, [])
    with pytest.raises(ValueError, match="reason"):
        deps.plan(tmp_path, omit=[{"package": "x"}])
    (tmp_path / "uv.lock").unlink()
    with pytest.raises(ValueError, match="uv.lock"):
        deps.plan(tmp_path, omit=[{"package": "x", "reason": "y"}])
