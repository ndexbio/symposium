"""The skill's Python runtime (R-I7): the CLI's environment, `<skill>/.venv`, is built once per
machine and recorded once per agent session; a later command in the session only reads the
record. Each case runs on a stand-in skill whose CLI needs no packages, so a real environment
is built with `venv` and pip without the network."""

import json
import shutil
import sys
from pathlib import Path

import pytest
from suite import REPO

sys.path.insert(0, str(REPO / "skills" / "symposium" / "scripts"))

from runtime import STAMP, Runtime, RuntimeUnavailable  # noqa: E402


@pytest.fixture
def skill(tmp_path) -> Path:
    skill = tmp_path / "skill"
    cli = skill / "toolchain" / "tools" / "symposium-data"
    cli.mkdir(parents=True)
    (cli / "cli.py").write_text("print('{}')\n")
    (cli / "requirements.txt").write_text("")
    return skill


def runtime(skill: Path, session: Path, **options) -> Runtime:
    cli = skill / "toolchain" / "tools" / "symposium-data" / "cli.py"
    return Runtime(skill, cli, session=session, **options)


def session(tmp_path, name: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    return directory


def test_a_sessions_first_command_builds_the_environment_and_records_it(
    skill, tmp_path
):
    lyra = session(tmp_path, "lyra")
    built = runtime(skill, lyra)
    command = built.command()
    python = built.interpreter(skill / ".venv")
    assert command == [
        str(python),
        str(skill / "toolchain/tools/symposium-data/cli.py"),
    ]
    assert python.exists() and (skill / ".venv" / STAMP).exists()
    assert json.loads((lyra / ".symposium" / "runtime.json").read_text()) == {
        "cli": command
    }
    assert not list(skill.glob(".venv-*"))  # built beside its place, renamed in


def test_a_later_command_only_reads_the_record(skill, tmp_path, monkeypatch):
    lyra = session(tmp_path, "lyra")
    first = runtime(skill, lyra).command()

    def refuse(*_):
        raise AssertionError("a later command must not check or build the environment")

    monkeypatch.setattr(Runtime, "ensure_environment", refuse)
    monkeypatch.setattr(Runtime, "ready", refuse)
    assert runtime(skill, lyra).command() == first


def test_a_new_session_reuses_the_built_environment(skill, tmp_path, monkeypatch):
    runtime(skill, session(tmp_path, "lyra")).command()

    def refuse(*_):
        raise AssertionError("a built environment must not be built again")

    monkeypatch.setattr(Runtime, "run", refuse)
    vega = session(tmp_path, "vega")
    reused = runtime(skill, vega)
    assert reused.command()[0] == str(reused.interpreter(skill / ".venv"))
    assert (vega / ".symposium" / "runtime.json").exists()


def test_a_changed_requirements_file_rebuilds_the_environment(skill, tmp_path):
    runtime(skill, session(tmp_path, "lyra")).command()
    stamp = skill / ".venv" / STAMP
    before = stamp.read_text()
    requirements = skill / "toolchain/tools/symposium-data/requirements.txt"
    requirements.write_text("# a new pin\n")
    runtime(skill, session(tmp_path, "vega")).command()
    assert stamp.read_text() != before and not list(skill.glob(".venv-*"))


def test_a_reinstalled_skill_is_prepared_again_in_the_same_session(skill, tmp_path):
    lyra = session(tmp_path, "lyra")
    command = runtime(skill, lyra).command()
    shutil.rmtree(skill / ".venv")  # the skill reinstalled
    assert runtime(skill, lyra).command() == command
    assert Path(command[0]).exists()


def test_an_environment_that_cannot_be_built_says_what_is_needed(skill, tmp_path):
    lyra = session(tmp_path, "lyra")
    with pytest.raises(RuntimeUnavailable) as failed:
        runtime(skill, lyra, python=str(tmp_path / "no-such-python")).command()
    report = failed.value.report
    assert report["error"].startswith(
        "the skill could not create its Python environment"
    )
    assert "venv module" in report["needs"] and "PyPI" in report["needs"]
    assert not (lyra / ".symposium" / "runtime.json").exists()
    assert not (skill / ".venv").exists() and not list(skill.glob(".venv-*"))
