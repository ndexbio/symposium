"""Access, without a server: the key a request presents, the standing it keeps, the UserContext
it resolves to, and the rules the contract sets for each operation (`symposium_data.access`)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from symposium_data.access import Caller, Contract, Rule, authenticate, check, standing
from symposium_data.access.rbac import ALL, Assignment, UserContext, compile_grants
from symposium_data.api_keys import ISSUED, SESSION, KeyRow

SERVICE = Path(__file__).resolve().parents[2]
LYRA, ROOT = uuid.uuid4(), uuid.uuid4()


class Records:
    """The answers authentication asks the records layer for."""

    def __init__(self, users=None, active=(), assignments=None):
        self.users = users if users is not None else {}
        self.active = set(active)
        self.assignments = assignments or {}

    def user(self, conn, user_id):
        return self.users.get(user_id)

    def key_is_active(self, conn, user_id, kid):
        return (user_id, kid) in self.active

    def context_for(
        self,
        conn,
        *,
        principal_id,
        principal_name,
        community,
        via_session,
        user_id=None,
        api_key_id=None,
    ):
        held = self.assignments.get(user_id if user_id is not None else api_key_id, [])
        return UserContext(
            principal_id=principal_id,
            principal_name=principal_name,
            community=community,
            via_session=via_session,
            grants=compile_grants(held),
        )


class Keys:
    def __init__(self, rows: dict):
        self.rows = rows

    def find(self, conn, key):
        return self.rows.get(key)


class Conn:
    def commit(self):
        pass


def request(credential: str | None = None):
    headers = {"authorization": f"Bearer {credential}"} if credential else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host="10.0.0.1"))


def key(kind=ISSUED, user_id=LYRA, community="demo", handle="lyra", kid=None):
    return KeyRow(
        id=uuid.uuid4(),
        kind=kind,
        user_id=user_id,
        community=community,
        handle=handle,
        label=None if kind == SESSION else "notebook",
        created_by=handle or "lyra",
        ed25519_kid=kid,
    )


LYRA_SESSION = key(SESSION, kid="kid-1")
LYRA_KEY = key()
APP_KEY = key(user_id=None, handle=None)
ROOT_SESSION = key(SESSION, user_id=ROOT, community=None, handle="root", kid="kid-r")
USERS = {
    LYRA: {"id": LYRA, "handle": "lyra", "home": "demo", "removed": None},
    ROOT: {"id": ROOT, "handle": "root", "home": None, "removed": None},
}
RECORDS = Records(
    users=USERS,
    active={(LYRA, "kid-1"), (ROOT, "kid-r")},
    assignments={
        LYRA: [Assignment("community-member", (ALL,))],
        ROOT: [Assignment("server-root")],
        LYRA_KEY.id: [Assignment("community-observer", (ALL,))],
        APP_KEY.id: [Assignment("community-observer", ("c1",))],
    },
)
KEYS = Keys(
    {
        "sak_session": LYRA_SESSION,
        "sak_member": LYRA_KEY,
        "sak_app": APP_KEY,
        "sak_root": ROOT_SESSION,
    }
)


def caller(credential, records=RECORDS):
    return authenticate(Conn(), records, KEYS, request(credential))


def test_no_key_is_an_anonymous_caller():
    who = caller(None)
    assert who.anonymous and who.context is None
    assert who.client_addr == "10.0.0.1"


def test_a_session_acts_as_its_user_with_the_users_roles():
    ctx = caller("sak_session").context
    assert (ctx.principal_id, ctx.community, ctx.via_session) == (LYRA, "demo", True)
    assert ctx.grants["publish"] is None and ctx.grants["write"] == (ALL,)


def test_a_member_key_acts_as_its_issuer_with_its_own_roles():
    ctx = caller("sak_member").context
    assert (ctx.principal_id, ctx.principal_name, ctx.via_session) == (
        LYRA,
        "lyra",
        False,
    )
    assert set(ctx.grants) == {"read"}


def test_a_non_member_key_is_its_own_principal():
    ctx = caller("sak_app").context
    assert ctx.principal_id == APP_KEY.id and ctx.grants == {"read": ("c1",)}


def test_a_server_level_session_has_no_community():
    ctx = caller("sak_root").context
    assert ctx.community is None and ctx.allowsRequest("delegate", None)


@pytest.mark.parametrize(
    "credential",
    [
        "sak_unknown",  # unknown or expired: find answers nothing
        "sdr_" + "A" * 43,  # anything without the prefix is no credential here
        "eyJhbGciOiJFZERTQSJ9.e30.x",
    ],
)
def test_anything_but_a_live_key_is_refused_with_401(credential):
    with pytest.raises(HTTPException) as refused:
        caller(credential)
    assert refused.value.status_code == 401


def test_a_removed_users_keys_lose_their_standing():
    removed = {**USERS, LYRA: {**USERS[LYRA], "removed": "2026-11-04"}}
    records = Records(users=removed, active={(LYRA, "kid-1")})
    for row in (LYRA_SESSION, LYRA_KEY):
        assert "removed" in standing(Conn(), records, row)


def test_a_session_ends_with_the_key_that_signed_it_in():
    records = Records(users=USERS, active=set())
    assert "retired" in standing(Conn(), records, LYRA_SESSION)


def test_a_non_member_key_stands_on_itself_alone():
    assert standing(Conn(), Records(), APP_KEY) is None


def signed(*assignments, community="demo", session=True) -> Caller:
    return Caller(
        kind="session" if session else "issued",
        community=community,
        context=UserContext(
            principal_id=LYRA,
            principal_name="lyra",
            community=community,
            via_session=session,
            grants=compile_grants(assignments),
        ),
    )


MEMBER = Assignment("community-member", (ALL,))
OBSERVER = Assignment("community-observer", (ALL,))


@pytest.mark.parametrize(
    "rule, who, community, status",
    [
        # anonymous: only where the operation answers without a key
        (Rule(("read",), None), Caller(kind="anonymous"), "demo", 401),
        (Rule((), "always"), Caller(kind="anonymous"), None, None),
        (Rule(("read",), "public"), Caller(kind="anonymous"), "demo", None),
        # any one of the grants the operation lists, for the request's community
        (Rule(("publish",), None), signed(OBSERVER), "demo", 403),
        (Rule(("publish",), None), signed(MEMBER), "demo", None),
        (Rule(("publish",), None), signed(MEMBER), "other", 403),
        (Rule(("write", "publish", "gate"), None), signed(OBSERVER), "demo", 403),
        (Rule(("communities",), None), signed(MEMBER), None, 403),
        (
            Rule(("communities",), None),
            signed(Assignment("server-admin"), community=None),
            None,
            None,
        ),
        # no grants listed: any key of the community, or a server-level one
        (Rule((), None), signed(OBSERVER), "demo", None),
        (Rule((), None), signed(OBSERVER), "other", 403),
        (
            Rule((), None),
            signed(Assignment("server-admin"), community=None),
            "other",
            None,
        ),
        # and a session where it asks for one
        (Rule((), None, session=True), signed(MEMBER, session=False), "demo", 403),
        (Rule((), None, session=True), signed(MEMBER), "demo", None),
    ],
)
def test_a_rule_lets_in_exactly_whom_its_grants_name(rule, who, community, status):
    if status is None:
        assert check(rule, who, community) is who
        return
    with pytest.raises(HTTPException) as refused:
        check(rule, who, community)
    assert refused.value.status_code == status


def test_the_contract_states_each_rule(tmp_path):
    path = tmp_path / "openapi.yaml"
    path.write_text(
        """
