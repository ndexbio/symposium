"""The Docker commands of SKILL.md's "Running a local data server", run as written against real
containers of the suite's own (named sdtest-*, never the local data server's): what the steps
read from them is what the steps say it is."""

import shlex
import uuid

import pytest
from harness import IMAGE, VERSION, docker
from skills.test_local_server_docs import CONTAINER, commands, section


def written(marker: str, container: str) -> list:
    """The arguments of the section's one Docker command holding `marker`, on `container`."""
    (command,) = [c for c in commands(section()) if marker in c]
    return shlex.split(command.replace(CONTAINER, container))[1:]


@pytest.fixture
def created(server):
    """A container created from the image under test and never started. Like the suite's
    server, it needs Docker."""
    name = f"sdtest-{uuid.uuid4().hex[:10]}"
    docker("create", "--name", name, IMAGE)
    try:
        yield name
    finally:
        docker("rm", "-f", name, check=False)


def test_the_image_command_prints_the_image_a_container_was_created_from(
    server, created
):
    for container in (server.name, created):
        found = docker(*written("{{.Config.Image}}", container))
        assert found.stdout.strip() == IMAGE  # character for character, tag included


def test_the_state_command_tells_running_from_stopped(server, created):
    assert docker(*written("{{.State.Running}}", server.name)).stdout.strip() == "true"
    assert docker(*written("{{.State.Running}}", created)).stdout.strip() == "false"
    # the section's own start command is what makes a stopped one run
    docker(*written("docker start", created))
    assert docker(*written("{{.State.Running}}", created)).stdout.strip() == "true"


def test_the_image_command_fails_for_no_such_container(server):
    absent = f"sdtest-{uuid.uuid4().hex[:10]}"
    result = docker(*written("{{.Config.Image}}", absent), check=False)
    assert result.returncode != 0 and result.stdout.strip() == ""
    assert "no such container" in result.stderr.lower()


def test_the_remove_command_removes_the_container_alone(created):
    docker(*written("docker rm -f", created))
    result = docker(*written("{{.Config.Image}}", created), check=False)
    assert "no such container" in result.stderr.lower()
    assert docker("image", "inspect", "--format", "{{.Id}}", IMAGE).stdout.strip()


def test_the_status_check_reports_the_version_the_image_is_tagged(
    server, skill, tmp_path
):
    """Step 6: the status command of the section, with no session, on the suite's server."""
    text = " ".join(section().split())
    assert "`/symposium data status --data-server-url http://127.0.0.1:8790`" in text
    status = skill.ok(tmp_path, "data", "status", "--data-server-url", server.url)
    assert status["version"] == VERSION == IMAGE.rsplit(":", 1)[1]
