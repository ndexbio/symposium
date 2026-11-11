"""Installing the `symposium` package the way a skill built on Symposium installs it.

Not from an index: from the bundle, which is the only copy whose version matches the Symposium
skill beside it. So this builds the bundle, extracts it, and installs out of the extracted tree
into a throwaway environment — the path a dependent skill's first command takes.

It reaches PyPI for `cryptography` and `keyring`, which is why it sits outside the suites that
run without a network. `make test` runs it; `make test DOCKER=false` does not.
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from suite import REPO

TOOLCHAIN = "skills/symposium/toolchain"


@pytest.fixture(scope="module")
def installed(tmp_path_factory) -> Path:
    """A throwaway environment holding the package, installed from an extracted bundle."""
    root = tmp_path_factory.mktemp("install")
    bundle = root / "Symposium_skill.zip"
    built = subprocess.run(
        [sys.executable, str(REPO / "tools" / "bundle.py"), str(bundle)],
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    with zipfile.ZipFile(bundle) as zf:
        zf.extractall(root / "extracted")
    base = root / "extracted" / TOOLCHAIN
    environment = root / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / "bin" / "python"
    if not python.exists():  # Windows
        python = environment / "Scripts" / "python.exe"
    # Both local projects in one call: `symposium` requires `symposium-rules`, and naming them
    # together is what lets pip satisfy that from the sibling it is already installing rather
    # than looking for it on an index.
    install = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            str(base / "tools"),
            str(base / "tools" / "sdk"),
        ],
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    return python


def ran(python: Path, code: str) -> str:
    result = subprocess.run([str(python), "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_the_package_and_the_rules_it_depends_on_both_install(installed):
    """`symposium-rules` is depended on rather than absorbed, because the data server takes it
    as a path dependency; installing from the bundle has to bring both."""
    assert (
        ran(
            installed,
            "import symposium, symposium_rules, cryptography, keyring;print('ok')",
        )
        == "ok"
    )


def test_the_public_api_is_importable_from_the_installed_package(installed):
    names = ran(
        installed,
        "import symposium; print(' '.join(sorted(symposium.__all__)))",
    )
    assert names.split() == [
        "Record",
        "Result",
        "Session",
        "SessionError",
        "Sessions",
        "ToolchainError",
        "validate",
    ]


def test_the_validator_is_the_one_the_gate_runs(installed):
    """`validate` is `symposium_rules.validate`, resolved on first use — the same function the
    gate applies, not a copy of it."""
    assert (
        ran(
            installed,
            "from symposium import validate;"
            "import symposium_rules.validate as r;"
            "print(validate is r.validate)",
        )
        == "True"
    )


def test_a_session_resolves_from_outside_the_skills_own_process(installed, tmp_path):
    """The point of packaging this: a skill that is not the Symposium skill lands on the same
    session, without reaching into ~/.symposium itself."""
    root = tmp_path / ".symposium"
    context = root / "member" / "demo" / "agent_lyra" / ".symposium"
    context.mkdir(parents=True)
    (context / "context.json").write_text(
        json.dumps(
            {
                "community": "demo",
                "handle": "agent_lyra",
                "home": "demo",
                "access": {},
            }
        )
    )
    label = ran(
        installed,
        "from pathlib import Path; from symposium.session import Sessions;"
        f"print(Sessions(root=Path({str(root)!r})).chosen().label())",
    )
    assert label == "demo/agent_lyra"
