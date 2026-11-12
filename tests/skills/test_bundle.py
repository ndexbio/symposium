"""The bundle and `make deploy-local`: the zip holds the root README, the licence
and the skill, with its toolchain inside it: the repository's Symposium base one for one, at its
repository paths, so every relative link in the installed skill resolves inside it and the
conformance suite runs from it; deploy-local installs exactly the skill; and the installed skill
works with no repository and nothing on PATH but python3, preparing its own Python runtime once
per agent session, including `validate` against a data server."""

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from harness import MAX_WAIT
from skills.test_workflow import note
from suite import REPO

sys.path.insert(0, str(REPO / "tools"))
import bundle  # noqa: E402

BUNDLE = REPO / "dist" / "Symposium_skill.zip"
CLI = "skills/symposium/toolchain/tools/symposium-data"
# the repository's Symposium base, shipped whole at its repository paths under toolchain/
SHIPPED_FOLDERS = ("spec", "tools", "server", "examples")
# and the data server's operator docs (its top-level *.md but its developer README) and chart
SHIPPED_FILES = (
    ":(glob)data-server/*.md",
    "data-server/helm",
)
NOT_SHIPPED = {"tools/bundle.py", "tools/pyproject.toml", "data-server/README.md"}


def make(*args) -> subprocess.CompletedProcess:
    # the real environment: make runs lint before it builds
    return subprocess.run(
        ["make", "-s", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=MAX_WAIT,
    )


@pytest.fixture(scope="module")
def installed(tmp_path_factory) -> dict:
    skills = tmp_path_factory.mktemp("install") / "skills"
    result = make("deploy-local", f"SKILLS={skills}")
    assert result.returncode == 0, result.stdout + result.stderr
    return {"skills": skills, "output": result.stdout}


def files_under(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def tracked(*paths) -> set:
    listed = subprocess.run(
        ["git", "ls-files", "--", *paths],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(listed.stdout.split())


def only_python3(suite, tmp_path) -> dict:
    """The environment of an agent on a host with python3 and nothing else of Symposium's: no
    CLI on PATH, no CLI command handed down, no repository."""
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (shim / "python3").chmod(0o755)
    env = {k: v for k, v in suite.env.items() if k != "SYMPOSIUM_DATA_CLI"}
    return {**env, "PATH": os.pathsep.join([str(shim), "/usr/bin", "/bin"])}


def run_skill(skill: Path, cwd: Path, env: dict, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(skill / "scripts" / "main.py"), *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=MAX_WAIT,
    )


def test_the_bundle_holds_the_skill_with_its_toolchain_and_the_stamped_cli(installed):
    with zipfile.ZipFile(BUNDLE) as zf:
        names = set(zf.namelist())
        skill_md = zf.read("skills/symposium/SKILL.md").decode()
        compat = json.loads(zf.read(f"{CLI}/compat.json"))
        readme = zf.read("README.md")
    assert all(
        n in ("README.md", "LICENSE") or n.startswith("skills/symposium/")
        for n in names
    )
    # the repository's, at the root, with only its links moved to where the zip holds each
    assert bundle.LINK.sub("", readme.decode()) == bundle.LINK.sub(
        "", (REPO / "README.md").read_text(encoding="utf-8")
    )
    with zipfile.ZipFile(BUNDLE) as zf:
        assert zf.read("LICENSE") == (REPO / "LICENSE").read_bytes()
    for required in (
        "skills/symposium/SKILL.md",
        "skills/symposium/README.md",
        "skills/symposium/scripts/main.py",
        "skills/symposium/scripts/runtime.py",
        "skills/symposium/toolchain/tools/setup.py",
        "skills/symposium/toolchain/tools/publish.py",
        "skills/symposium/toolchain/tools/sync.py",
        "skills/symposium/toolchain/tools/gate.py",
        "skills/symposium/toolchain/tools/validate.py",
        "skills/symposium/toolchain/tools/data_io.py",
        "skills/symposium/toolchain/tools/telemetry.py",
        "skills/symposium/toolchain/tools/browse.py",
        "skills/symposium/toolchain/tools/serve.py",
        "skills/symposium/toolchain/tools/figures.py",
        "skills/symposium/toolchain/tools/templates.py",
        "skills/symposium/toolchain/tools/vendor/cytoscape.min.js",
        "skills/symposium/toolchain/tools/vendor/cytoscape-svg.js",
        "skills/symposium/toolchain/tools/CANONICAL.md",
        "skills/symposium/toolchain/server/bootstrap.py",
        "skills/symposium/toolchain/tools/MEMBER-AGENT-INSTRUCTIONS.md",
        "skills/symposium/toolchain/tools/roles/README.md",
        "skills/symposium/toolchain/spec/symposium_specification.md",
        "skills/symposium/toolchain/data-server/RUNBOOK.md",
        "skills/symposium/toolchain/data-server/helm/symposium-helm/Chart.yaml",
        "skills/symposium/toolchain/data-server/helm/symposium-helm/values.yaml",
        "skills/symposium/toolchain/data-server/helm/symposium-helm/templates/deployment.yaml",
        f"{CLI}/cli.py",
        f"{CLI}/main.py",
        f"{CLI}/keystore.py",
        f"{CLI}/requirements.txt",
        f"{CLI}/reference/COMMANDS.md",
    ):
        assert required in names, required
    assert not [
        n
        for n in names
        if "__pycache__" in n
        or n.endswith(".pyc")
        or "/tests/" in n
        or "/.venv" in n
        or n == f"{CLI}/symposium-data"
    ]
    assert re.match(r"^---\nname: symposium\n", skill_md)
    # make deploy-local builds with no version of its own, so the install says so
    assert "\nversion: 0.0.0-dev\n" in skill_md
    version = re.search(
        r'^version = "([^"]+)"',
        (REPO / "data-server" / "service" / "pyproject.toml").read_text(),
        re.MULTILINE,
    ).group(1)
    assert compat == {"data_server_version": version}


def test_the_installed_skill_holds_the_repositorys_symposium_base_one_for_one(
    installed,
):
    toolchain = installed["skills"] / "symposium" / "toolchain"
    expected = tracked(*SHIPPED_FOLDERS, *SHIPPED_FILES) - NOT_SHIPPED
    shipped = {
        f
        for f in files_under(toolchain)
        if "__pycache__" not in f  # what running the suite leaves behind
    } - {"tools/symposium-data/compat.json"}  # the bundle's stamp
    assert shipped == expected
    for path in sorted(expected):
        assert (toolchain / path).read_bytes() == (REPO / path).read_bytes(), path


def test_every_relative_link_in_the_bundle_resolves_inside_it(installed):
    """The build's own check, run again on what it wrote: every Markdown link of the zip, its
    README included, names a file or folder the zip holds."""
    with zipfile.ZipFile(BUNDLE) as zf:
        names = zf.namelist()
        documents = {n: zf.read(n).decode("utf-8") for n in names if n.endswith(".md")}
    assert bundle.dead_links(documents, bundle.zip_exists(names)) == []
    readme = documents["README.md"]
    assert "](skills/symposium/toolchain/data-server/RBAC.md)" in readme
    assert f"]({bundle.GITHUB}AGENTS.md)" in readme  # not shipped: its GitHub address


def test_a_dead_link_fails_the_build_and_writes_no_zip(tmp_path, monkeypatch):
    entries = bundle.Bundle.entries

    def with_a_dead_link(self):
        out = entries(self)
        out["skills/symposium/NOTES.md"] = b"See [the guide](missing/GUIDE.md#start).\n"
        return out

    monkeypatch.setattr(bundle.Bundle, "entries", with_a_dead_link)
    out = tmp_path / "Symposium_skill.zip"
    result = bundle.Bundle().write(out)
    assert result["dead"] == [
        {
            "file": "skills/symposium/NOTES.md",
            "link": "missing/GUIDE.md#start",
            "resolved": "skills/symposium/missing/GUIDE.md",
        }
    ]
    assert not out.exists() and list(tmp_path.iterdir()) == []


def test_the_build_stamps_its_version_into_the_skills_frontmatter(tmp_path):
    """The release tag's version reaches the installed skill, which otherwise cannot say
    which release it is. The body is left alone."""
    out = tmp_path / "Symposium_skill.zip"
    result = bundle.Bundle(version="1.2.3").write(out)
    assert result["version"] == "1.2.3"
    with zipfile.ZipFile(out) as zf:
        skill_md = zf.read("skills/symposium/SKILL.md").decode()
    assert re.match(r"^---\nname: symposium\n", skill_md)
    assert "\nversion: 1.2.3\n" in skill_md
    source = (REPO / "skills" / "symposium" / "SKILL.md").read_text(encoding="utf-8")
    assert skill_md.split("\n---\n", 1)[1] == source.split("\n---\n", 1)[1]


def test_a_skill_document_with_no_version_line_fails_the_build(tmp_path, monkeypatch):
    """Without the line there is nothing to rewrite, and the build would ship whatever the
    repository happens to carry."""
    skill = tmp_path / "skills" / "symposium"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: symposium\n---\n\n# Symposium\n")
    monkeypatch.setattr(bundle, "SKILL", skill)
    with pytest.raises(SystemExit, match="no version line"):
        bundle.Bundle(version="1.2.3").skill_md()


def test_every_relative_link_in_the_repository_resolves():
    """The same check on the repository's own documents, shipped or not; a skill document's
    `toolchain/…` link names the repository path the bundle ships there."""
    documents = {
        name: (REPO / name).read_text(encoding="utf-8")
        for name in tracked(":(glob)**/*.md")
        if not name.startswith("examples/") and name != "CHANGELOG.md"
    }

    def exists(path: str) -> bool:
        if path.startswith(bundle.SHIPPED):
            path = path[len(bundle.SHIPPED) :]
        return (REPO / path).exists()

    assert bundle.dead_links(documents, exists) == []


def test_the_conformance_suite_runs_from_the_installed_skill(installed):
    tools = installed["skills"] / "symposium" / "toolchain" / "tools"
    result = subprocess.run(
        [sys.executable, "conformance.py"],
        cwd=tools,
        # the installed skill stays exactly as installed: no bytecode written into it
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=MAX_WAIT,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr
    assert "everything behaved as specified" in result.stdout


def test_deploy_local_installs_exactly_the_skill_and_says_so(installed):
    skills = installed["skills"]
    with zipfile.ZipFile(BUNDLE) as zf:
        names = zf.namelist()
    expected = {n[len("skills/symposium/") :] for n in names if n.startswith("skills/")}
    assert files_under(skills / "symposium") == expected
    # after lint and build report, deploy-local ends with its three lines
    assert installed["output"].splitlines()[-3:] == [
        f"/symposium skill installed in {skills}/symposium",
        "  usage: /symposium <setup|bootstrap|use|publish|sync|gate|validate|serve|port|"
        "admin-config|…> [options]    e.g. /symposium setup --invite-file <file>",
        f"  full instructions: {skills}/symposium/README.md",
    ]


def test_deploy_local_refuses_an_empty_destination(installed):
    result = make("deploy-local", "SKILLS=")
    assert result.returncode != 0 and "SKILLS is empty" in result.stdout + result.stderr
    assert (installed["skills"] / "symposium" / "SKILL.md").exists()  # nothing removed


def test_the_installed_skill_prepares_its_runtime_once_per_session(
    installed, root_dir, cli, suite, tmp_path
):
    invite = root_dir / "lyra.invite"
    cli.ok(
        root_dir,
        "invite",
        "--handle",
        "lyra",
        "--access",
        "community-member:*",
        "--out",
        invite,
    )
    skill = installed["skills"] / "symposium"
    env = only_python3(suite, tmp_path)
    anywhere = (
        tmp_path / "anywhere"
    )  # the agent's directory: the skill keeps the session
    anywhere.mkdir()

    # the session's first command builds the skill's own environment, then records it
    result = run_skill(skill, anywhere, env, "setup", "--invite-file", invite)
    joined = json.loads(result.stdout)
    assert result.returncode == 0, (joined, result.stderr)
    assert joined["registered"] is True and joined["handle"] == "lyra"
    session = suite.home / ".symposium" / "member" / "demo" / "lyra"
    record = json.loads((session / ".symposium" / "runtime.json").read_text())
    assert record == {
        "cli": [
            str(skill / ".venv" / "bin" / "python"),
            str(skill / "toolchain" / "tools" / "symposium-data" / "cli.py"),
        ]
    }
    built = (skill / ".venv").stat().st_mtime_ns

    # a later command in the session only reads the record: `validate` is `publish --check`,
    # which syncs against the suite's server first
    checked = run_skill(
        skill, anywhere, env, "validate", note(anywhere, "lyra", "installed")
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "--check: validation passed" in checked.stdout
    assert (skill / ".venv").stat().st_mtime_ns == built


def test_a_runtime_that_cannot_be_built_says_what_it_needs(installed, suite, tmp_path):
    # a copy of the installed skill whose CLI asks for a package no index has
    skill = tmp_path / "symposium"
    shutil.copytree(
        installed["skills"] / "symposium",
        skill,
        ignore=shutil.ignore_patterns(".venv*"),
    )
    (skill / "toolchain" / "tools" / "symposium-data" / "requirements.txt").write_text(
        "symposium-no-such-package-anywhere==0.0.0\n"
    )
    session = tmp_path / "session"
    session.mkdir()
    env = only_python3(suite, tmp_path)
    result = run_skill(skill, session, env, "setup", "--invite-file", "x.invite")
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["error"].startswith("the skill could not install the CLI's packages")
    assert "venv module" in report["needs"] and "PyPI" in report["needs"]
    assert not (session / ".symposium" / "runtime.json").exists()
    assert not (skill / ".venv").exists() and not list(skill.glob(".venv-*"))
