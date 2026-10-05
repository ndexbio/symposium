"""#21 stage 1: the member's side of the workflow on the data server: `publish.py` submits into
the community's `inbox` (R-G3), and `sync.py` keeps the session's copy of the record (`./record`)
current from the `record` feed and lists the gate's replies. The gate's part (promote, reply)
is done here by the admin through the CLI, as stage 2's gate will do it."""

import json
import subprocess
import sys
from pathlib import Path

from suite import REPO, enroll

TOOLS = REPO / "tools"


def tool(suite, cwd: Path, script: str, *args) -> tuple[int, str]:
    """Run a toolchain script the way the skill will: in the session's directory."""
    result = subprocess.run(
        [sys.executable, str(TOOLS / script), *map(str, args)],
        cwd=cwd,
        env=suite.env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode, result.stdout + result.stderr


def note(directory: Path, handle: str, topic: str) -> Path:
    """A small, valid artifact for `handle` to publish."""
    name = f"{handle}_note_{topic}_v1"
    path = directory / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "artifact": {
                    "name": name,
                    "type": "NonGroundable",
                    "specification_version": "1.0",
                    "published_by": f"@{handle}",
                    "created": None,
                    "title": f"A note on {topic}",
                    "authors": [handle],
                    "text": f"A short note on {topic}, for the workflow tests.",
                },
                "objects": [],
                "relationships": [],
            }
        )
    )
    return path


def submissions(cli, directory: Path) -> list:
    return cli.ok(directory, "changes", "--collection", "inbox", "--all")["items"]


def accept(cli, admin_dir: Path, submission: dict) -> dict:
    """What the gate does on acceptance: promote into `record`, stamping the server's clock."""
    name = submission["name"].split("@")[0]
    return cli.ok(
        admin_dir,
        "promote",
        submission["citation"],
        "--collection",
        "record",
        "--name",
        name,
        "--metadata",
        '{"symposium_record": true}',
        "--stamp-json-pointer",
        "/artifact/created",
    )


def test_publish_check_needs_the_data_server(suite, admin_dir, cli):
    # nothing validates offline: `--check` syncs first, and stops when the server is unreachable
    lyra = enroll(cli, admin_dir, "lyra")
    context = lyra / ".symposium" / "context.json"
    unreachable = json.loads(context.read_text())
    unreachable["data-server-url"] = "http://127.0.0.1:9"  # nothing answers there
    context.write_text(json.dumps(unreachable))
    code, out = tool(suite, lyra, "publish.py", "--check", note(lyra, "lyra", "check"))
    assert code == 1 and "could not be reached" in out and "nothing was checked" in out
    assert "spec ok" not in out


def test_publish_validates_against_the_record_as_it_stands_now(suite, admin_dir, cli):
    # vega never ran sync after lyra's note was accepted; publish syncs first, so vega's note
    # citing it resolves, and vega's copy of the record now holds it
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "seed"))[0] == 0
    accept(cli, admin_dir, submissions(cli, admin_dir)[0])
    citing = note(vega, "vega", "reply")
    artifact = json.loads(citing.read_text())
    artifact["artifact"]["text"] = "Following [lyra's note](@lyra_note_seed_v1)."
    citing.write_text(json.dumps(artifact))
    code, out = tool(suite, vega, "publish.py", "--check", citing)
    assert code == 0, out
    assert (vega / "record" / "lyra_note_seed_v1.json").exists()


