"""#20 stage 5: the bundle (R-I8) and `make deploy-local` (R-J4): the zip holds the skill with its
toolchain and the stamped CLI, and nothing else; deploy-local installs exactly that; and the
installed skill works with no repository, through the installed CLI's launcher. #21 stage 3:
the workflow tools in the toolchain, and `validate` from the installed skill."""

import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from skills.test_workflow import note
from suite import REPO

BUNDLE = REPO / "dist" / "Symposium_skill.zip"


def make(*args) -> subprocess.CompletedProcess:
    # the real environment: make runs lint (uv, ruff) before it builds
    return subprocess.run(
        ["make", "-s", *args], cwd=REPO, capture_output=True, text=True, timeout=600
    )


@pytest.fixture(scope="module")
def installed(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("install")
    skills, prefix = root / "skills", root / "prefix"
    result = make("deploy-local", f"SKILLS={skills}", f"PREFIX={prefix}")
    assert result.returncode == 0, result.stdout + result.stderr
    return {"skills": skills, "prefix": prefix, "output": result.stdout}


def files_under(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_the_bundle_holds_the_skill_its_toolchain_and_the_stamped_cli(installed):
    with zipfile.ZipFile(BUNDLE) as zf:
        names = set(zf.namelist())
        skill_md = zf.read("skills/symposium/SKILL.md").decode()
        compat = json.loads(zf.read("tools/symposium-data/compat.json"))
    assert all(
        n.startswith(("skills/symposium/", "tools/symposium-data/")) for n in names
    )
    assert "README.md" not in names  # the bundle's own README arrives with #21
    for required in (
        "skills/symposium/SKILL.md",
        "skills/symposium/README.md",
        "skills/symposium/scripts/main.py",
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
        "tools/symposium-data/symposium-data",
        "tools/symposium-data/cli.py",
        "tools/symposium-data/main.py",
        "tools/symposium-data/requirements.txt",
        "tools/symposium-data/reference/COMMANDS.md",
    ):
        assert required in names, required
    assert not [
        n for n in names if "__pycache__" in n or n.endswith(".pyc") or "/tests/" in n
    ]
    assert re.match(r"^---\nname: symposium\n", skill_md)
    version = re.search(
        r'^version = "([^"]+)"',
        (REPO / "data-server" / "service" / "pyproject.toml").read_text(),
        re.MULTILINE,
    ).group(1)
    assert compat == {"data_server_version": version}


def test_deploy_local_installs_exactly_the_bundle_and_says_so(installed):
    skills, prefix = installed["skills"], installed["prefix"]
    with zipfile.ZipFile(BUNDLE) as zf:
        names = zf.namelist()
    expected_skill = {
        n[len("skills/symposium/") :] for n in names if n.startswith("skills/")
    }
    expected_cli = {
        n[len("tools/symposium-data/") :] for n in names if n.startswith("tools/")
    }
    assert files_under(skills / "symposium") == expected_skill
    assert files_under(prefix / "share" / "symposium-data") == expected_cli
    link = prefix / "bin" / "symposium-data"
    assert link.is_symlink()
    assert (
        link.resolve()
        == (prefix / "share" / "symposium-data" / "symposium-data").resolve()
    )
    assert os.access(link, os.X_OK)
    # after lint and build report, deploy-local ends with its three lines
    assert installed["output"].splitlines()[-3:] == [
        f"/symposium skill installed in {skills}/symposium; the symposium-data CLI it uses is in "
        f"{prefix}/bin (keep it on PATH)",
        "  usage: /symposium <setup|bootstrap|publish|sync|gate|validate|serve|port|"
        "admin-config|…> [options]    e.g. /symposium setup --invite-file <file>",
        f"  full instructions: {skills}/symposium/README.md",
    ]


@pytest.mark.parametrize("empty", ["SKILLS", "PREFIX"])
def test_deploy_local_refuses_an_empty_destination(installed, empty):
    values = {"SKILLS": str(installed["skills"]), "PREFIX": str(installed["prefix"])}
    values[empty] = ""
    result = make("deploy-local", *(f"{k}={v}" for k, v in values.items()))
    assert (
        result.returncode != 0 and f"{empty} is empty" in result.stdout + result.stderr
    )
    assert (installed["skills"] / "symposium" / "SKILL.md").exists()  # nothing removed


def test_the_installed_skill_sets_up_a_member_with_no_repository(
    installed, admin_dir, cli, suite, tmp_path
):
    cli.ok(admin_dir, "roster", "add", "--handle", "lyra")
    invite = admin_dir / "lyra.invite"
    cli.ok(admin_dir, "invite", "--handle", "lyra", "--out", invite)

    # PATH holds the installed CLI's link, and a python3 with the CLI's requirements (the pip
    # fallback): no uv, and nothing from the repository
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (shim / "python3").chmod(0o755)
    env = {
        **suite.env,
        "PATH": os.pathsep.join(
            [str(installed["prefix"] / "bin"), str(shim), "/usr/bin", "/bin"]
        ),
    }
    member = tmp_path / "lyra"
    member.mkdir()
    skill = installed["skills"] / "symposium" / "scripts" / "main.py"
    result = subprocess.run(
        [sys.executable, str(skill), "setup", "--invite-file", str(invite)],
        cwd=member,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    joined = json.loads(result.stdout)
    assert result.returncode == 0, (joined, result.stderr)
    assert joined["registered"] is True and joined["handle"] == "lyra"
    # the installed toolchain validates against the suite's server: `validate` is
    # `publish --check`, which syncs first
    checked = subprocess.run(
        [
            sys.executable,
            str(skill),
            "validate",
            str(note(member, "lyra", "installed")),
        ],
        cwd=member,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "--check: validation passed" in checked.stdout
    assert (
        stat.S_IMODE(
            (installed["prefix"] / "share" / "symposium-data" / "symposium-data")
            .stat()
            .st_mode
        )
        == 0o755
    )
