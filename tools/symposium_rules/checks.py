"""The checks the gate and `publish` make beyond the validator: the inbox skip rule, the
naming rule, and the embedded-payload limit. Each returns a reason, or None when it passes, so
the tools print it their way and the API reports it as a finding."""

from __future__ import annotations

from .validate import EMBED_REFUSE, embedded_size


def skip_reason(inbox_name: str, owner: str, declared, members) -> str | None:
    """Why the gate sets an inbox item aside without deciding it, or None to decide it.

    The item's inbox name, before the `@`, must be the artifact's own name; that name must
    carry its submitter's handle as a prefix; and the submitter must be a member."""
    name = inbox_name.partition("@")[0]
    if declared != name:
        return f"inbox name '{name}' is not the artifact's name '{declared}'"
    if not name.startswith(f"{owner}_"):
        return f"the name is not prefixed with its submitter's handle '{owner}_'"
    if owner not in members:
        return f"'{owner}' is not a member of this community"
    return None


def naming_refusal(name, account: str) -> str | None:
    """The profile's naming rule: an artifact's name starts with its publisher's handle."""
    if not str(name).startswith(f"{account}_"):
        return f"name must be prefixed '{account}_' (profile naming rule)"
    return None


def payload_refusal(artifact: dict) -> str | None:
    """The embedded-payload limit: an artifact over EMBED_REFUSE belongs in the file store."""
    total, props = embedded_size(artifact)
    if total <= EMBED_REFUSE:
        return None
    biggest = (
        f"; largest property: '{props[0][1]}' on {props[0][0]}, {props[0][2] // 1024} KB"
        if props
        else ""
    )
    return (
        f"embedded payload is {total // 1024} KB, over the {EMBED_REFUSE // 1024} KB "
        f"limit{biggest}"
    )
