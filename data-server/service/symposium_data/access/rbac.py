"""Role-based access: the grants, the six roles that bundle them, and the one check every
request makes.

A principal (a user, or an issued API key) is assigned roles. The only value an assignment
carries is a collection list, and only `community-member` and `community-observer` take one;
the community is the principal's own, never part of an assignment. On every request the
principal's assignments compile into a `UserContext`, and every enforcement point asks it one
question, `allowsRequest(grant, community, collection)`. Nothing outside this module, the
assignment handlers and the CLI's role commands names a role.

Standard library only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# ── grants ──────────────────────────────────────────────────────────────────────────────────
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
# the grants a collection list scopes; every other grant applies to a whole community
COLLECTION_SCOPED = frozenset({READ, WRITE, MANAGE})
# every collection: of the principal's community, or of every community for a server-level one
ALL = "*"
# outside every collection-scoped grant: reached through `publish` and `gate` alone
INBOX = "inbox"

# ── who a role is assigned to ───────────────────────────────────────────────────────────────
SERVER_USER = "server-user"
HOMED_USER = "homed-user"
MEMBER_KEY = "member-key"
NON_MEMBER_KEY = "non-member-key"
PRINCIPAL_KINDS = frozenset({SERVER_USER, HOMED_USER, MEMBER_KEY, NON_MEMBER_KEY})

# a role's grant takes the assignment's own collection value
VALUE = object()


class AssignmentError(ValueError):
    """An assignment that cannot exist: an unknown role, or a collection value that does not
    fit the role."""


@dataclass(frozen=True)
class Role:
    id: str
    assignable_to: frozenset
    # each grant's compiled value: None (not collection-scoped), a tuple of collection
    # values (`(ALL,)` or `()`), or VALUE, the assignment's own collection value
    grants: Mapping
    # the grant an assigner holds, at the assignee's community, to assign or unassign the role
    assigned_by: str
    # with collection names on the assignment: the grant held on each named collection
    # instead; None when the names change nothing about who may assign
    names_assigned_by: str | None = None
    assignable: bool = True

    @property
    def takes_collections(self) -> bool:
        return any(v is VALUE for v in self.grants.values())

    @property
    def key_assignable(self) -> bool:
        return bool(self.assignable_to & {MEMBER_KEY, NON_MEMBER_KEY})


_EVERY = (ALL,)

ROLES: dict[str, Role] = {
    role.id: role
    for role in (
        Role(
            id="server-root",
            assignable_to=frozenset({SERVER_USER}),
            grants={
                READ: _EVERY,
                WRITE: _EVERY,
                MANAGE: _EVERY,
                DELEGATE: None,
                COMMUNITIES: None,
                GATE: None,
                MEMBERS: None,
                EXPORT: None,
            },
            assigned_by=DELEGATE,
            assignable=False,
        ),
        Role(
            id="server-admin",
            assignable_to=frozenset({SERVER_USER}),
            grants={
                READ: _EVERY,
                WRITE: _EVERY,
                MANAGE: _EVERY,
                COMMUNITIES: None,
                GATE: None,
                MEMBERS: None,
                EXPORT: None,
            },
            assigned_by=DELEGATE,
        ),
        Role(
            id="community-admin",
            assignable_to=frozenset({HOMED_USER}),
            grants={
                READ: _EVERY,
                WRITE: _EVERY,
                MANAGE: _EVERY,
                GATE: None,
                MEMBERS: None,
                EXPORT: None,
            },
            assigned_by=MEMBERS,
        ),
        Role(
            id="gate-keeper",
            assignable_to=frozenset({HOMED_USER}),
            grants={READ: _EVERY, GATE: None},
            assigned_by=MEMBERS,
        ),
        Role(
            id="community-member",
            assignable_to=frozenset({HOMED_USER, MEMBER_KEY}),
            grants={READ: VALUE, WRITE: VALUE, MANAGE: (), PUBLISH: None},
            assigned_by=MEMBERS,
        ),
        Role(
            id="community-observer",
            assignable_to=frozenset({HOMED_USER, MEMBER_KEY, NON_MEMBER_KEY}),
            grants={READ: VALUE},
            assigned_by=MEMBERS,
            names_assigned_by=MANAGE,
        ),
    )
}


def role(role_id: str) -> Role:
    found = ROLES.get(role_id)
    if found is None:
        raise AssignmentError(f"no role '{role_id}'")
    return found


def collection_value(role_id: str, collections: Iterable[str] | None) -> tuple | None:
    """`collections` as the role stores it: a tuple of collection names, `(ALL,)` or `()`
    for the two roles that take one, None for every other role."""
    found = role(role_id)
    if not found.takes_collections:
        if collections is not None:
            raise AssignmentError(f"'{role_id}' takes no collection value")
        return None
    if collections is None:
        raise AssignmentError(
            f"'{role_id}' needs a collection value: '*', an empty list, or collection names"
        )
    names = tuple(dict.fromkeys(collections))
    if ALL in names and names != (ALL,):
        raise AssignmentError("'*' stands alone in a collection value")
    if INBOX in names:
        raise AssignmentError("'inbox' is never part of a collection value")
    return names


def names_in(value: tuple | None) -> tuple:
    """The specific collection names in a value: none for `*`, an empty list or None."""
    if not value or ALL in value:
        return ()
    return value


@dataclass(frozen=True)
class Assignment:
    role_id: str
    collections: tuple | None = None


def merge(current: tuple | None, more: tuple) -> tuple:
    """Two lists for one grant: unioned, `*` absorbing everything, `()` adding nothing."""
    if current is None:
        return tuple(more)
    if ALL in current or ALL in more:
        return _EVERY
    return tuple(dict.fromkeys((*current, *more)))


def compile_grants(assignments: Iterable[Assignment]) -> dict:
    """The grant map of a principal's live assignments: grant -> None (not collection-scoped)
    or a tuple of collection values."""
    out: dict = {}
    for assignment in assignments:
        found = role(assignment.role_id)
        value = collection_value(assignment.role_id, assignment.collections)
        for grant, template in found.grants.items():
            if template is None:
                out[grant] = None
                continue
            more = value if template is VALUE else template
            out[grant] = merge(out.get(grant), more)
    return out


@dataclass(frozen=True)
class CollectionRef:
    name: str
    owner_id: object | None = None


@dataclass(frozen=True)
class UserContext:
    """The resolved caller of one request."""

    principal_id: object
    principal_name: str | None
    community: str | None  # None: a server-level principal
    via_session: bool  # signed in with a session key, rather than an issued API key
    grants: Mapping = field(default_factory=dict)

    def allowsRequest(  # noqa: N802 (the shared name every enforcement point calls)
        self, grant: str, community: str | None, collection: CollectionRef | None = None
    ) -> bool:
        """Whether this caller holds `grant` for `community` (and, for a collection-scoped
        grant at a handler, for `collection`)."""
        if grant not in self.grants:
            return False
        if grant not in COLLECTION_SCOPED or collection is None:
            # a whole-community grant, or the route-level check before a handler names the
            # collection: the grant is held, so only the community matters
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
        if ALL in value:
            return True
        return collection.name in value

    def view(self) -> dict:
        """What `GET /me` and the CLI's `access` show."""
        return {
            "principal": self.principal_name,
            "community": self.community,
            "via_session": self.via_session,
            "grants": {
                grant: (None if value is None else list(value))
                for grant, value in sorted(self.grants.items())
            },
        }


