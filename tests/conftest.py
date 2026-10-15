"""The top-level test suite's lifecycle (tests/suite.py): setUp once before any test, tearDown
once after the last, and the fixtures its tests share.

With SYMPOSIUM_TEST_DOCKER=false (`make test DOCKER=false`, CI's Windows job) no container is
started: the suites that need none run in full, and a test that asks for the server is skipped."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from suite import Suite, community_file

ROOT = pytest.StashKey[Path]()
DOCKER = os.environ.get("SYMPOSIUM_TEST_DOCKER", "true") != "false"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """The suite's one directory, in the platform's temporary directory; pytest's own temporary
    paths live inside it, so deleting it at the end leaves nothing from the run behind."""
    root = Path(tempfile.mkdtemp(prefix="symposium-suite-"))
    config.option.basetemp = str(root / "tmp")
    config.stash[ROOT] = root


def pytest_unconfigure(config):
    root = config.stash.get(ROOT, None)
    if root is not None:
        Suite(root).purge()


@pytest.fixture(scope="session", autouse=True)
def suite(request) -> Suite:
    """setUp before the first test, tearDown after the last, whatever the tests did."""
    suite = Suite(request.config.stash[ROOT])
    if not DOCKER:
        yield suite  # no container: only the suites that need none run
        return
    try:
        suite.set_up()
        yield suite
    finally:
        suite.tear_down()


def needs_docker():
    if not DOCKER:
        pytest.skip("needs Docker")


@pytest.fixture(scope="session")
def server(suite):
    needs_docker()
    return suite.server


@pytest.fixture(scope="session")
def cli(suite):
    needs_docker()
    return suite.cli


@pytest.fixture(scope="session")
def skill(suite):
    needs_docker()
    return suite.skill


@pytest.fixture(autouse=True)
def clean_slate(suite):
    """Every test starts from an empty, operational server and no skill sessions on the suite's
    machine; the admin binding and the keystore stay."""
    if suite.server is not None:
        suite.server.reset()
    for sessions in ("admin", "member", "current"):
        shutil.rmtree(suite.home / ".symposium" / sessions, ignore_errors=True)
    yield


@pytest.fixture
def admin_dir(tmp_path, server, cli) -> Path:
    """A working directory whose context is the admin's, on an existing `demo` community."""
    cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    cli.ok(tmp_path, "communities", "create", "--name", "demo")
    return tmp_path
