"""The repository states only the current model. Every tracked text file is scanned, except the
ones that must name what came before, for: the old security model's identifiers, route forms the
resource tree retired, community routes without their `/communities/` prefix, requirement IDs,
historical wording, and a bare "admin" where the role it means is root, a server admin or a
community admin. Each failure names the file, the line and the match."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
THIS = "tests/api/test_rbac_boundaries.py"

# what must name what came before: Alembic's upgrade path, the published 0.1.2 client the
# upgrade tests drive, the conformance fixtures, the change history; and data recorded from
# elsewhere: NDEx's responses, the vendored libraries
KEPT = (
    re.compile(r"^data-server/service/symposium_data/migrations/versions/"),
    re.compile(r"^examples/"),
    re.compile(r"^CHANGELOG\.md$"),
    re.compile(r"^data-server/service/tests/integration/test_migration\.py$"),
    re.compile(r"^data-server/service/tests/previous\.py$"),
    re.compile(r"^tools/vendor/"),
    re.compile(r"^data-server/service/tests/fixtures/"),
    re.compile(rf"^{re.escape(THIS)}$"),
)
TEXT = re.compile(
    r"\.(py|md|ya?ml|json|txt|jinja2|toml|ini|cfg|sh|html|js|css|tpl)$|(^|/)Makefile$"
)

IDENTIFIERS = re.compile(
    r"\bis_admin\b|\badmin_keys\b|\bowner_keys\b|\bx-roles\b|\bADMIN_ONLY\b|\bMEMBERS_TOO\b"
    r"|\bsign_in_admin\b|\bsign_in_member\b|\badmin_handle\(|\bDEFAULT_GRANTS\b"
    r'|role == "admin"'
)
# a retired route form, as whole path segments: it ends where a path ends
END = r"(?=[\"'`?\s/)\]>,.;:]|$)"
RETIRED = re.compile(
    r"/auth/(challenge|token)"
    + END
    + r"|/admin/(challenge|token)"
    + END
    + r"|/(assignments|roster|port-ndex|stat|purge|promote|resolve|verify|find|query"
    r"|export)"
    + END
    + r"|/v/|/submissions/check"
    + END
    + r"|/streams/|/sha256/|/communities/import"
    + END
    + r"|/users/me/keys"
    + END
)
# a route under /v1 names one of the server's own resources first
SERVER_WIDE = (
    "communities",
    "status",
    "challenges",
    "sessions",
    "registrations",
    "me",
    "roles",
    "users",
    "invites",
    "openapi.yaml",
    "openapi.json",
)
# a Kubernetes apiVersion (`gateway.networking.k8s.io/v1/HTTPRoute`) is not a route
UNPREFIXED = re.compile(
    r"(?<!\.io)/v1/(?!(?:" + "|".join(map(re.escape, SERVER_WIDE)) + r")\b)[\w{<$]"
)
API_VAR = re.compile(
    r"\$API/(?!(?:" + "|".join(map(re.escape, SERVER_WIDE)) + r")\b)\w"
)
REQUIREMENT_ID = re.compile(r"\bR-[A-Z][0-9]+\b")
HISTORICAL = re.compile(
    r"\b(previously|formerly|used to|no longer|legacy|deprecated|for compatibility"
    r"|backward[- ]compat\w*)\b",
    re.IGNORECASE,
)
# "admin" is a role name only as root, a server admin or a community admin; these are the
# current names that carry the word
ADMIN = re.compile(r"\badmin(s|'s)?\b", re.IGNORECASE)
ADMIN_ALLOWED = re.compile(
    r"(server|community)[ -]admins?('s)?\b|\badmin-config\b|\badmin_pub_|\badminKey\b"
    r"|\badmin[ -_]key|\bAdminMode\b|\bADMIN_SCOPE\b|\badmin_key\b"
    r"|[/\"'`.]admin\b|\badmin/|--admin\b|\badmin[\"'`]|\{name, admin\}|<admin>"
    r"|\badmin:|\badmin=|\badmin\)|\bargs\.admin\b|\bbody\.admin\b"
    r"|NDEx (community )?admin('s)?|\[name, admin\]|permission=ADMIN|\bndex-admin\b|\bdemo-admin\b"
    r"|\bsymposium-admin\b|\bndexbio-admin\b|\badmin_networks\b|\bdemo_admin\b"
    r"|\badmin: str\b|\badmin \(|`admin` \(",
    re.IGNORECASE,
)


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    return [f for f in out if TEXT.search(f) and not any(k.search(f) for k in KEPT)]


def lines():
    for rel in tracked():
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        upgrade = False
        for number, line in enumerate(text.splitlines(), 1):
            # the README's upgrade guide names what a 0.1.x server holds
            if rel == "data-server/README.md":
                if line.startswith("## Upgrading a 0.1.x server"):
                    upgrade = True
                elif line.startswith("## ") and upgrade:
                    upgrade = False
            if not upgrade:
                yield rel, number, line


def found(pattern, *, allowed=None) -> list[str]:
    hits = []
    for rel, number, line in lines():
        for match in pattern.finditer(line):
            if allowed is not None and any(
                a.start() <= match.start() and match.end() <= a.end()
                for a in allowed.finditer(line)
            ):
                continue
            hits.append(f"{rel}:{number}: {match.group(0)!r} in {line.strip()[:120]}")
    return hits


@pytest.mark.parametrize(
    "name,pattern",
    [
        ("an identifier of the old model", IDENTIFIERS),
        ("a retired route form", RETIRED),
        ("a community route without /communities/", UNPREFIXED),
        ("a community route without /communities/", API_VAR),
        ("a requirement ID", REQUIREMENT_ID),
    ],
)
def test_the_repository_states_only_the_current_model(name, pattern):
    hits = found(pattern)
    assert not hits, f"{len(hits)} × {name}:\n" + "\n".join(hits)


# the specification's own vocabulary: an Artifact cites "previously published" Artifacts, a
# citation "must not be used to" supply evidence; a role's text says what a claim "no longer"
# is once it has evidence
HISTORICAL_ALLOWED = re.compile(
    r"previously published|\bbe used to (supply|do)\b|no longer a hypothesis",
    re.IGNORECASE,
)


def test_the_wording_states_what_is():
    hits = found(HISTORICAL, allowed=HISTORICAL_ALLOWED)
    assert not hits, f"{len(hits)} × historical wording:\n" + "\n".join(hits)


def test_admin_names_the_role_it_means():
    hits = found(ADMIN, allowed=ADMIN_ALLOWED)
    assert not hits, f"{len(hits)} × a bare 'admin':\n" + "\n".join(hits)
