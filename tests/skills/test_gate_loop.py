"""The gate on the data server. It reads the members' submissions from `inbox`,
validates them in a serial order, promotes each accepted one into `record` (the server stamps
`created`) or replies to its submitter, verifies every `download` held on the data server, and
keeps no decision only it knows: the record version or the reply names the submission it
decided, so a lost state file is rebuilt from the server."""

import hashlib
import json
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness import MAX_WAIT, Output
from skills.test_workflow import TOOLS, note, submissions, tool
from suite import enroll


def gate(suite, root_dir: Path, *args) -> str:
    code, out = tool(suite, root_dir, "gate.py", *args)
    assert code == 0, out
    return out


def records(cli, directory: Path) -> list:
    return cli.ok(directory, "changes", "--collection", "record", "--all")["items"]


def replies(cli, root_dir: Path) -> list:
    return [
        i
        for i in submissions(cli, root_dir)
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
    suite, root_dir, cli
):
    lyra = enroll(cli, root_dir, "lyra")
    vega = enroll(cli, root_dir, "vega")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "seed"))[0] == 0
    [submission] = submissions(cli, root_dir)

    out = gate(suite, root_dir)
    assert "lyra_note_seed_v1" in out and "ACCEPTED" in out
    [stored] = records(cli, root_dir)
    assert stored["name"] == "lyra_note_seed_v1" and stored["created_by"] == "lyra"
    assert stored["metadata"] == {
        "symposium_submission": True,
        "symposium_record": True,
        "symposium_submission_citation": submission["citation"],
    }
    held = json.loads((root_dir / "record" / "lyra_note_seed_v1.json").read_text())
    assert held["artifact"]["created"] == stored["created"]  # the server's own stamp

    assert tool(suite, vega, "sync.py")[0] == 0
    copied = json.loads((vega / "record" / "lyra_note_seed_v1.json").read_text())
    assert copied["artifact"]["created"] == stored["created"]

    out = gate(suite, root_dir)  # a second pass decides nothing
    assert "0 submission(s) to decide" in out and len(records(cli, root_dir)) == 1


