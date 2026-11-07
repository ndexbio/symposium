"""Role-based access, without a server: the role registry, how a principal's assignments compile
into a grant map, and the one check every request makes (`symposium_data.access.rbac`)."""

from __future__ import annotations

import pytest

from symposium_data.access import rbac
from symposium_data.access.rbac import (
    ALL,
    COLLECTION_SCOPED,
    COMMUNITIES,
    DELEGATE,
    EXPORT,
    GATE,
    GRANTS,
    HOMED_USER,
    INBOX,
    MANAGE,
    MEMBER_KEY,
    MEMBERS,
    NON_MEMBER_KEY,
    PUBLISH,
    READ,
    ROLES,
    SERVER_USER,
    WRITE,
    Assignment,
    AssignmentError,
    CollectionRef,
    UserContext,
    compile_grants,
    may_assign,
    may_carry,
    validate_registry,
)

C, OTHER = "demo", "other"
LYRA, MIA, KEY = "u-lyra", "u-mia", "k-1"


def ctx(*assignments, community=C, principal=LYRA, via_session=True):
    return UserContext(
        principal_id=principal,
        principal_name=principal,
        community=community,
        via_session=via_session,
        grants=compile_grants(assignments),
    )


def ref(name, owner=None):
    return CollectionRef(name, owner)


ROOT = ctx(Assignment("server-root"), community=None, principal="u-root")
SERVER_ADMIN = ctx(Assignment("server-admin"), community=None, principal="u-ana")
COMMUNITY_ADMIN = ctx(Assignment("community-admin"), principal="u-cadmin")
GATE_KEEPER = ctx(Assignment("gate-keeper"), principal="u-bob")
MEMBER = ctx(Assignment("community-member", (ALL,)))
OBSERVER = ctx(Assignment("community-observer", (ALL,)), principal="u-olive")


# ── the registry ────────────────────────────────────────────────────────────────────────────
def test_the_registry_is_consistent():
    validate_registry()
    assert set(ROLES) == {
        "server-root",
        "server-admin",
        "community-admin",
        "gate-keeper",
        "community-member",
        "community-observer",
    }


def test_only_member_and_observer_take_a_collection_value():
    takes = {r.id for r in ROLES.values() if r.takes_collections}
    assert takes == {"community-member", "community-observer"}


def test_no_administrative_role_holds_publish():
    publishers = {r.id for r in ROLES.values() if PUBLISH in r.grants}
    assert publishers == {"community-member"}


def test_only_member_and_observer_are_carried_by_keys():
    assert {r.id for r in ROLES.values() if r.key_assignable} == {
        "community-member",
        "community-observer",
    }
    assert NON_MEMBER_KEY not in ROLES["community-member"].assignable_to
    assert NON_MEMBER_KEY in ROLES["community-observer"].assignable_to


def test_every_grant_is_in_some_role():
    used = {g for r in ROLES.values() for g in r.grants}
    assert used == set(GRANTS)


# ── compiling ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "role_id, value, expected",
    [
        (
            "server-root",
            None,
            {
                READ: (ALL,),
                WRITE: (ALL,),
                MANAGE: (ALL,),
                DELEGATE: None,
                COMMUNITIES: None,
                GATE: None,
                MEMBERS: None,
                EXPORT: None,
            },
        ),
        (
            "server-admin",
            None,
            {
                READ: (ALL,),
                WRITE: (ALL,),
                MANAGE: (ALL,),
                COMMUNITIES: None,
                GATE: None,
                MEMBERS: None,
                EXPORT: None,
            },
        ),
        (
            "community-admin",
            None,
            {
                READ: (ALL,),
                WRITE: (ALL,),
                MANAGE: (ALL,),
                GATE: None,
                MEMBERS: None,
                EXPORT: None,
            },
        ),
        ("gate-keeper", None, {READ: (ALL,), GATE: None}),
        (
            "community-member",
            (ALL,),
            {READ: (ALL,), WRITE: (ALL,), MANAGE: (), PUBLISH: None},
        ),
        (
            "community-member",
            (),
            {READ: ("record",), WRITE: (), MANAGE: (), PUBLISH: None},
        ),
        (
            "community-member",
            ("c1", "c2"),
            {
                READ: ("c1", "c2", "record"),
                WRITE: ("c1", "c2"),
                MANAGE: (),
                PUBLISH: None,
            },
        ),
        ("community-observer", (ALL,), {READ: (ALL,)}),
        ("community-observer", (), {READ: ()}),
        ("community-observer", ("c1",), {READ: ("c1",)}),
    ],
)
def test_each_role_compiles_to_its_grants(role_id, value, expected):
    assert compile_grants([Assignment(role_id, value)]) == expected


