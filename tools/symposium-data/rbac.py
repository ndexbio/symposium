"""Access roles on the client: the grants, the six roles, the `--access` syntax, and
`UserContext.allowsRequest()` over the context the server resolves for a caller (`GET /me`).

The server decides every request; the CLI, the tools and the skill ask this module first only to
refuse early with a clear message. Its constants and its check are the server's own
(`data-server/service/symposium_data/access/rbac.py`), and a test keeps the two equal.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

from dataclasses import dataclass

READ = "read"
WRITE = "write"
MANAGE = "manage"
PUBLISH = "publish"
GATE = "gate"
MEMBERS = "members"
EXPORT = "export"
COMMUNITIES = "communities"
DELEGATE = "delegate"

GRANTS = (READ, WRITE, MANAGE, PUBLISH, GATE, MEMBERS, EXPORT, COMMUNITIES, DELEGATE)
COLLECTION_SCOPED = frozenset({READ, WRITE, MANAGE})
ALL = "*"
INBOX = "inbox"

SERVER_ROOT = "server-root"
SERVER_ADMIN = "server-admin"
COMMUNITY_ADMIN = "community-admin"
GATE_KEEPER = "gate-keeper"
COMMUNITY_MEMBER = "community-member"
COMMUNITY_OBSERVER = "community-observer"

ROLES = (
    SERVER_ROOT,
    SERVER_ADMIN,
    COMMUNITY_ADMIN,
    GATE_KEEPER,
    COMMUNITY_MEMBER,
    COMMUNITY_OBSERVER,
)
# the roles whose assignment carries a collection value, required
TAKES_COLLECTIONS = frozenset({COMMUNITY_MEMBER, COMMUNITY_OBSERVER})

ACCESS_FORMS = (
    "`--access <role>` for a role without collections; for community-member and "
    "community-observer a collection value is required: `<role>:*` (every collection), "
    "`<role>:` (only the collections it owns) or `<role>:c1,c2` (those collections)"
)


class AccessError(ValueError):
    pass


def parse_access(text: str) -> dict:
    """One `--access` value -> {"role", "collections"}, as the server's assignment routes take
    it."""
    role, colon, value = text.partition(":")
    if role not in ROLES:
        raise AccessError(f"'{role}' is not an access role ({', '.join(ROLES)})")
    if role in TAKES_COLLECTIONS:
        if not colon:
            raise AccessError(f"{role} needs a collection value: {ACCESS_FORMS}")
        if value == ALL:
            return {"role": role, "collections": [ALL]}
        names = [n.strip() for n in value.split(",") if n.strip()]
        return {"role": role, "collections": names}
    if colon:
        raise AccessError(f"{role} takes no collection value: {ACCESS_FORMS}")
    return {"role": role, "collections": None}


def access_text(assignment: dict) -> str:
    """An assignment as `--access` writes it."""
    collections = assignment.get("collections")
    if collections is None:
        return assignment["role"]
    return f"{assignment['role']}:{','.join(collections)}"


@dataclass(frozen=True)
class CollectionRef:
    name: str
    owner_id: str | None = None


@dataclass(frozen=True)
class UserContext:
    principal_id: str | None
    community: str | None
    via_session: bool
    grants: dict

    @classmethod
    def from_view(cls, view: dict) -> UserContext:
        """The context `GET /me` reports as `context`. It names its principal by handle, so
        the owner allowance is the server's to apply."""
        return cls(
            principal_id=None,
            community=view.get("community"),
            via_session=bool(view.get("via_session")),
            grants={
                g: (None if v is None else tuple(v))
                for g, v in (view.get("grants") or {}).items()
            },
        )

    def allowsRequest(  # noqa: N802 (the shared name every enforcement point calls)
        self, grant: str, community: str | None, collection: CollectionRef | None = None
    ) -> bool:
        if grant not in self.grants:
            return False
        if grant not in COLLECTION_SCOPED or collection is None:
            return self.community is None or community == self.community
        if collection.name == INBOX:
            return False
        if (
            self.via_session
            and collection.owner_id is not None
            and collection.owner_id == self.principal_id
        ):
            return True
        if self.community is None:
            return True
        if community != self.community:
            return False
        value = self.grants[grant]
        return ALL in value or collection.name in value