security:
  - apiKey: []
paths:
  /a:
    get:
      operationId: always
      x-grants: []
      x-anonymous: always
      security: [{apiKey: []}, {}]
  /b:
    get:
      operationId: public
      x-grants: [read]
      x-anonymous: public
      security: [{apiKey: []}, {}]
  /c:
    put:
      operationId: session
      x-grants: [members, delegate]
      x-session: true
"""
    )
    rules = Contract(path).rules
    assert rules["always"] == Rule((), "always", False)
    assert rules["public"] == Rule(("read",), "public", False)
    assert rules["session"] == Rule(("members", "delegate"), None, True)


def test_only_authentication_reads_the_bearer_header():
    """One place reads a request's credential, so no route can take a second kind of one."""
    readers = []
    for path in SERVICE.glob("symposium_*/**/*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bbearer\(|headers\.get\(\"authorization\"", text):
            readers.append(path.relative_to(SERVICE).as_posix())
    assert readers == ["symposium_data/access/authn.py"]


def test_a_keyless_server_wide_request_touches_no_database():
    """/v1/status answers while PostgreSQL is down: with no key and no community, authorize
    has nothing to look up."""
    from symposium_data import access
    from symposium_data.access import authz

    class Broken:
        def connection(self):
            raise AssertionError("authorize opened a connection")

    saved = dict(authz._wired)
    access.wire(
        db=Broken(),
        records=RECORDS,
        keys=KEYS,
        contract=SimpleNamespace(rules={"getStatus": Rule((), "always")}),
        public_url="https://data.example.org",
    )
    try:
        dependency = access.authorize("getStatus")
        who = dependency(SimpleNamespace(**vars(request()), path_params={}))
        assert who.anonymous and who.base_url == "https://data.example.org"
        keyed = SimpleNamespace(**vars(request("sak_root")), path_params={})
        with pytest.raises(AssertionError, match="opened a connection"):
            dependency(keyed)  # a key is looked up, so it needs the database
    finally:
        authz._wired.clear()
        authz._wired.update(saved)
