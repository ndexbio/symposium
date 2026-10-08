"""The gate on the data server. It reads the members' submissions from `inbox`,
validates them in a serial order, promotes each accepted one into `record` (the server stamps
`created`) or replies to its submitter, verifies every `download` held on the data server, and
keeps no decision only it knows: the record version or the reply names the submission it
decided, so a lost state file is rebuilt from the server."""

import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from skills.test_workflow import TOOLS, note, submissions, tool
from suite import enroll


def gate(suite, admin_dir: Path, *args) -> str:
    code, out = tool(suite, admin_dir, "gate.py", *args)
    assert code == 0, out
    return out


def records(cli, directory: Path) -> list:
    return cli.ok(directory, "changes", "--collection", "record", "--all")["items"]


def replies(cli, admin_dir: Path) -> list:
    return [
        i
        for i in submissions(cli, admin_dir)
        if (i.get("metadata") or {}).get("symposium_reply")
    ]


def submit(cli, member: Path, path: Path) -> dict:
    """A submission put straight into `inbox`, as publish would, but without its check: how
    the gate meets what publish would have refused, or an output sent before its Analysis."""
    name = json.loads(path.read_text())["artifact"]["name"]
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return cli.ok(
        member,
        "put",
        path,
        "--collection",
        "inbox",
        "--name",
        f"{name}@{when}",
        "--metadata",
        '{"symposium_submission": true}',
        "--content-type",
        "application/json",
    )


def artifact(directory: Path, header: dict, objects=()) -> Path:
    path = directory / f"{header['name']}.json"
    path.write_text(
        json.dumps(
            {
                "artifact": {
                    "specification_version": "1.0",
                    "published_by": "@lyra",
                    "created": None,
                    **header,
                },
                "objects": list(objects),
                "relationships": [],
            }
        )
    )
    return path


def analysis(directory: Path) -> Path:
    return artifact(
        directory,
        {
            "name": "lyra_analysis_count_v1",
            "type": "Analysis",
            "title": "Count",
            "description": "Counts the rows.",
            "procedure": "Count the rows of the input by hand.",
        },
    )


def output(directory: Path, name: str, location: str = "", sha256: str = "") -> Path:
    """A Data artifact produced by the Analysis, its full table behind a `download`."""
    content = {
        "name": "download",
        "type": "Content",
        "description": "The full table.",
        "addressing_method": "The whole file.",
        "groundable": True,
        "location": location or "the analyst's notebook",
        "access_method": "symposium-data get <location>",
    }
    if sha256:
        content["sha256"] = sha256
    return artifact(
        directory,
        {
            "name": name,
            "type": "Data",
            "title": "Counts",
            "description": "The counts, held in the file store.",
            "produced_by": "@lyra_analysis_count_v1",
        },
        [content],
    )


def test_an_accepted_submission_enters_the_record_and_reaches_every_member(
    suite, admin_dir, cli
):
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "seed"))[0] == 0
    [submission] = submissions(cli, admin_dir)

    out = gate(suite, admin_dir)
    assert "lyra_note_seed_v1" in out and "ACCEPTED" in out
    [stored] = records(cli, admin_dir)
    assert stored["name"] == "lyra_note_seed_v1" and stored["created_by"] == "lyra"
    assert stored["metadata"] == {
        "symposium_submission": True,
        "symposium_record": True,
        "symposium_submission_citation": submission["citation"],
    }
    held = json.loads((admin_dir / "record" / "lyra_note_seed_v1.json").read_text())
    assert held["artifact"]["created"] == stored["created"]  # the server's own stamp

    assert tool(suite, vega, "sync.py")[0] == 0
    copied = json.loads((vega / "record" / "lyra_note_seed_v1.json").read_text())
    assert copied["artifact"]["created"] == stored["created"]

    out = gate(suite, admin_dir)  # a second pass decides nothing
    assert "0 submission(s) to decide" in out and len(records(cli, admin_dir)) == 1


