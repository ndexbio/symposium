"""The `symposium` package: what a skill built on Symposium imports.

Each case runs against a stand-in Symposium skill, so nothing here needs a server, a network or
the repository's own layout — which is the point, since the package is what runs on someone
else's machine beside someone else's skill.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from suite import REPO

sys.path.insert(0, str(REPO / "tools" / "sdk"))

from symposium import record as record_module  # noqa: E402
from symposium import session as session_module  # noqa: E402
from symposium import toolchain  # noqa: E402

TOOL = """import json, os, sys
print(json.dumps({"argv": sys.argv[1:], "cli": os.environ.get("SYMPOSIUM_DATA_CLI"),
                  "cwd": os.getcwd()}))
sys.exit(int(os.environ.get("STAND_IN_EXIT", "0")))
"""


@pytest.fixture
def skill(tmp_path) -> Path:
    """A stand-in installed Symposium skill: what `skill_root` looks for, and tools that report
    how they were called instead of doing anything."""
    skill = tmp_path / "skills" / "symposium"
    tools = skill / "toolchain" / "tools"
    tools.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: symposium\n---\n")
    (skill / "scripts").mkdir()
    for name in ("publish.py", "sync.py"):
        (tools / name).write_text(TOOL)
    return skill


@pytest.fixture
def session(tmp_path) -> Path:
    """A session directory that has had a `/symposium` command run in it once."""
    directory = tmp_path / "session"
    (directory / ".symposium").mkdir(parents=True)
    (directory / ".symposium" / "runtime.json").write_text(
        json.dumps({"cli": ["/stand-in/python", "/stand-in/cli.py"]}) + "\n"
    )
    return directory


def member(root: Path, community: str, handle: str) -> Path:
    directory = root / "member" / community / handle / ".symposium"
    directory.mkdir(parents=True)
    (directory / "context.json").write_text(
        json.dumps(
            {"community": community, "handle": handle, "home": community, "access": {}}
        )
    )
    return directory.parent


# ── the bare-interpreter rule ────────────────────────────────────────────────────────────


def test_importing_the_package_reaches_nothing_a_bare_interpreter_lacks():
    """The skill's own scripts and the toolchain's tools run with no virtual environment, so
    importing this package must not need `cryptography`, `keyring` or `symposium_rules`. They
    are resolved on first use instead, and the shim at the skill's historical import path
    depends on that."""
    probe = (
        f"import sys; sys.path.insert(0, {str(REPO / 'tools' / 'sdk')!r});"
        "import symposium;"
        "from symposium import agent_process;"
        "print([m for m in ('cryptography', 'keyring', 'symposium_rules')"
        " if m in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout


def test_the_public_names_are_the_ones_promised():
    """What `__all__` names is what a skill built on this may depend on; everything else is
    free to change, so the list is asserted rather than left to drift."""
    import symposium

    assert sorted(symposium.__all__) == [
        "Record",
        "Result",
        "Session",
        "SessionError",
        "Sessions",
        "ToolchainError",
        "validate",
    ]
    for name in symposium.__all__:
        assert getattr(symposium, name) is not None, name


# ── finding the installed skill ──────────────────────────────────────────────────────────


def test_the_skill_is_found_where_it_is_named(skill, monkeypatch):
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(skill))
    assert toolchain.skill_root() == skill
    assert toolchain.base(skill) == skill / "toolchain"


def test_the_skill_is_found_beside_the_one_asking(skill, monkeypatch):
    """Skills install as siblings, so a package installed into one finds the other without
    being told where it is."""
    monkeypatch.delenv("SYMPOSIUM_SKILL_DIR", raising=False)
    monkeypatch.setattr(
        toolchain,
        "_candidates",
        lambda: [skill.parent / "symposium"],
    )
    assert toolchain.skill_root() == skill


def test_no_skill_says_every_path_it_tried(tmp_path, monkeypatch):
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(toolchain.ToolchainError) as refused:
        toolchain.skill_root()
    assert "not installed beside this one" in refused.value.report["error"]
    assert refused.value.report["searched"] == [str(tmp_path / "nowhere")]


# ── running its tools ────────────────────────────────────────────────────────────────────


def test_a_tool_runs_in_the_session_with_its_recorded_cli(skill, session, monkeypatch):
    """The session records the CLI command the Symposium skill built; this package reads it
    rather than building a virtual environment of its own."""
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(skill))
    code, output = toolchain.run("sync.py", [], session)
    assert code == 0
    reported = json.loads(output)
    assert reported["cli"] == json.dumps(["/stand-in/python", "/stand-in/cli.py"])
    assert Path(reported["cwd"]).resolve() == session.resolve()


def test_a_session_with_no_recorded_cli_is_refused(skill, tmp_path, monkeypatch):
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(skill))
    bare = tmp_path / "unprepared"
    bare.mkdir()
    with pytest.raises(toolchain.ToolchainError) as refused:
        toolchain.run("sync.py", [], bare)
    assert "no data-server CLI yet" in refused.value.report["error"]


def test_a_missing_tool_names_what_it_looked_for(skill, session, monkeypatch):
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(skill))
    with pytest.raises(toolchain.ToolchainError) as refused:
        toolchain.run("gate.py", [], session)
    assert "has no gate.py" in refused.value.report["error"]


# ── the session's own methods ────────────────────────────────────────────────────────────


def test_check_and_publish_differ_only_by_uploading(skill, session, monkeypatch):
    """`--check` is the same validation the gate runs, against the same record, and uploads
    nothing: the one difference on the command line is the one difference in what happens."""
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(skill))
    held = session_module.Session(session, "demo", "agent_lyra", "demo", {})
    checked = json.loads(held.check("a.json", role="importer").output)["argv"]
    published = json.loads(held.publish("a.json", role="importer").output)["argv"]
    assert checked == ["--role", "importer", "--check", "a.json"]
    assert published == ["--role", "importer", "a.json"]


def test_a_refused_artifact_is_an_answer_rather_than_an_exception(
    skill, session, monkeypatch
):
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(skill))
    monkeypatch.setenv("STAND_IN_EXIT", "1")
    held = session_module.Session(session, "demo", "agent_lyra", "demo", {})
    answer = held.check("a.json", role="importer")
    assert not answer.ok and answer.code == 1 and answer.output


def test_publishing_without_a_role_passes_none(skill, session, monkeypatch):
    monkeypatch.setenv("SYMPOSIUM_SKILL_DIR", str(skill))
    held = session_module.Session(session, "demo", "agent_lyra", "demo", {})
    assert json.loads(held.publish("a.json").output)["argv"] == ["a.json"]


# ── the record ───────────────────────────────────────────────────────────────────────────


def test_the_record_reads_artifacts_and_ignores_everything_else(tmp_path):
    """An artifact is recognised by its shape, so the tools' own state files stay out without
    having to be named."""
    directory = tmp_path / "record"
    directory.mkdir()
    (directory / "agent_lyra_importer_pub_v1.json").write_text(
        json.dumps({"artifact": {"name": "agent_lyra_importer_pub_v1"}, "objects": []})
    )
    (directory / "manifest.json").write_text(json.dumps({"build": 3}))
    (directory / ".sync_state.json").write_text(json.dumps({"cursor": "x"}))
    (directory / "broken.json").write_text("{not json")
    held = record_module.Record(directory)
    assert held.names() == {"agent_lyra_importer_pub_v1"}
    assert len(held) == 1


def test_a_record_never_synced_reads_as_empty(tmp_path):
    assert record_module.Record(tmp_path / "absent").artifacts() == []


# ── what the package depends on staying put ──────────────────────────────────────────────


def test_the_role_contracts_resolve_from_the_shipped_tree():
    """`publish.py` reads its role contracts from `roles/*.md` beside itself, which is why they
    stay in the toolchain rather than moving into the package. A skill that publishes as
    `importer` is relying on this, so it is asserted rather than assumed — and on the bare
    interpreter the tools actually run with."""
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "publish.py"), "--roles", "importer"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert '"may_import": true' in result.stdout
    for publishable in ("Argument", "Data", "ScientificPublication"):
        assert f'"{publishable}"' in result.stdout


# ── resolving a session ──────────────────────────────────────────────────────────────────


def test_the_only_session_on_a_machine_is_the_one_chosen(tmp_path):
    root = tmp_path / ".symposium"
    member(root, "demo", "agent_lyra")
    chosen = session_module.Sessions(root=root).chosen()
    assert chosen.label() == "demo/agent_lyra"
    assert chosen.record.directory == chosen.directory / "record"


def test_several_sessions_and_no_choice_lists_them(tmp_path):
    root = tmp_path / ".symposium"
    member(root, "demo", "agent_lyra")
    member(root, "demo", "agent_vega")
    with pytest.raises(session_module.SessionError) as refused:
        session_module.Sessions(root=root).chosen()
    assert "several Symposium sessions" in refused.value.report["error"]
    assert len(refused.value.report["sessions"]) == 2
