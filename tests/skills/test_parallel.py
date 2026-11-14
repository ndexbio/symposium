"""Many callers at once, on one machine, against the suite's data server: commands running
together in one session folder and across folders in one community, and two gates watching
under two user contexts. Every submission is decided once, every rejection is sent once,
every copy holds the record, and every state file and event-log line is whole."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from harness import MAX_WAIT
from skills.test_watch import Watch, poll
from skills.test_workflow import TOOLS, note, tool
from suite import enroll

NOTES = 6  # notes per member, published at once


def start(suite, cwd, script: str, *args) -> subprocess.Popen:
    """A toolchain script started in a session folder and left running beside the others."""
    return subprocess.Popen(
        [sys.executable, str(TOOLS / script), *map(str, args)],
        cwd=cwd,
        env=suite.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def record_names(cli, root_dir) -> list:
    items = cli.ok(root_dir, "changes", "--collection", "record", "--all")["items"]
    return sorted(i["name"] for i in items if not i.get("deleted"))


def test_callers_at_once_in_one_folder_and_across_folders_are_each_decided_once(
    suite, root_dir, cli
):
    lyra = enroll(cli, root_dir, "lyra")
    vega = enroll(cli, root_dir, "vega")
    keeper = enroll(cli, root_dir, "bob", "gate-keeper")
    wanted = sorted(
        f"{handle}_note_p{n}_v1" for handle in ("lyra", "vega") for n in range(NOTES)
    )
    fast = {"SYMPOSIUM_POLL": "1"}
    admin_gate = Watch(suite, root_dir, "gate", env=fast)
    keeper_gate = None
    try:
        poll(admin_gate.passed_once, "the admin's gate never finished its first pass")
        # a second gate, under another user context of the community: it stands by
        keeper_gate = Watch(suite, keeper, "gate", env=fast)
        keeper_gate.output.wait_for("standing by")

        # every member's notes, and one name submitted twice, all at the same moment, with
        # syncs and validations running beside them in the same folders
        running = []
        for folder, handle in ((lyra, "lyra"), (vega, "vega")):
            for n in range(NOTES):
                running.append(
                    start(suite, folder, "publish.py", note(folder, handle, f"p{n}"))
                )
            running.append(start(suite, folder, "sync.py"))
            running.append(
                start(
                    suite,
                    folder,
                    "publish.py",
                    "--check",
                    note(folder, handle, "check"),
                )
            )
        twice = note(lyra, "lyra", "twice")
        running += [start(suite, lyra, "publish.py", twice) for _ in range(2)]
        outputs = [(p.communicate(timeout=MAX_WAIT)[0], p.returncode) for p in running]
        assert all(code == 0 for _, code in outputs), [o for o, c in outputs if c]
        assert not any("Traceback" in out for out, _ in outputs)

        every = sorted([*wanted, "lyra_note_twice_v1"])
        poll(
            lambda: record_names(cli, root_dir) == every,
            f"the record never held each name once: {record_names(cli, root_dir)}",
        )
        # the name submitted twice: accepted once, and rejected once with one reply
        poll(
            lambda: (
                tool(suite, lyra, "sync.py", "--replies")[1].count(
                    "(re lyra_note_twice_v1)"
                )
                == 1
            ),
            "the second submission of one name never got its one reply",
        )

        # the gate that was deciding ends: the one standing by decides from there on
        assert admin_gate.stop() == 0, admin_gate.ended()
        poll(keeper_gate.holds_the_lock, "the standing-by gate never took the lock")
        with ThreadPoolExecutor() as pool:
            late = list(
                pool.map(
                    lambda pair: tool(
                        suite, pair[0], "publish.py", note(pair[0], pair[1], "late")
                    ),
                    ((lyra, "lyra"), (vega, "vega")),
                )
            )
        assert all(code == 0 for code, _ in late), late
        every = sorted([*every, "lyra_note_late_v1", "vega_note_late_v1"])
        poll(
            lambda: record_names(cli, root_dir) == every,
            "the gate that took over never decided the late submissions",
        )
        assert (
            tool(suite, lyra, "sync.py", "--replies")[1].count("reply from the gate")
            == 1
        )
    finally:
        for watch in (admin_gate, keeper_gate):
            if watch is not None:
                watch.kill()

    # every copy holds the record, and every file a command wrote beside the others is whole
    for folder in (lyra, vega, keeper, root_dir):
        code, out = tool(suite, folder, "sync.py")
        assert code == 0, out
        held = sorted(
            json.loads(p.read_text())["artifact"]["name"]
            for p in (folder / "record").glob("*.json")
            if "artifact" in json.loads(p.read_text())
        )
        assert held == every, folder
        for state in (folder / "record").glob(".*_state.json"):
            json.loads(state.read_text())
        json.loads((folder / ".symposium" / "context.json").read_text())
        for log in folder.glob("symposium_events_*.jsonl"):
            for line in log.read_text().splitlines():
                json.loads(line)
        assert not list(folder.rglob("*.tmp"))
    code, out = tool(suite, keeper, "gate.py", "--verify")
    assert code == 0 and "OK" in out, out
