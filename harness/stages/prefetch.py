"""Source archives a build needs from a git host, fetched on the host by exact
commit and checked by sha256, for the dependency stage.

The install worker reaches the package registries only (docker/registry-proxy.py);
git hosts stay refused. A build that clones from GitHub (a git submodule the
clone did not fetch, CMake FetchContent, a Makefile that runs git clone) gets
the same tree another way: the host downloads a commit-pinned archive, checks
it against the sha256 in config/repos.yaml, and keeps it in the repository's
run folder (prefetch/<name>.tar.gz). The install worker sees that folder
read-only at /prefetch and unpacks each archive itself, so nothing from the
archive is unpacked or run on the host.

Each entry in config/repos.yaml (deps.prefetch):

    - name: googletest                      # file name; letters, digits, . _ -
      url: https://codeload.github.com/google/googletest/tar.gz/<40-hex commit>
      sha256: <64 hex>                      # required; a mismatch stops the stage
      fetchcontent: googletest              # optional: CMake FetchContent name, or
      extract_to: pybind11                  # optional: a path inside the working copy

      declared_in: {file: CMakeLists.txt, contains: release-1.12.1}
                                            # optional, recommended: or {submodule: pybind11}

An entry with neither extract_to nor fetchcontent is unpacked to
/tmp/qot-prefetch/<name>. declared_in is checked against the snapshot before
anything is fetched, so an upstream bump fails loudly rather than building
the old tree. A fetchcontent entry is passed to CMake as FETCHCONTENT_SOURCE_DIR_<NAME> through CMAKE_ARGS
(read by setup.py builds that follow the pybind11 example, scikit-build and
scikit-build-core), with FETCHCONTENT_FULLY_DISCONNECTED=ON so CMake does not
try to update it.
"""

from __future__ import annotations

import hashlib
import re
import shlex
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

# Archive hosts the controller may download from. A URL must also name a full
# commit id, so a moving branch or tag can never be fetched by accident.
ALLOWED_HOSTS = ("codeload.github.com", "github.com", "gitlab.com")
MAX_BYTES = 512 * 1024 * 1024
UNPACK_ROOT = "/tmp/qot-prefetch"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_COMMIT = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CMAKE_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")


class PrefetchError(RuntimeError):
    pass


def validate(entry: dict) -> dict:
    """The entry, checked; raises ValueError on anything outside the rules above."""
    name, url, sha = str(entry.get("name", "")), str(entry.get("url", "")), str(entry.get("sha256", "")).lower()
    if not _NAME.fullmatch(name):
        raise ValueError(f"prefetch name {name!r}: letters, digits, '.', '_' and '-' only")
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or u.username or u.password or u.port:
        raise ValueError(f"prefetch {name}: url must be https on {', '.join(ALLOWED_HOSTS)}")
    commits = _COMMIT.findall(u.path)
    if not commits:
        raise ValueError(f"prefetch {name}: url must name a full 40-character commit id")
    if not _SHA256.fullmatch(sha):
        raise ValueError(f"prefetch {name}: sha256 (64 hex characters) is required")
    out = {"name": name, "url": url, "commit": commits[-1], "sha256": sha}
    if entry.get("extract_to") is not None and entry.get("fetchcontent") is not None:
        raise ValueError(f"prefetch {name}: give extract_to or fetchcontent, not both")
    if entry.get("extract_to") is not None:
        p = PurePosixPath(str(entry["extract_to"]))
        if p.is_absolute() or ".." in p.parts or not p.parts or str(p) == ".":
            raise ValueError(f"prefetch {name}: extract_to must be a relative path inside the copy")
        out["extract_to"] = str(p)
    if entry.get("fetchcontent") is not None:
        fc = str(entry["fetchcontent"])
        if not _CMAKE_NAME.fullmatch(fc):
            raise ValueError(f"prefetch {name}: fetchcontent must be a CMake dependency name")
        out["fetchcontent"] = fc
    if entry.get("declared_in") is not None:
        d = entry["declared_in"]
        if not isinstance(d, dict) or not (("file" in d and d.get("contains")) or "submodule" in d):
            raise ValueError(f"prefetch {name}: declared_in needs {{file, contains}} or {{submodule}}")
        rel = PurePosixPath(str(d.get("file") or d.get("submodule")))
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"prefetch {name}: declared_in must name a path inside the repository")
        out["declared_in"] = ({"submodule": str(rel)} if "submodule" in d
                              else {"file": str(rel), "contains": str(d["contains"])})
    return out