def may_assign(
    ctx: UserContext,
    role_id: str,
    collections: Iterable[str] | None,
    assignee_kind: str,
    community: str | None,
    refs: Mapping | None = None,
) -> bool:
    """Whether `ctx` may assign (or unassign) `role_id` with `collections` to a principal of
    `assignee_kind` homed in `community` (None for a server-level user). `refs` maps each named
    collection to its `CollectionRef`. Unassigning names asks this for the names removed."""
    found = role(role_id)
    if not found.assignable or assignee_kind not in found.assignable_to:
        return False
    value = collection_value(role_id, collections)
    if (assignee_kind == SERVER_USER) != (community is None):
        return False
    names = names_in(value)
    if names and found.names_assigned_by is not None:
        refs = refs or {}
        return all(
            name in refs
            and ctx.allowsRequest(found.names_assigned_by, community, refs[name])
            for name in names
        )
    return ctx.allowsRequest(found.assigned_by, community)


def may_carry(
    issuer: UserContext,
    role_id: str,
    collections: Iterable[str] | None,
    member_key: bool,
    community: str,
    refs: Mapping | None = None,
) -> bool:
    """Whether an API key `issuer` issues in `community` may carry `role_id` with
    `collections`: a role keys may carry, of the kind of key, granting nothing the issuer
    lacks there."""
    found = role(role_id)
    kind = MEMBER_KEY if member_key else NON_MEMBER_KEY
    if kind not in found.assignable_to:
        return False
    value = collection_value(role_id, collections)
    if issuer.community is not None and community != issuer.community:
        return False
    refs = refs or {}
    for grant, template in found.grants.items():
        if template is None:
            if not issuer.allowsRequest(grant, community):
                return False
            continue
        wanted = value if template is VALUE else template
        if not wanted:
            continue  # nothing by list: a key has no owner allowance
        if ALL in wanted:
            held = issuer.grants.get(grant)
            if held is None or (issuer.community is not None and ALL not in held):
                return False
            continue
        for name in wanted:
            if name not in refs or not issuer.allowsRequest(
                grant, community, refs[name]
            ):
                return False
    return True


def validate_registry() -> None:
    """Raise when the role table contradicts itself."""
    for found in ROLES.values():
        if not found.assignable_to or not found.assignable_to <= PRINCIPAL_KINDS:
            raise AssertionError(
                f"{found.id}: assignable_to {set(found.assignable_to)}"
            )
        for grant, template in found.grants.items():
            if grant not in GRANTS:
                raise AssertionError(f"{found.id}: unknown grant '{grant}'")
            if (grant in COLLECTION_SCOPED) == (template is None):
                raise AssertionError(
                    f"{found.id}: '{grant}' has the wrong kind of value"
                )
            if PUBLISH == grant and found.id != "community-member":
                raise AssertionError(f"{found.id}: only community-member publishes")
        if found.assigned_by not in GRANTS:
            raise AssertionError(f"{found.id}: assigned_by '{found.assigned_by}'")
        if found.names_assigned_by is not None and not found.takes_collections:
            raise AssertionError(
                f"{found.id}: names_assigned_by without a collection value"
            )
        if SERVER_USER in found.assignable_to and found.assignable_to != {SERVER_USER}:
            raise AssertionError(
                f"{found.id}: a server role is for server-level users only"
            )


validate_registry()
