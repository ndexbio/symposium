"""`/symposium port` (port-ndex) as the skill's README describes it: bootstrap, port,
bootstrap again for the authors' invites; and the refusals it reports, against the recorded
NDEx 3.0.0 responses served by the shared stub."""

import json
import subprocess
import sys
from pathlib import Path

from fixtures.ndex_port.stub import CREDENTIALS, FIXTURES, NdexStub, attributes
from suite import ADMIN, SKILL, community_file


def credentials_file(directory: Path) -> Path:
    path = directory / "ndex-credentials.json"
    path.write_text(json.dumps(CREDENTIALS))
    path.chmod(0o600)
    return path


def bootstrap(
    skill, directory: Path, server, community: str = "demo", handles=()
) -> dict:
    spec = community_file(directory, server, community, handles)
    return skill.ok(directory, "bootstrap", "--community-file", spec)


def test_bootstrap_then_port_then_bootstrap_invites_the_authors(
    server, skill, tmp_path
):
    bootstrap(skill, tmp_path, server)
    stub = NdexStub()
    try:
        ported = skill.ok(tmp_path, "port", credentials_file(tmp_path), stub.url)
    finally:
        stub.close()
    assert ported["state"] == "ok"
    assert (ported["result"]["record"], ported["result"]["replies"]) == (9, 1)

    again = bootstrap(skill, tmp_path, server)
    assert sorted(Path(p).name for p in again["invite_files"]) == [
        "demo-lyra.invite",
        "demo-vega.invite",
    ]
    record = skill.ok(tmp_path, "data", "changes", "--collection", "record")["items"]
    assert len(record) == 9


def test_port_refusals_are_reported_with_their_reasons(
    server, skill, cli, suite, tmp_path
):
    stub = NdexStub()
    try:
        # a session for a community the server does not hold (one since removed)
        nowhere = suite.home / ".symposium" / "admin" / "nowhere"
        nowhere.mkdir(parents=True)
        cli.ok(
            nowhere,
            "context",
            "set",
            "--community-file",
            community_file(tmp_path, server, "nowhere"),
        )
        code, out = skill(tmp_path, "port", credentials_file(tmp_path), stub.url)
        assert code == 1 and out["status"] == 404

        bootstrap(skill, tmp_path, server)  # it makes demo's session the current one
        port = ("port", credentials_file(tmp_path), stub.url)
        assert skill(tmp_path, *port)[0] == 0
        code, out = skill(tmp_path, *port)
        assert code == 1 and out["status"] == 400 and "holds files" in out["error"]
    finally:
        stub.close()


def test_a_port_while_another_runs_is_refused(server, skill, tmp_path):
    first_dir, other_dir = tmp_path / "first", tmp_path / "other"
    for directory, community in ((first_dir, "demo"), (other_dir, "other")):
        directory.mkdir()
        bootstrap(skill, directory, server, community)
    stub = NdexStub(hold=True)
    skill.ok(first_dir, "use", "demo", ADMIN)
    first = subprocess.Popen(
        [
            sys.executable,
            str(SKILL),
            "port",
            str(credentials_file(first_dir)),
            stub.url,
        ],
        cwd=first_dir,
        env=skill.env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert stub.held.wait(timeout=30), "the first port never reached the listing"
        # switching now changes only the commands after it: the running port keeps demo's
        skill.ok(other_dir, "use", "other", ADMIN)
        code, out = skill(other_dir, "port", credentials_file(other_dir), stub.url)
        assert code == 1 and out["status"] == 409
        stub.released.set()
        stdout, _ = first.communicate(timeout=60)
        ported = json.loads(stdout)
        assert ported["state"] == "ok" and ported["session"] == f"demo/{ADMIN}"
    finally:
        stub.close()
        first.kill()


def test_a_collision_with_the_admins_handle_is_reported(server, skill, tmp_path):
    network = sorted((FIXTURES / "networks").glob("*.json"))[0]
    na = attributes(json.loads(network.read_text()))
    artifact = json.loads(na["symposium_canonical"])
    artifact["artifact"].update(
        name="admin_handle_note_v1",
        created="2026-10-02T23:00:00+00:00",
        published_by="@demo-admin",
    )
    copy = {**na, "symposium_canonical": json.dumps(artifact)}
    stub = NdexStub(extra_networks={"admin-handle": [{"networkAttributes": [copy]}]})
    bootstrap(skill, tmp_path, server)
    try:
        code, out = skill(tmp_path, "port", credentials_file(tmp_path), stub.url)
    finally:
        stub.close()
    assert code == 1 and out["error"] == "the port-ndex failed: handle collision"