def test_a_rejection_is_a_reply_only_its_submitter_reads(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    vega = enroll(cli, root_dir, "vega")
    bad = note(lyra, "lyra", "dangling")
    broken = json.loads(bad.read_text())
    broken["artifact"]["supersedes"] = ["@lyra_missing_v1"]
    bad.write_text(json.dumps(broken))
    submission = submit(cli, lyra, bad)

    out = gate(suite, root_dir)
    assert "REJECTED" in out and "lyra_missing_v1" in out
    assert records(cli, root_dir) == []
    [reply] = replies(cli, root_dir)
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

    gate(suite, root_dir)  # never a second reply
    assert len(replies(cli, root_dir)) == 1


def test_a_name_already_in_the_record_is_rejected_with_a_reply(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    seed = note(lyra, "lyra", "seed")
    assert tool(suite, lyra, "publish.py", seed)[0] == 0
    gate(suite, root_dir)
    submit(cli, lyra, seed)  # publish would refuse it; the gate must too

    out = gate(suite, root_dir)
    assert "REJECTED" in out and "already in the record" in out
    assert len(records(cli, root_dir)) == 1 and len(replies(cli, root_dir)) == 1


def test_an_output_sent_before_its_analysis_is_accepted_after_it(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    submit(cli, lyra, output(lyra, "lyra_data_counts_v1"))
    submit(cli, lyra, analysis(lyra))

    out = gate(suite, root_dir)
    assert out.count("ACCEPTED") == 2, out
    stamps = {i["name"]: i["created"] for i in records(cli, root_dir)}
    assert stamps["lyra_analysis_count_v1"] < stamps["lyra_data_counts_v1"]


def test_an_output_waits_for_its_analysis_across_passes(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    submit(cli, lyra, output(lyra, "lyra_data_counts_v1"))
    out = gate(suite, root_dir)
    assert "DEFERRED lyra_data_counts_v1" in out and records(cli, root_dir) == []

    submit(cli, lyra, analysis(lyra))
    out = gate(suite, root_dir)
    assert out.count("ACCEPTED") == 2, out
    assert len(records(cli, root_dir)) == 2


def test_a_download_on_the_data_server_is_verified(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    assert tool(suite, lyra, "publish.py", analysis(lyra))[0] == 0
    gate(suite, root_dir)
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

    out = gate(suite, root_dir)
    assert {i["name"] for i in records(cli, root_dir)} == {
        "lyra_analysis_count_v1",
        "lyra_data_counts_v1",
    }
    assert "sha256 does not match" in out and "is not strictly earlier" in out
    assert len(replies(cli, root_dir)) == 2


def table(
    directory: Path, name: str, stored: dict, file_name: str, values: str = ""
) -> Path:
    """A Data artifact in the form the embedding policy gives: its full output a file in
    `files`, cited from a groundable `download` Content with its sha256, and, with `values`,
    the rows an Argument turns on embedded under a `csv` Content."""
    citation = stored["citation"]
    header = {
        "name": name,
        "type": "Data",
        "title": "Scores",
        "description": "Scores by gene. The full table is the file behind `download`.",
        "produced_by": "@lyra_analysis_count_v1",
    }
    contents = [
        {
            "name": "download",
            "type": "Content",
            "description": "The full table, as CSV.",
            "addressing_method": "row=<gene>&col=<column name>, in the file. "
            "Line 1 is the header.",
            "groundable": True,
            "location": citation,
            "sha256": stored["sha256"],
            "access_method": "A file in this community's `files` collection on the data "
            f"server. `/symposium data get {citation} --out {file_name}` downloads it, "
            "checked against its digest.",
        }
    ]
    if values:
        header["values"] = values
        contents.insert(
            0,
            {
                "name": "csv",
                "type": "Content",
                "description": "The rows an Argument turns on, held in `values`.",
                "addressing_method": "row=<gene>&col=<column name>. Line 1 is the header.",
                "groundable": True,
            },
        )
    return artifact(directory, header, contents)


def argument(directory: Path, name: str, citation: str) -> Path:
    """An Argument by vega resting on one Ground: the profile's worked skeleton."""
    path = directory / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "artifact": {
                    "name": name,
                    "type": "Argument",
                    "specification_version": "1.0",
                    "published_by": "@vega",
                    "created": None,
                    "authors": ["vega"],
                    "primary_assertion": "a_primary",
                    "verdict": "Supported, for the purpose stated.",
                    "purpose": "Choosing one gene to follow up; a wrong pick is cheap.",
                    "rationale": "The score puts BST2 on the list.",
                },
                "objects": [
                    {
                        "name": "a_primary",
                        "type": "Assertion",
                        "claim": "BST2 scores among the lowest.",
                        "scope": "This table only.",
                    },
                    {
                        "name": "g_score",
                        "type": "Ground",
                        "citation": citation,
                        "rationale": "The score the table gives for BST2.",
                        "criterion": "A high score would have removed it.",
                    },
                ],
                "relationships": [
                    {"rel": "grounded_by", "source": "a_primary", "target": "g_score"}
                ],
            }
        )
    )
    return path


def fetched(cli, member: Path, location: str) -> bytes:
    """The file a citation names, as `/symposium data get` downloads it."""
    out = member / "fetched.bin"
    cli.ok(member, "get", location, "--out", out)
    return out.read_bytes()


def test_a_published_download_is_read_as_its_file_and_grounded_on(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    vega = enroll(cli, root_dir, "vega")
    assert tool(suite, lyra, "publish.py", analysis(lyra))[0] == 0
    gate(suite, root_dir)
    scores = lyra / "scores.csv"
    scores.write_text("gene,score\nBST2,0.06\nLY6E,0.24\n")
    stored = cli.ok(
        lyra, "put", scores, "--collection", "files", "--name", "scores.csv"
    )
    data = table(lyra, "lyra_data_scores_v1", stored, "scores.csv")
    assert tool(suite, lyra, "publish.py", data)[0] == 0
    assert "ACCEPTED" in gate(suite, root_dir)

    # another member reads the Artifact from her copy of the record, then the file it cites
    code, out = tool(suite, vega, "sync.py")
    assert code == 0, out
    held = json.loads((vega / "record" / "lyra_data_scores_v1.json").read_text())
    content = next(o for o in held["objects"] if o["name"] == "download")
    assert content["location"] == stored["citation"]
    got = fetched(cli, vega, content["location"])
    assert got == scores.read_bytes()
    assert hashlib.sha256(got).hexdigest() == content["sha256"]

    # and grounds on a cell of it: accepted, with the REVIEW that says nothing checked the cell
    cell = "@lyra_data_scores_v1#download.row=BST2&col=score"
    code, out = tool(
        suite, vega, "publish.py", argument(vega, "vega_arg_bst2_v1", cell)
    )
    assert code == 0, out
    assert "grounds via 'download'" in out
    assert "ACCEPTED" in gate(suite, root_dir)
    assert "vega_arg_bst2_v1" in {i["name"] for i in records(cli, root_dir)}


def test_a_result_over_the_limit_is_published_as_its_rows_and_its_file(
    suite, root_dir, cli
):
    lyra = enroll(cli, root_dir, "lyra")
    vega = enroll(cli, root_dir, "vega")
    assert tool(suite, lyra, "publish.py", analysis(lyra))[0] == 0
    gate(suite, root_dir)
    rows = ["gene,score"] + [f"GENE{i},{i / 100000:.5f}" for i in range(20000)]
    full = "\n".join(rows) + "\n"
    assert len(full) > 250 * 1024

    # embedded whole, it is refused before anything is submitted, and the policy is named
    whole = artifact(
        lyra,
        {
            "name": "lyra_data_scores_v1",
            "type": "Data",
            "title": "Scores",
            "description": "Scores by gene.",
            "produced_by": "@lyra_analysis_count_v1",
            "values": full,
        },
        [
            {
                "name": "csv",
                "type": "Content",
                "description": "Every row.",
                "addressing_method": "row=<gene>&col=<column name>.",
                "groundable": True,
            }
        ],
    )
    code, out = tool(suite, lyra, "publish.py", whole)
    assert code != 0
    assert "over the 250 KB limit" in out and "A result over the limit" in out
    assert not [
        i for i in submissions(cli, root_dir) if i["name"].startswith("lyra_data_")
    ]

    # in the policy's form: the rows an Argument turns on embedded, the full output a file
    scores = lyra / "scores.csv"
    scores.write_text(full)
    stored = cli.ok(
        lyra, "put", scores, "--collection", "files", "--name", "scores.csv"
    )
    few = "\n".join(rows[:4]) + "\n"
    code, out = tool(
        suite,
        lyra,
        "publish.py",
        table(lyra, "lyra_data_scores_v1", stored, "scores.csv", values=few),
    )
    assert code == 0, out
    assert "embedded payload" not in out
    assert "ACCEPTED" in gate(suite, root_dir)
    assert [
        i["name"] for i in records(cli, root_dir) if i["name"].startswith("lyra_data_")
    ] == ["lyra_data_scores_v1"]

    # the citation gives the full table back
    got = fetched(cli, vega, stored["citation"])
    assert got == full.encode() and len(got) > 250 * 1024
    assert hashlib.sha256(got).hexdigest() == stored["sha256"]

    # a Ground on an embedded row is verified to the cell; a row only in the file is not there
    embedded = "@lyra_data_scores_v1.values#csv.row=GENE1&col=score"
    code, out = tool(
        suite, vega, "publish.py", argument(vega, "vega_arg_gene1_v1", embedded)
    )
    assert code == 0, out
    assert "grounds via" not in out
    absent = "@lyra_data_scores_v1.values#csv.row=GENE19999&col=score"
    code, out = tool(
        suite, vega, "publish.py", argument(vega, "vega_arg_gene19999_v1", absent)
    )
    assert code != 0, out
    assert "ACCEPTED" in gate(suite, root_dir)
    assert "vega_arg_gene1_v1" in {i["name"] for i in records(cli, root_dir)}


def test_a_removed_members_pending_submission_is_skipped(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "late"))[0] == 0
    cli.ok(root_dir, "users", "remove", "--handle", "lyra")
    out = gate(suite, root_dir)
    assert "'lyra' is not an active member of this community" in out, out
    assert "skipped" in out and records(cli, root_dir) == []


def test_a_gate_keeper_gates_until_its_role_is_unassigned(suite, root_dir, cli):
    bob = enroll(cli, root_dir, "bob", "gate-keeper")
    lyra = enroll(cli, root_dir, "lyra")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "first"))[0] == 0
    assert "ACCEPTED" in gate(suite, bob)
    cli.ok(root_dir, "unassign", "--handle", "bob", "--access", "gate-keeper")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "second"))[0] == 0
    code, out = tool(suite, bob, "gate.py")
    assert code == 1 and "takes the `gate` grant" in out, out
    assert [r["name"] for r in records(cli, root_dir)] == ["lyra_note_first_v1"]


