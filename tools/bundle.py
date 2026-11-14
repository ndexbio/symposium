#!/usr/bin/env python3
"""Build the Symposium skill's release zip, dist/symposium_skill-<version>.zip: `make build`
runs this.

    python3 tools/bundle.py dist/symposium_skill-<version>.zip [version]

The version is the release tag's, passed by `make build VERSION=<semver>`. It names the zip and
is written into the skill's frontmatter, as `metadata.version`, on the way in, so an installed
skill says which release it came from. A build that is given none says 0.0.0-dev.

The zip holds one folder, `symposium/`, in the Agent Skills format, so it unzips straight into
an agent's skills directory:

  symposium/SKILL.md         the skill's entry document
  symposium/README.md        the skill's own README: installing it and using it
  symposium/LICENSE          the repository's licence
  symposium/reference/, scripts/
  symposium/toolchain/       the repository's Symposium base, one for one at its repository
                             paths, so every relative link between its documents resolves in
                             the installed skill as it does in a clone: spec/, tools/ (the
                             workflow tools, the docs, roles, policies and SOPs, the conformance
                             suite and record checkers, and the CLI in tools/symposium-data/,
                             stamped with compat.json: the data-server version this zip was
                             built for), server/, examples/, and the data server's operator docs
                             (its top-level *.md but its developer README) and its Helm chart,
                             data-server/helm/

Every relative link in every Markdown file of the zip must name a file or folder the zip holds:
a dead one fails the build, and no zip is written (`dead_links`, which the repository's own
link test shares).

Only repository-maintenance files stay out: this script (NOT_SHIPPED), and everything outside
the skill and TOOLCHAIN (the repository's front-page README, AGENTS.md, CLAUDE.md, the Makefile,
CI, tests, and the data server's source; the server ships as its image).

Never tests, caches, the skill's own Python environment (.venv) or editor leftovers. Entries are
sorted and dated alike, so the same tree always builds the same zip. Standard library only,
Python 3.9+.
"""

from __future__ import annotations

import json
import posixpath
import re
import stat
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "symposium"
# the one folder the zip holds: the skill, named as an agent's skills directory names it
FOLDER = "symposium/"
# The repository's Symposium base, kept at its repository paths under the skill's toolchain/.
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
# where the repository's skill folder names the Symposium base: a skill document's
# `toolchain/…` link names the repository path the zip ships there
SHIPPED = "skills/symposium/toolchain/"
# a Markdown link's target: [text](target "title")
LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
# what a build with no version of its own stamps, so a working-tree install says so
DEV_VERSION = "0.0.0-dev"
# the frontmatter's `metadata.version` line, which every build rewrites
VERSION_LINE = re.compile(r"^  version:.*$", re.MULTILINE)
FENCE = re.compile(r"^\s*(```|~~~)")


def link_targets(text: str):
    """Each relative link target of a Markdown text, outside fenced code: (target, the path
    it names, its #anchor removed). Web, mail and in-page links are not files, and neither is
    a Symposium address: `(@name)`, or one in angle brackets, `(<address>)`."""
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for match in LINK.finditer(line):
            target = match.group(1)
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target[:1] in ("#", "@", "<"):
                continue
            path = target.split("#", 1)[0]
            if path:
                yield target, path


def dead_links(documents: dict, exists) -> list:
    """Every relative link in `documents` ({posix path: Markdown text}) whose path `exists`
    (a posix path -> bool) rejects, each as {file, link, resolved}."""
    dead = []
    for name in sorted(documents):
        for target, path in link_targets(documents[name]):
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            if not exists(resolved):
                dead.append({"file": name, "link": target, "resolved": resolved})
    return dead


def zip_exists(names) -> callable:
    """Whether a posix path is a file of the zip, or a folder holding one."""
    files = set(names)
    folders = set()
    for name in files:
        parent = posixpath.dirname(name)
        while parent and parent not in folders:
            folders.add(parent)
            parent = posixpath.dirname(parent)
    return lambda path: path in files or path in folders


class Bundle:
    def __init__(self, repo: Path = REPO, version: str = DEV_VERSION):
        self.repo = repo
        self.version = version

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
        """zip path -> source path (or bytes, for the generated files)."""
        out = {f"{FOLDER}LICENSE": self.repo / "LICENSE"}
        for path, relative in self.files(SKILL):
            out[f"{FOLDER}{relative.as_posix()}"] = path
        for item in TOOLCHAIN:
            for source in sorted(self.repo.glob(item)):
                for path, relative in self.files(source):
                    inner = source.relative_to(self.repo)
                    if source.is_dir():
                        inner = inner / relative
                    if inner.as_posix() in NOT_SHIPPED:
                        continue
                    out[f"{FOLDER}toolchain/{inner.as_posix()}"] = path
        out[f"{FOLDER}toolchain/tools/symposium-data/compat.json"] = (
            json.dumps({"data_server_version": self.data_server_version()}, indent=2)
            + "\n"
        ).encode()
        out[f"{FOLDER}SKILL.md"] = self.skill_md()
        return out

    def skill_md(self) -> bytes:
        """The skill's entry document, its frontmatter's `metadata.version` set to this
        build's. Only the frontmatter is rewritten: a `version:` line in the body is prose."""
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        end = text.find("\n---\n", 3)
        if not text.startswith("---\n") or end < 0:
            raise SystemExit("skills/symposium/SKILL.md has no frontmatter")
        front, found = VERSION_LINE.subn(f'  version: "{self.version}"', text[:end], count=1)
        if not found or "\nmetadata:\n" not in front:
            raise SystemExit(
                "skills/symposium/SKILL.md frontmatter has no metadata.version line"
            )
        return (front + text[end:]).encode("utf-8")

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
        with zipfile.ZipFile(partial) as zf:
            names = zf.namelist()
            documents = {
                n: zf.read(n).decode("utf-8", "replace") for n in names if n.endswith(".md")
            }
        dead = dead_links(documents, zip_exists(names))
        if dead:
            partial.unlink()
            return {"error": f"{len(dead)} dead link(s) in the bundle; no zip written", "dead": dead}
        partial.replace(out)
        return {"bundle": str(out), "files": len(entries), "version": self.version}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not 1 <= len(argv) <= 2:
        print(json.dumps({"error": "usage: bundle.py <out.zip> [version]"}))
        return 1
    version = argv[1] if len(argv) > 1 else DEV_VERSION
    result = Bundle(version=version).write(Path(argv[0]))
    print(json.dumps(result))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
