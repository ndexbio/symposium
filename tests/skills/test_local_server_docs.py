"""The local data server's instructions, as text: SKILL.md's "Running a local data server" is
the one place that gives its Docker commands, in one order, on the container, directory, URL
and image the skill names; every other document links there. No container is needed."""

import re
import subprocess
import sys

from suite import REPO

SKILL_MD = REPO / "skills" / "symposium" / "SKILL.md"
HEADING = "## Running a local data server"
ANCHOR = "#running-a-local-data-server"
CONTAINER = "symposium-data-local"
# a Docker command that acts on a container
DOCKER = re.compile(
    r"\bdocker (run|start|restart|rm|cp|logs|stop|kill|container inspect)\b"
)
# the data server's container, under either name
NAMED = re.compile(r"(?<![\w/-])symposium-data(-local)?\b(?![-/:])")
# the documents that say how to run a data server
LINKING = (
    "skills/symposium/README.md",
    "data-server/RUNBOOK.md",
    "data-server/README.md",
)


def section() -> str:
    """SKILL.md's "Running a local data server", up to the next heading of its level."""
    text = SKILL_MD.read_text()
    assert text.count(f"\n{HEADING}\n") == 1
    return text.split(f"\n{HEADING}\n", 1)[1].split("\n## ", 1)[0]


def commands(text: str) -> list:
    """The Docker commands of a text, one per line that starts with `docker`."""
    return [
        line.strip() for line in text.splitlines() if line.strip().startswith("docker ")
    ]


def markdown() -> list:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [name for name in out.stdout.split() if (REPO / name).is_file()]


def skill_main():
    sys.path.insert(0, str(SKILL_MD.parent / "scripts"))
    try:
        import main
    finally:
        sys.path.pop(0)
    return main


def test_the_section_gives_every_command_in_order():
    assert commands(section()) == [
        "docker container inspect --format '{{.Config.Image}}' " + CONTAINER,
        f"docker rm -f {CONTAINER}",
        "docker container inspect --format '{{.State.Running}}' " + CONTAINER,
        f"docker start {CONTAINER}",
        f"docker run -d --name {CONTAINER} --restart unless-stopped "
        "-p 127.0.0.1:8790:8080 -v $HOME/.symposium/data-server-local:/apps <IMAGE>",
        f"docker logs --tail 50 {CONTAINER}",
        f"docker cp <public_key_file> {CONTAINER}:/apps/",
        f"docker restart {CONTAINER}",
    ]
    # the status check sits between running the container and reading its logs
    text = section()
    run, status, logs = (
        text.index("docker run -d"),
        text.index("/symposium data status --data-server-url http://127.0.0.1:8790"),
        text.index("docker logs"),
    )
    assert run < status < logs


def test_the_image_comes_from_help_alone():
    text = section()
    first = text.split("\n1. ", 1)[1].split("\n2. ", 1)[0]
    assert "/symposium --help" in first and "`data_server_image`" in first
    assert "`<IMAGE>`" in first
    for command in commands(text):
        # an example may name a version; a command takes the image as <IMAGE> alone
        assert "<version>" not in command
        assert not re.search(r"ndexbio/symposium-data", command), command
    # a container is compared with it before it is used
    third = text.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    assert "`<FOUND>`" in third and "`<IMAGE>`" in third
    assert "character for character" in third


def test_the_section_names_what_the_skill_names():
    local = skill_main().data_server_local()
    text = section()
    assert local["container"] == CONTAINER
    assert (
        local["directory"].replace("\\", "/").endswith("/.symposium/data-server-local")
    )
    assert local["url"] == "http://127.0.0.1:8790"
    for value in (CONTAINER, "~/.symposium/data-server-local/", local["url"]):
        assert f"`{value}`" in text, value
    # every Docker command of the section acts on that container, and no other
    for command in commands(text):
        assert CONTAINER in command, command
        assert not NAMED.search(command.replace(CONTAINER, "")), command


def test_trouble_has_one_rule():
    text = section()
    assert "show the user Docker's message and stop" in " ".join(text.split())
    assert not re.search(r"\bnever\b", text, re.IGNORECASE)
