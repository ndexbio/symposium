"""The Python API for working in a Symposium community record.

What is public is what `__all__` names, and nothing else: a skill built on this package depends on
these names staying put, which is a commitment a command's one-JSON-object-on-stdout never asked
for. Everything else here is free to change.

    from symposium import Session, validate

    s = Session.from_env()            # the session this agent session is working in
    s.sync()                          # refresh the local copy of the record
    s.record.artifacts()              # what the record holds, for reconciling against
    s.check(artifact, role="importer")    # what the gate will say, uploading nothing
    s.publish(artifact, role="importer")

**Importing this package must work on a bare interpreter**, because the skill's own scripts and the
toolchain's tools run with the interpreter that started them and no virtual environment. So nothing
is imported at module scope: `validate` reaches `symposium_rules`, and the data-server client
reaches `cryptography` and `keyring`, neither of which a bare interpreter has. They are resolved on
first use instead (PEP 562), which keeps `from symposium import agent_process` free.

Standard library only until something third-party is actually asked for. Python 3.9+.
"""

from __future__ import annotations

__all__ = [
    "Record",
    "Result",
    "Session",
    "SessionError",
    "Sessions",
    "ToolchainError",
    "validate",
]


def __getattr__(name: str):
    """Resolve a public name on first use, so importing the package costs nothing."""
    if name in ("Result", "Session", "SessionError", "Sessions"):
        from . import session

        return getattr(session, name)
    if name == "Record":
        from .record import Record

        return Record
    if name == "ToolchainError":
        from .toolchain import ToolchainError

        return ToolchainError
    if name == "validate":
        from .validation import validate

        return validate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
