from __future__ import annotations

from harness.scanners.base import ScanResult, Scanner, has_files, load_json


class Lychee(Scanner):
    """Local links only (--offline): workers have no network during scans."""

    name = "lychee"

    def applies(self, src):
        ok = has_files(src, ("**/*.md", "**/*.rst", "**/*.html"))
        return (True, "") if ok else (False, "no documentation files")

    def script(self) -> str:
        return "lychee --offline --no-progress --format json --exclude-path .git . ; rc=$?; [ $rc -le 2 ] && exit 0 || exit $rc"

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        doc = load_json(stdout)
        if doc is None:
            return ScanResult(self.name, "failed", note=f"no output; exit {exit_code}: {stderr[-300:]}")
        broken = []
        for path, errors in (doc.get("error_map") or {}).items():
            for e in errors:
                broken.append({"file": path.lstrip("./"), "url": e.get("url", "").replace("file:///work/", ""),
                               "line": (e.get("span") or {}).get("line")})
        return ScanResult(self.name, "ok", hygiene={"links_checked": doc.get("total", 0), "broken_local_links": len(broken),
                                                    "broken": broken[:50]},
                          note="external links not checked (offline)")