def test_a_rejection_is_a_reply_only_its_submitter_reads(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    bad = note(lyra, "lyra", "dangling")
    broken = json.loads(bad.read_text())
    broken["artifact"]["supersedes"] = ["@lyra_missing_v1"]
    bad.write_text(json.dumps(broken))
    submission = submit(cli, lyra, bad)

    out = gate(suite, admin_dir)
    assert "REJECTED" in out and "lyra_missing_v1" in out
    assert records(cli, admin_dir) == []
    [reply] = replies(cli, admin_dir)
    assert reply["metadata"] == {
        "symposium_reply": True,
        "symposium_in_reply_to": "lyra_note_dangling_v1",
        "recipients": ["lyra"],
        "symposium_submission_citation": submission["citation"],
    }
    code, out = tool(suite, lyra, "sync.py")
    assert code == 0 and "(re lyra_note_dangling_v1)" in out
    code, out = tool(suite, vega, "sync.py")
    assert code == 0 and "reply from the gate" not in out

    gate(suite, admin_dir)  # never a second reply
    assert len(replies(cli, admin_dir)) == 1


def test_a_name_already_in_the_record_is_rejected_with_a_reply(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    seed = note(lyra, "lyra", "seed")
    assert tool(suite, lyra, "publish.py", seed)[0] == 0
    gate(suite, admin_dir)
    submit(cli, lyra, seed)  # publish would refuse it; the gate must too

    out = gate(suite, admin_dir)
    assert "REJECTED" in out and "already in the record" in out
    assert len(records(cli, admin_dir)) == 1 and len(replies(cli, admin_dir)) == 1


def test_an_output_sent_before_its_analysis_is_accepted_after_it(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    submit(cli, lyra, output(lyra, "lyra_data_counts_v1"))
    submit(cli, lyra, analysis(lyra))

    out = gate(suite, admin_dir)
    assert out.count("ACCEPTED") == 2, out
    stamps = {i["name"]: i["created"] for i in records(cli, admin_dir)}
    assert stamps["lyra_analysis_count_v1"] < stamps["lyra_data_counts_v1"]


def test_an_output_waits_for_its_analysis_across_passes(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    submit(cli, lyra, output(lyra, "lyra_data_counts_v1"))
    out = gate(suite, admin_dir)
    assert "DEFERRED lyra_data_counts_v1" in out and records(cli, admin_dir) == []

    submit(cli, lyra, analysis(lyra))
    out = gate(suite, admin_dir)
    assert out.count("ACCEPTED") == 2, out
    assert len(records(cli, admin_dir)) == 2


def test_a_download_on_the_data_server_is_verified(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    assert tool(suite, lyra, "publish.py", analysis(lyra))[0] == 0
    gate(suite, admin_dir)
    table = lyra / "counts.csv"
    table.write_text("gene,count\nBST2,3\n")
    stored = cli.ok(lyra, "put", table, "--collection", "files", "--name", "counts.csv")

    good = output(lyra, "lyra_data_counts_v1", stored["citation"], stored["sha256"])
    assert tool(suite, lyra, "publish.py", good)[0] == 0
    wrong = output(lyra, "lyra_data_wrong_v1", stored["citation"], "0" * 64)
    assert tool(suite, lyra, "publish.py", wrong)[0] == 0
    # cites a version stored only after the submission
    later = stored["citation"].replace("@v1", "@v2")
    assert (
        tool(suite, lyra, "publish.py", output(lyra, "lyra_data_later_v1", later))[0]
        == 0
    )
    table.write_text("gene,count\nBST2,4\n")
    cli.ok(lyra, "version", stored["file_id"], table)

    out = gate(suite, admin_dir)
    assert {i["name"] for i in records(cli, admin_dir)} == {
        "lyra_analysis_count_v1",
        "lyra_data_counts_v1",
    }
    assert "sha256 does not match" in out and "is not strictly earlier" in out
    assert len(replies(cli, admin_dir)) == 2


def test_the_admins_own_submission_is_accepted(suite, admin_dir, cli):
    admin = cli.ok(admin_dir, "context", "show")["context"]["handle"]
    path = note(admin_dir, admin, "welcome")
    assert tool(suite, admin_dir, "publish.py", path)[0] == 0
    out = gate(suite, admin_dir)
    assert "ACCEPTED" in out
    [stored] = records(cli, admin_dir)
    assert (
        stored["name"] == f"{admin}_note_welcome_v1" and stored["created_by"] == admin
    )


def test_the_gate_rebuilds_its_state_from_the_server(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "seed"))[0] == 0
    bad = note(lyra, "lyra", "dangling")
    broken = json.loads(bad.read_text())
    broken["artifact"]["supersedes"] = ["@lyra_missing_v1"]
    bad.write_text(json.dumps(broken))
    submit(cli, lyra, bad)
    gate(suite, admin_dir)
    state = admin_dir / "record" / ".gate_state.json"

    state.unlink()  # lost: the server still holds both decisions
    out = gate(suite, admin_dir)
    assert "0 submission(s) to decide" in out
    assert len(records(cli, admin_dir)) == 1 and len(replies(cli, admin_dir)) == 1
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "next"))[0] == 0
    assert "ACCEPTED" in gate(suite, admin_dir)

    out = gate(suite, admin_dir, "--rebuild")
    assert "2 artifact(s), 3 decision(s)" in out
    assert "0 submission(s) to decide" in gate(suite, admin_dir)
    assert len(records(cli, admin_dir)) == 2 and len(replies(cli, admin_dir)) == 1

    assert "OK" in gate(suite, admin_dir, "--verify")
    (admin_dir / "record" / "lyra_note_next_v1.json").unlink()
    code, out = tool(suite, admin_dir, "gate.py", "--verify")
    assert code == 1 and "missing from the copy: ['lyra_note_next_v1']" in out


def test_the_gate_watches_inbox_until_stopped(suite, admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    watching = subprocess.Popen(
        [sys.executable, str(TOOLS / "gate.py"), "--watch"],
        cwd=admin_dir,
        env={**suite.env, "SYMPOSIUM_POLL": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # submitted after the gate started: a later pass accepts it
        assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "watched"))[0] == 0
        deadline = time.monotonic() + 60
        while not records(cli, admin_dir) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert [i["name"] for i in records(cli, admin_dir)] == ["lyra_note_watched_v1"]
    finally:
        watching.send_signal(signal.SIGINT)
        out, _ = watching.communicate(timeout=30)
    assert watching.returncode == 0, out
    assert "watching inbox (every 1s)" in out and "ACCEPTED" in out


def test_watch_does_not_combine_with_verify_or_rebuild(suite, admin_dir):
    for mode in ("--verify", "--rebuild"):
        code, out = tool(suite, admin_dir, "gate.py", "--watch", mode)
        assert code == 2 and "does not combine" in out