def test_a_member_user_reads_the_record_and_an_issued_key_only_its_value():
    """A publisher validates against the record, so a user holding community-member reads it
    whatever its collection value; a key carries exactly the collections it is given."""
    assignment = [Assignment("community-member", ("files",))]
    assert compile_grants(assignment)[READ] == ("files", "record")
    assert compile_grants(assignment, user=False)[READ] == ("files",)
    member = ctx(Assignment("community-member", ()))
    assert member.allowsRequest(READ, C, ref("record"))
    assert not member.allowsRequest(WRITE, C, ref("record"))
    assert not member.allowsRequest(READ, C, ref("inbox"))


def test_a_collection_value_is_required_exactly_where_the_role_takes_one():
    with pytest.raises(AssignmentError):
        compile_grants([Assignment("community-member")])
    with pytest.raises(AssignmentError):
        compile_grants([Assignment("community-observer")])
    with pytest.raises(AssignmentError):
        compile_grants([Assignment("community-admin", (ALL,))])
    with pytest.raises(AssignmentError):
        compile_grants([Assignment("gate-keeper", ("c1",))])


def test_a_collection_value_is_well_formed():
    with pytest.raises(AssignmentError):
        compile_grants([Assignment("community-observer", (ALL, "c1"))])
    with pytest.raises(AssignmentError):
        compile_grants([Assignment("community-observer", (INBOX,))])
    with pytest.raises(AssignmentError):
        compile_grants([Assignment("no-such-role")])


def test_lists_merge_and_star_absorbs():
    merged = compile_grants(
        [
            Assignment("community-observer", ("c1", "c2")),
            Assignment("community-member", ("c2", "c3")),
        ]
    )
    assert merged[READ] == ("c1", "c2", "c3", "record")
    assert merged[WRITE] == ("c2", "c3")
    starred = compile_grants(
        [Assignment("community-observer", ("c1",)), Assignment("gate-keeper")]
    )
    assert starred[READ] == (ALL,)


def test_an_empty_list_adds_nothing():
    merged = compile_grants(
        [Assignment("community-observer", ()), Assignment("community-member", ("c1",))],
        user=False,
    )
    assert merged[READ] == ("c1",)
    assert compile_grants([Assignment("community-observer", ())])[READ] == ()


def test_no_assignments_hold_nothing():
    assert compile_grants([]) == {}
    nobody = ctx()
    assert not any(nobody.allowsRequest(g, C, ref("c1")) for g in GRANTS)


# ── the check ───────────────────────────────────────────────────────────────────────────────
def test_a_grant_absent_from_the_map_is_refused():
    assert not OBSERVER.allowsRequest(WRITE, C, ref("c1"))
    assert not MEMBER.allowsRequest(GATE, C)
    assert not COMMUNITY_ADMIN.allowsRequest(DELEGATE, None)


def test_whole_community_grants_follow_the_principals_community():
    assert MEMBER.allowsRequest(PUBLISH, C)
    assert not MEMBER.allowsRequest(PUBLISH, OTHER)
    assert COMMUNITY_ADMIN.allowsRequest(MEMBERS, C)
    assert not COMMUNITY_ADMIN.allowsRequest(MEMBERS, OTHER)


def test_a_server_level_principal_holds_its_grants_everywhere():
    for community in (C, OTHER):
        assert SERVER_ADMIN.allowsRequest(MEMBERS, community)
        assert SERVER_ADMIN.allowsRequest(READ, community, ref("anything", "u-x"))
    assert ROOT.allowsRequest(DELEGATE, None)
    assert not SERVER_ADMIN.allowsRequest(DELEGATE, None)


