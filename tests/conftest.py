"""The top-level test suite's lifecycle (tests/suite.py): setUp once before any test, tearDown
once after the last, and the fixtures its tests share."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from suite import Suite, community_file

ROOT = pytest.StashKey[Path]()


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """The suite's one directory under /tmp; pytest's own temporary paths live inside it, so
    deleting it at the end leaves nothing from the run behind."""
    root = Path(tempfile.mkdtemp(prefix="symposium-suite-", dir="/tmp"))
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
    try:
        suite.set_up()
        yield suite
    finally:
        suite.tear_down()


@pytest.fixture(scope="session")
def server(suite):
    return suite.server


@pytest.fixture(scope="session")
def cli(suite):
    return suite.cli


@pytest.fixture(scope="session")
def skill(suite):
    return suite.skill


@pytest.fixture(autouse=True)
def clean_slate(suite):
    """Every test starts from an empty, operational server; the admin binding stays."""
    suite.server.reset()
    yield


@pytest.fixture
def admin_dir(tmp_path, server, cli) -> Path:
    """A working directory whose context is the admin's, on an existing `demo` community."""
    cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    cli.ok(tmp_path, "communities", "create", "--name", "demo")
    return tmp_path