def test_publish_submits_into_inbox_for_the_admin_only(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    code, out = tool(suite, lyra, "publish.py", note(lyra, "lyra", "inbox"))
    assert code == 0, out
    assert "submitted  symposium-data:" in out

    [item] = submissions(cli, admin_dir)
    assert item["name"].startswith("lyra_note_inbox_v1@")
    assert item["metadata"] == {"symposium_submission": True}
    assert item["created_by"] == "lyra"
    assert submissions(cli, vega) == []  # another member never sees it

    code, out = tool(suite, lyra, "publish.py", note(lyra, "vega", "not_mine"))
    assert (
        code == 1
        and "name must be prefixed 'lyra_'" in out
        and "nothing uploaded" in out
    )


def test_sync_applies_the_record_in_order_and_is_idempotent(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    for topic in ("first", "second"):
        assert tool(suite, lyra, "publish.py", note(lyra, "lyra", topic))[0] == 0
    for submission in submissions(cli, admin_dir):
        accept(cli, admin_dir, submission)

    code, out = tool(suite, vega, "sync.py")
    assert code == 0, out
    assert "+2: lyra_note_first_v1, lyra_note_second_v1" in out
    held = {
        p.stem: json.loads(p.read_text()) for p in (vega / "record").glob("lyra_*.json")
    }
    assert sorted(held) == ["lyra_note_first_v1", "lyra_note_second_v1"]
    first, second = (held[n]["artifact"]["created"] for n in sorted(held))
    assert (
        first and second and first < second
    )  # the server's clock, stamped on acceptance
    manifest = json.loads((vega / "record" / "manifest.json").read_text())
    assert manifest["build"] == 1 and manifest["artifacts"] == 2

    code, out = tool(suite, vega, "sync.py")
    assert code == 0 and "up to date — 2 artifact(s)" in out


def test_sync_lists_a_reply_only_to_its_recipient(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    reply = admin_dir / "reply.json"
    reply.write_text(json.dumps({"reply": "rejected"}))
    cli.ok(
        admin_dir,
        "put",
        reply,
        "--collection",
        "inbox",
        "--name",
        "demo-admin_REPLY_lyra_note_x_v1@2026-10-04T00:00:00Z",
        "--metadata",
        json.dumps(
            {
                "symposium_reply": True,
                "symposium_in_reply_to": "lyra_note_x_v1",
                "recipients": ["lyra"],
            }
        ),
    )
    code, out = tool(suite, lyra, "sync.py")
    assert code == 0 and "reply from the gate: demo-admin_REPLY_lyra_note_x_v1" in out
    assert "(re lyra_note_x_v1)" in out
    code, out = tool(suite, lyra, "sync.py")
    assert code == 0 and "reply from the gate" not in out  # listed once
    code, out = tool(suite, vega, "sync.py")
    assert code == 0 and "reply from the gate" not in out


def test_sync_reports_an_unreachable_server_and_keeps_the_copy(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    assert tool(suite, lyra, "sync.py")[0] == 0
    context = lyra / ".symposium" / "context.json"
    unreachable = json.loads(context.read_text())
    unreachable["data-server-url"] = "http://127.0.0.1:9"
    context.write_text(json.dumps(unreachable))
    code, out = tool(suite, lyra, "sync.py")
    assert (
        code == 1 and "COULD NOT REACH THE SERVER" in out and "may now be STALE" in out
    )


def test_setup_syncs_the_record_after_registering(suite, admin_dir, cli, skill):
    lyra = enroll(cli, admin_dir, "lyra")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "seed"))[0] == 0
    accept(cli, admin_dir, submissions(cli, admin_dir)[0])

    cli.ok(admin_dir, "roster", "add", "--handle", "vega")
    invite = admin_dir / "vega.invite"
    cli.ok(admin_dir, "invite", "--handle", "vega", "--out", invite)
    vega = admin_dir / "vega"
    vega.mkdir()
    joined = skill.ok(vega, "setup", "--invite-file", invite)
    assert joined["registered"] is True and joined["record"]["artifacts"] == 1
    assert (vega / "record" / "lyra_note_seed_v1.json").exists()


def test_an_address_to_a_member_who_has_not_published_resolves(suite, admin_dir, cli):
    # vega is on the roster and invited, but has never published or even joined: `@vega` must
    # still resolve in `publish --check`, through the live roster, as it will at the gate
    lyra = enroll(cli, admin_dir, "lyra")
    cli.ok(admin_dir, "roster", "add", "--handle", "vega")
    cli.ok(admin_dir, "invite", "--handle", "vega", "--out", admin_dir / "vega.invite")
    message = lyra / "lyra_msg_hello_v1.json"
    message.write_text(
        json.dumps(
            {
                "artifact": {
                    "name": "lyra_msg_hello_v1",
                    "type": "Message",
                    "specification_version": "1.0",
                    "published_by": "@lyra",
                    "created": None,
                    "title": "Hello",
                    "recipients": ["@vega"],
                    "text": "A message to a member who has not published yet.",
                },
                "objects": [],
                "relationships": [],
            }
        )
    )
    code, out = tool(suite, lyra, "publish.py", "--check", message)
    assert code == 0, out  # the live roster names vega; nothing is kept for offline use
    assert not (lyra / "record" / ".roster.json").exists()