def test_the_route_level_check_asks_only_the_community():
    limited = ctx(
        Assignment("community-observer", ("c2",)), principal=KEY, via_session=False
    )
    assert limited.allowsRequest(READ, C)
    assert not limited.allowsRequest(READ, OTHER)
    owner_only = ctx(Assignment("community-member", ()))
    assert owner_only.allowsRequest(WRITE, C)


def test_a_collection_list_decides_at_the_handler():
    limited = ctx(Assignment("community-observer", ("c2", "c3")), via_session=False)
    assert limited.allowsRequest(READ, C, ref("c2", MIA))
    assert not limited.allowsRequest(READ, C, ref("c1", MIA))
    assert not limited.allowsRequest(READ, OTHER, ref("c2", MIA))


def test_star_covers_every_collection_of_the_community_only():
    assert OBSERVER.allowsRequest(READ, C, ref("c9", MIA))
    assert OBSERVER.allowsRequest(READ, C, ref("record", "u-root"))
    assert not OBSERVER.allowsRequest(READ, OTHER, ref("c9", MIA))


def test_an_empty_list_allows_only_owned_collections():
    owner_only = ctx(Assignment("community-member", ()))
    assert owner_only.allowsRequest(WRITE, C, ref("mine", LYRA))
    assert owner_only.allowsRequest(MANAGE, C, ref("mine", LYRA))
    assert not owner_only.allowsRequest(WRITE, C, ref("theirs", MIA))


def test_the_owner_allowance_holds_whatever_the_list():
    limited = ctx(Assignment("community-member", ("files",)))
    assert limited.allowsRequest(WRITE, C, ref("mine", LYRA))
    assert limited.allowsRequest(MANAGE, C, ref("mine", LYRA))
    assert not limited.allowsRequest(MANAGE, C, ref("files", "u-root"))


def test_the_owner_allowance_needs_the_grant_in_the_map():
    observer = ctx(Assignment("community-observer", ()))
    assert not observer.allowsRequest(WRITE, C, ref("mine", LYRA))


def test_issued_keys_get_no_owner_allowance():
    key = ctx(Assignment("community-member", ("files",)), via_session=False)
    assert key.allowsRequest(WRITE, C, ref("files", "u-root"))
    assert not key.allowsRequest(WRITE, C, ref("mine", LYRA))
    owner_only_key = ctx(Assignment("community-member", ()), via_session=False)
    assert not owner_only_key.allowsRequest(READ, C, ref("mine", LYRA))


def test_inbox_is_outside_every_collection_scoped_grant():
    for context in (ROOT, SERVER_ADMIN, COMMUNITY_ADMIN, MEMBER, OBSERVER):
        for grant in COLLECTION_SCOPED:
            assert not context.allowsRequest(grant, C, ref(INBOX, context.principal_id))
    assert MEMBER.allowsRequest(PUBLISH, C)
    assert GATE_KEEPER.allowsRequest(GATE, C)


def test_the_view_shows_community_and_grants():
    view = MEMBER.view()
    assert view["community"] == C
    assert view["grants"][READ] == [ALL]
    assert view["grants"][PUBLISH] is None


# ── who may assign ──────────────────────────────────────────────────────────────────────────
def test_server_roles_need_delegate_and_server_root_is_never_assigned():
    assert may_assign(ROOT, "server-admin", None, SERVER_USER, None)
    assert not may_assign(SERVER_ADMIN, "server-admin", None, SERVER_USER, None)
    for context in (ROOT, SERVER_ADMIN, COMMUNITY_ADMIN):
        assert not may_assign(context, "server-root", None, SERVER_USER, None)


def test_administrative_community_roles_need_members():
    for role_id in ("community-admin", "gate-keeper"):
        assert may_assign(COMMUNITY_ADMIN, role_id, None, HOMED_USER, C)
        assert may_assign(SERVER_ADMIN, role_id, None, HOMED_USER, C)
        assert not may_assign(COMMUNITY_ADMIN, role_id, None, HOMED_USER, OTHER)
        assert not may_assign(GATE_KEEPER, role_id, None, HOMED_USER, C)
        assert not may_assign(MEMBER, role_id, None, HOMED_USER, C)


def test_community_member_always_needs_members():
    owner = ctx(Assignment("community-member", ()))
    refs = {"mine": ref("mine", LYRA)}
    for value in ((ALL,), (), ("mine",)):
        assert may_assign(
            COMMUNITY_ADMIN, "community-member", value, HOMED_USER, C, refs
        )
        assert not may_assign(owner, "community-member", value, HOMED_USER, C, refs)


