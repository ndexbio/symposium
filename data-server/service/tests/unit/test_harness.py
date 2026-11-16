"""`diagnose`, which turns a container's log into the reason it is not working.

A failing program dies in the container's first second, while SeaweedFS prints a heartbeat
every thirty. A tail of the log is therefore always the heartbeat, whatever its size, and a
reader is told that the server never became healthy without being told why.
"""

from harness import diagnose

NOISE = "I1112 20:02:35.555797 lock_ring_manager.go:159 LockRing: broadcasting ring update\n"
REASON = (
    'FATAL:  configuration file "/apps/postgres/data/postgresql.conf" contains errors'
)


def test_the_reason_survives_a_log_that_buries_it():
    report = diagnose(REASON + "\n" + NOISE * 5000)
    assert "postgresql.conf" in report
    # and the tail is still there, for whatever the reason does not say
    assert "lock_ring_manager" in report


def test_a_repeated_line_is_said_once_and_counted():
    """supervisord restarts what dies, so the same line arrives every few seconds."""
    report = diagnose((REASON + "\n") * 7)
    said = report.split("--- the last")[0]  # the tail below it may repeat the line
    assert said.count("postgresql.conf") == 1
    assert "(x7)" in said


def test_a_line_that_happened_once_carries_no_count():
    assert "(x" not in diagnose(REASON + "\n" + NOISE)


def test_every_kind_of_trouble_is_recognised():
    log = "\n".join(
        [
            "LOG:  could not open configuration file: Permission denied",
            "2026-11-12 21:14:23,064 WARN exited: postgres (exit status 1; not expected)",
            "ERROR:    Application startup failed. Exiting.",
            "PANIC:  could not write to file",
            "2026-11-12 21:14:22,017 CRIT Server running without authentication",
        ]
    )
    report = diagnose(log)
    for said in (
        "Permission denied",
        "exited: postgres",
        "startup failed",
        "PANIC",
        "CRIT",
    ):
        assert said in report.split("--- the last")[0], said


def test_a_log_with_nothing_wrong_says_so():
    report = diagnose(NOISE * 10)
    assert "nothing in the log says why" in report


def test_the_report_is_bounded_when_everything_is_wrong():
    report = diagnose("\n".join(f"FATAL: failure number {n}" for n in range(200)))
    assert "and 175 more" in report
