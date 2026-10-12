#!/usr/bin/env python3
"""Build the Symposium bundle, dist/Symposium_skill.zip (R-I8): `make build` runs this.

    python3 tools/bundle.py dist/Symposium_skill.zip

The zip holds:
  README.md                  the repository's README: Symposium, installing it, and participating
  LICENSE                    the repository's licence
  skills/symposium/          the `symposium` skill, with toolchain/: the repository's Symposium
                             base, one for one at its repository paths, so every relative link
                             between its documents resolves in the installed skill as it does in
                             a clone: spec/, tools/ (the workflow tools, the docs, roles, policies
                             and SOPs, the conformance suite and record checkers, and the CLI in
                             tools/symposium-data/, stamped with compat.json: the data-server
                             version this bundle was built for, R-I5), server/, examples/, and
                             the data server's operator docs (its top-level *.md but its
                             developer README) and its Helm chart, data-server/helm/

Only repository-maintenance files stay out: this script (NOT_SHIPPED), and everything outside
TOOLCHAIN (AGENTS.md, CLAUDE.md, the Makefile, CI, tests, and the data server's source; the
server ships as its image).

Never tests, caches, the skill's own Python environment (.venv) or editor leftovers. Entries are sorted and dated alike, so the same tree
always builds the same zip. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import re
import stat
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "symposium"
# The repository's Symposium base, kept at its repository paths under skills/symposium/toolchain/.
TOOLCHAIN = (
    "spec",
    "tools",
    "server",
    "examples",
    "data-server/*.md",
    "data-server/helm",
)
# inside TOOLCHAIN, but repository maintenance: never shipped
NOT_SHIPPED = {"tools/bundle.py", "tools/pyproject.toml", "data-server/README.md"}
SKIPPED = {"__pycache__", "tests", ".pytest_cache", ".ruff_cache", ".DS_Store"}
DATE = (1980, 1, 1, 0, 0, 0)


class Bundle:
    def __init__(self, repo: Path = REPO):
        self.repo = repo

    def files(self, root: Path):
        """Every file under `root` worth shipping, as (path, path relative to `root`)."""
        if root.is_file():
            yield root, Path(root.name)
            return
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if (
                path.is_file()
                and not SKIPPED & set(relative.parts)
                and not any(part.startswith(".venv") for part in relative.parts)
                and path.suffix != ".pyc"
            ):
                yield path, relative

    def entries(self) -> dict:
        """zip path -> source path (or bytes, for the generated stamp)."""
        out = {"README.md": self.repo / "README.md", "LICENSE": self.repo / "LICENSE"}
        for path, relative in self.files(SKILL):
            out[f"skills/symposium/{relative.as_posix()}"] = path
        for item in TOOLCHAIN:
            for source in sorted(self.repo.glob(item)):
                for path, relative in self.files(source):
                    inner = source.relative_to(self.repo)
                    if source.is_dir():
                        inner = inner / relative
                    if inner.as_posix() in NOT_SHIPPED:
                        continue
                    out[f"skills/symposium/toolchain/{inner.as_posix()}"] = path
        out["skills/symposium/toolchain/tools/symposium-data/compat.json"] = (
            json.dumps({"data_server_version": self.data_server_version()}, indent=2)
            + "\n"
        ).encode()
        return out

    def data_server_version(self) -> str:
        pyproject = (
            self.repo / "data-server" / "service" / "pyproject.toml"
        ).read_text()
        match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
        if not match:
            raise SystemExit("no version in data-server/service/pyproject.toml")
        return match.group(1)

    def write(self, out: Path) -> dict:
        out.parent.mkdir(parents=True, exist_ok=True)
        entries = self.entries()
        partial = out.with_name(out.name + ".partial")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(entries):
                source = entries[name]
                info = zipfile.ZipInfo(name, date_time=DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                if isinstance(source, bytes):
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    zf.writestr(info, source)
                else:
                    mode = 0o755 if source.stat().st_mode & stat.S_IXUSR else 0o644
                    info.external_attr = (stat.S_IFREG | mode) << 16
                    zf.writestr(info, source.read_bytes())
        partial.replace(out)
        return {"bundle": str(out), "files": len(entries)}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(json.dumps({"error": "usage: bundle.py <out.zip>"}))
        return 1
    print(json.dumps(Bundle().write(Path(argv[0]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