def test_an_observer_by_name_needs_manage_on_each_collection():
    refs = {"mine": ref("mine", LYRA), "theirs": ref("theirs", MIA)}
    assert may_assign(MEMBER, "community-observer", ("mine",), HOMED_USER, C, refs)
    assert may_assign(MEMBER, "community-observer", ("mine",), NON_MEMBER_KEY, C, refs)
    assert not may_assign(
        MEMBER, "community-observer", ("theirs",), HOMED_USER, C, refs
    )
    assert not may_assign(
        MEMBER, "community-observer", ("mine", "theirs"), HOMED_USER, C, refs
    )
    assert may_assign(
        COMMUNITY_ADMIN, "community-observer", ("theirs",), HOMED_USER, C, refs
    )
    assert not may_assign(
        MEMBER, "community-observer", ("unknown",), HOMED_USER, C, refs
    )


def test_an_observer_for_everything_or_nothing_needs_members():
    for value in ((ALL,), ()):
        assert may_assign(COMMUNITY_ADMIN, "community-observer", value, HOMED_USER, C)
        assert not may_assign(MEMBER, "community-observer", value, HOMED_USER, C)


def test_roles_go_only_to_their_kind_of_principal():
    assert not may_assign(ROOT, "server-admin", None, HOMED_USER, C)
    assert not may_assign(ROOT, "community-admin", None, SERVER_USER, None)
    assert not may_assign(
        COMMUNITY_ADMIN, "community-member", (ALL,), NON_MEMBER_KEY, C
    )
    assert not may_assign(COMMUNITY_ADMIN, "community-admin", None, MEMBER_KEY, C)


# ── what a key may carry ────────────────────────────────────────────────────────────────────
def test_a_key_carries_only_member_or_observer():
    for role_id in ("server-root", "server-admin", "community-admin", "gate-keeper"):
        assert not may_carry(COMMUNITY_ADMIN, role_id, None, True, C)
    assert not may_carry(MEMBER, "community-member", (ALL,), False, C)
    assert may_carry(MEMBER, "community-member", (ALL,), True, C)


def test_a_key_never_exceeds_its_issuer():
    observer = ctx(Assignment("community-observer", (ALL,)))
    assert not may_carry(
        observer, "community-member", ("c1",), True, C, {"c1": ref("c1")}
    )
    assert may_carry(observer, "community-observer", (ALL,), True, C)
    limited = ctx(Assignment("community-member", ("files",)))
    assert not may_carry(limited, "community-observer", (ALL,), True, C)
    assert may_carry(
        limited, "community-member", ("files",), True, C, {"files": ref("files")}
    )
    assert not may_carry(MEMBER, "community-observer", (ALL,), True, OTHER)


def test_an_owner_may_put_its_own_collections_on_a_key():
    owner_only = ctx(Assignment("community-member", ()))
    refs = {"mine": ref("mine", LYRA), "theirs": ref("theirs", MIA)}
    assert may_carry(owner_only, "community-observer", ("mine",), False, C, refs)
    assert not may_carry(owner_only, "community-observer", ("theirs",), False, C, refs)


def test_a_key_never_exceeds_what_its_issuer_reaches_now():
    member = rbac.UserContext(
        "u",
        "lyra",
        "demo",
        True,
        {
            "read": ("files",),
            "write": ("files",),
            "manage": (),
            "publish": None,
        },
    )
    key = {"read": ("*",), "write": ("files", "lab"), "publish": None, "gate": None}
    capped = rbac.within(key, member, "demo", owned={"lab"})
    assert capped == {
        "read": ("files", "lab"),
        "write": ("files", "lab"),
        "publish": None,
    }
    # an issuer that lost publish takes it from its keys
    narrowed = rbac.UserContext("u", "lyra", "demo", True, {"read": ("*",)})
    assert rbac.within(key, narrowed, "demo") == {"read": ("*",)}
    # a server-level issuer reaches every collection
    root = rbac.UserContext("r", "root", None, True, {"read": ("*",), "gate": None})
    assert rbac.within({"read": ("c1",)}, root, "demo") == {"read": ("c1",)}
