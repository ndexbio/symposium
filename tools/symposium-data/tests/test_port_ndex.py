"""#20 stage 2: `port-ndex` through the CLI (R-M1), against the recorded NDEx 3.0.0 responses
served by the shared stub, and what an admin does with a ported community: read it, purge a
version, export it and import it again (R-J6)."""

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

from conftest import CLI, community_file
from fixtures.ndex_port.stub import CREDENTIALS, NdexStub


def credentials_file(directory: Path, mode: int = 0o600) -> Path:
    path = directory / "ndex-credentials.json"
    path.write_text(json.dumps(CREDENTIALS))
    path.chmod(mode)
    return path


def port(cli, directory: Path, stub: NdexStub, *extra):
    return cli(
        directory,
        "port-ndex",
        credentials_file(directory),
        "--ndex-url",
        stub.url,
        "--page-size",
        4,
        *extra,
    )


def admin_on(server, cli, directory: Path, community: str, create: bool = True) -> Path:
    directory.mkdir(exist_ok=True)
    cli.ok(
        directory,
        "context",
        "set",
        "--community-file",
        community_file(directory, server, community),
    )
    if create:
        cli.ok(directory, "communities", "create", "--name", community)
    return directory


def ported(cli, admin_dir) -> list:
    stub = NdexStub()
    try:
        code, out = port(cli, admin_dir, stub)
    finally:
        stub.close()
    assert code == 0, out
    return cli.ok(admin_dir, "changes", "--collection", "record", "--limit", 100)[
        "items"
    ]


def test_the_port_fills_the_context_community(admin_dir, cli):
    stub = NdexStub()
    try:
        code, view = port(cli, admin_dir, stub)
    finally:
        stub.close()
    assert code == 0, view
    assert view["state"] == "ok" and view["requested_by"] == "demo-admin"
    result = view["result"]
    assert (result["networks"], result["record"], result["replies"]) == (10, 9, 1)
    assert (
        result["pages"] == 3 and stub.listing_pages == 3
    )  # 10 networks at page size 4
    record = cli.ok(admin_dir, "changes", "--collection", "record")["items"]
    assert len(record) == 9 and [i["seq"] for i in record] == list(range(1, 10))
    roster = cli.ok(admin_dir, "roster", "list")["roster"]
    assert [m["handle"] for m in roster] == ["lyra", "vega"]


def test_port_refusals_are_reported_with_their_reasons(
    server, admin_dir, cli, tmp_path
):
    stub = NdexStub()
    try:
        nowhere = admin_on(server, cli, tmp_path / "nowhere", "nowhere", create=False)
        code, out = port(cli, nowhere, stub)
        assert code == 1 and out["status"] == 404

        loose = credentials_file(tmp_path, mode=0o644)
        code, out = cli(admin_dir, "port-ndex", loose, "--ndex-url", stub.url)
        assert code == 1 and "chmod 600" in out["error"]
        assert stub.requests == 0  # refused before the data server or NDEx is asked

        assert port(cli, admin_dir, stub)[0] == 0
        code, out = port(cli, admin_dir, stub)
        assert code == 1 and out["status"] == 400 and "holds files" in out["error"]
    finally:
        stub.close()


def test_a_collision_with_the_admins_handle_fails_the_port(server, cli, tmp_path):
    from fixtures.ndex_port.stub import FIXTURES, attributes

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
    directory = admin_on(server, cli, tmp_path / "collide", "collide")
    try:
        code, out = port(cli, directory, stub)
    finally:
        stub.close()
    assert code == 1 and out["error"] == "the port-ndex failed: handle collision"
    assert out["port"]["state"] == "failed"


def test_only_one_port_runs_at_a_time(server, admin_dir, cli, tmp_path):
    other = admin_on(server, cli, tmp_path / "other", "other")
    stub = NdexStub(hold=True)
    first = subprocess.Popen(
        [sys.executable, str(CLI), "port-ndex", str(credentials_file(admin_dir))]
        + ["--ndex-url", stub.url, "--page-size", "4"],
        cwd=admin_dir,
        env=cli.env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert stub.held.wait(timeout=30), "the first port never reached the listing"
        code, out = port(cli, other, stub)
        assert code == 1 and out["status"] == 409
        stub.released.set()
        stdout, _ = first.communicate(timeout=60)
        assert json.loads(stdout)["state"] == "ok"
    finally:
        stub.close()
        first.kill()


def test_a_ported_version_can_be_purged(admin_dir, cli):
    record = ported(cli, admin_dir)
    cite = record[0]["citation"]
    purged = cli.ok(admin_dir, "purge", "--cite", cite)
    assert purged == {"purged": cite, "bytes_freed": True}
    assert cli.ok(admin_dir, "stat", cite)["purged"] is True
    code, out = cli(admin_dir, "get", cite, "--out", admin_dir / "gone.json")
    assert code == 1 and out["status"] == 410 and not (admin_dir / "gone.json").exists()
    kept = record[1]["citation"]
    got = cli.ok(admin_dir, "get", kept, "--out", admin_dir / "kept.json")
    assert got["sha256"] == record[1]["sha256"] and got["citation"] == kept
    versions = cli.ok(admin_dir, "versions", record[1]["file_id"])
    assert [v["version"] for v in versions["versions"]] == [1]


def rewritten(source: Path, out: Path, old: str, new: str) -> Path:
    """A copy of an export with text replaced in its rows (not its payloads)."""
    with tarfile.open(source) as src, tarfile.open(out, "w") as dst:
        for member in src.getmembers():
            data = src.extractfile(member).read()
            if not member.name.startswith("payloads/"):
                data = data.decode().replace(old, new).encode()
                member.size = len(data)
            dst.addfile(member, io.BytesIO(data))
    return out


def test_a_ported_community_exports_and_imports(server, admin_dir, cli, tmp_path):
    before = ported(cli, admin_dir)
    archive = admin_dir / "demo.tar"
    exported = cli.ok(admin_dir, "export", "--out", archive)
    assert (
        exported["exported"] == "demo" and exported["bytes"] == archive.stat().st_size
    )
    assert archive.stat().st_mode & 0o077 == 0
    server.reset()

    target = tmp_path / "target"
    target.mkdir()
    wrong = community_file(target, server, "elsewhere")
    code, out = cli(target, "import", "--from", archive, "--community-file", wrong)
    assert code == 1 and "'demo'" in out["error"] and "'elsewhere'" in out["error"]

    right = community_file(target, server, "demo")
    report = cli.ok(target, "import", "--from", archive, "--community-file", right)
    assert report["imported"] == "demo"
    assert cli.ok(target, "context", "show")["context"]["community"] == "demo"
    after = cli.ok(target, "changes", "--collection", "record")["items"]
    assert [(i["citation"], i["sha256"]) for i in after] == [
        (i["citation"], i["sha256"]) for i in before
    ]

    code, out = cli(target, "import", "--from", archive, "--community-file", right)
    assert code == 1 and out["status"] == 409 and "already exists" in out["error"]

    server.reset()
    collision = rewritten(archive, tmp_path / "collision.tar", '"lyra"', '"demo-admin"')
    code, out = cli(target, "import", "--from", collision, "--community-file", right)
    assert code == 1 and out["status"] == 409 and "handle collision" in out["error"]