def test_the_gate_rebuilds_its_state_from_the_server(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "seed"))[0] == 0
    bad = note(lyra, "lyra", "dangling")
    broken = json.loads(bad.read_text())
    broken["artifact"]["supersedes"] = ["@lyra_missing_v1"]
    bad.write_text(json.dumps(broken))
    submit(cli, lyra, bad)
    gate(suite, root_dir)
    state = root_dir / "record" / ".gate_state.json"

    state.unlink()  # lost: the server still holds both decisions
    out = gate(suite, root_dir)
    assert "0 submission(s) to decide" in out
    assert len(records(cli, root_dir)) == 1 and len(replies(cli, root_dir)) == 1
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "next"))[0] == 0
    assert "ACCEPTED" in gate(suite, root_dir)

    out = gate(suite, root_dir, "--rebuild")
    assert "2 artifact(s), 3 decision(s)" in out
    assert "0 submission(s) to decide" in gate(suite, root_dir)
    assert len(records(cli, root_dir)) == 2 and len(replies(cli, root_dir)) == 1

    assert "OK" in gate(suite, root_dir, "--verify")
    (root_dir / "record" / "lyra_note_next_v1.json").unlink()
    code, out = tool(suite, root_dir, "gate.py", "--verify")
    assert code == 1 and "missing from the copy: ['lyra_note_next_v1']" in out


def test_the_gate_watches_inbox_until_stopped(suite, root_dir, cli):
    lyra = enroll(cli, root_dir, "lyra")
    watching = subprocess.Popen(
        [sys.executable, str(TOOLS / "gate.py"), "--watch"],
        cwd=root_dir,
        env={**suite.env, "SYMPOSIUM_POLL": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = Output(watching.stdout)
    try:
        # submitted after the gate started: a later pass accepts it, and says so as it does
        assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "watched"))[0] == 0
        output.wait_for("ACCEPTED")
        assert [i["name"] for i in records(cli, root_dir)] == ["lyra_note_watched_v1"]
    finally:
        watching.send_signal(signal.SIGINT)
        code = watching.wait(MAX_WAIT)
    out = output.end()
    assert code == 0, out
    assert "watching inbox (every 1s)" in out


def test_watch_does_not_combine_with_verify_or_rebuild(suite, root_dir):
    for mode in ("--verify", "--rebuild"):
        code, out = tool(suite, root_dir, "gate.py", "--watch", mode)
        assert code == 2 and "does not combine" in out