def check_declared(entries: list[dict], src: Path, submodule_commit=None) -> None:
    """Refuse a prefetch that no longer matches what the snapshot asks for, so an upstream bump
    (a new FetchContent tag, a moved submodule) fails loudly instead of building the old tree.
    Reads files as data only. submodule_commit(src, path) returns the gitlink commit."""
    for e in (validate(x) for x in entries):
        d = e.get("declared_in")
        if not d:
            continue
        if "submodule" in d:
            got = submodule_commit(src, d["submodule"]) if submodule_commit else None
            if got != e["commit"]:
                raise PrefetchError(f"prefetch {e['name']}: the snapshot's submodule {d['submodule']} is at "
                                    f"{got}, not {e['commit']}")
        else:
            f = Path(src) / d["file"]
            text = f.read_text(errors="replace") if f.is_file() and not f.is_symlink() else ""
            if d["contains"] not in text:
                raise PrefetchError(f"prefetch {e['name']}: {d['file']} no longer contains {d['contains']!r}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch(entries: list[dict], dest: Path, *, opener=urllib.request.urlopen, log=print) -> list[dict]:
    """Download each archive into dest (kept if it is already there with the right
    hash). Returns one record per entry for the manifest; raises PrefetchError
    on a hash mismatch or an archive that is too large."""
    checked = [validate(e) for e in entries]
    if len({e["name"] for e in checked}) != len(checked):
        raise ValueError("prefetch names must be unique")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    records = []
    for e in checked:
        path = dest / f"{e['name']}.tar.gz"
        reused = path.is_file() and not path.is_symlink() and _sha256(path) == e["sha256"]
        if not reused:
            part = path.with_suffix(".part")
            h, size = hashlib.sha256(), 0
            req = urllib.request.Request(e["url"], headers={"User-Agent": "quantum-oss-triage-prefetch"})
            with opener(req, timeout=120) as r, open(part, "wb") as f:
                final = urlparse(r.geturl()).hostname
                if final not in ALLOWED_HOSTS:
                    part.unlink(missing_ok=True)
                    raise PrefetchError(f"prefetch {e['name']}: redirected to {final}, which is not allowed")
                while chunk := r.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        f.close()
                        part.unlink(missing_ok=True)
                        raise PrefetchError(f"prefetch {e['name']}: larger than {MAX_BYTES} bytes")
                    h.update(chunk)
                    f.write(chunk)
            if h.hexdigest() != e["sha256"]:
                part.unlink(missing_ok=True)
                raise PrefetchError(f"prefetch {e['name']}: sha256 {h.hexdigest()} does not match the "
                                    f"configured {e['sha256']}")
            part.replace(path)
            path.chmod(0o644)
            log(f"  deps: prefetched {e['name']} at {e['commit'][:12]} ({size} bytes, sha256 ok)")
        records.append({**e, "bytes": path.stat().st_size, "file": f"prefetch/{path.name}", "reused": reused})
    return records


def unpack_dir(e: dict) -> str:
    return f"/work/{e['extract_to']}" if e.get("extract_to") else f"{UNPACK_ROOT}/{e['name']}"


def script_lines(entries: list[dict]) -> list[str]:
    """Shell lines for the install worker: unpack each archive, then point CMake at them."""
    q = shlex.quote
    lines, flags = [], []
    for e in entries:
        d = unpack_dir(e)
        lines.append(f"echo 'QOT-STEP prefetch {e['name']}'; mkdir -p {q(d)} && "
                     f"tar -xzf {q('/prefetch/' + e['name'] + '.tar.gz')} -C {q(d)} --strip-components=1 "
                     f"--no-same-owner --no-same-permissions || {{ echo 'QOT-FAIL prefetch {e['name']}'; exit 92; }}")
        if e.get("fetchcontent"):
            flags.append(f"-DFETCHCONTENT_SOURCE_DIR_{e['fetchcontent'].upper()}={d}")
    if flags:
        flags.append("-DFETCHCONTENT_FULLY_DISCONNECTED=ON")
        lines.append(f"export CMAKE_ARGS=\"${{CMAKE_ARGS:-}} {' '.join(flags)}\"")
    return lines
