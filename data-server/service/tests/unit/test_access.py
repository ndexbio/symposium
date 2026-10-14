"""Access, without a server: the key a request presents, the standing it keeps, and the rules
the contract sets for each operation (`symposium_data.access`)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from symposium_data.access import Caller, Contract, Rule, authenticate, check, standing
from symposium_data.api_keys import ISSUED, SESSION, KeyRow
from symposium_data.records import ANONYMOUS, Principal

SERVICE = Path(__file__).resolve().parents[2]


class Records:
    """The answers `standing` asks the records layer for."""

    def __init__(self, roster=(), registered=(), active=(), admin_keys=()):
        self.roster, self.registered = set(roster), set(registered)
        self.active, self.admin_keys = set(active), set(admin_keys)

    def on_roster(self, conn, community, handle):
        return (community, handle) in self.roster

    def active_keys(self, conn, community, handle):
        return [{"kid": "k"}] if (community, handle) in self.registered else []

    def key_is_active(self, conn, community, handle, kid):
        return (community, handle, kid) in self.active

    def admin_key_is_active(self, conn, kid):
        return kid in self.admin_keys


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


def key(kind=ISSUED, role="member", community="demo", handle="lyra", kid=None):
    return KeyRow(
        id=uuid.uuid4(),
        kind=kind,
        role=role,
        community=community,
        handle=handle,
        label=None if kind == SESSION else "notebook",
        created_by=handle or "lyra",
        ed25519_kid=kid,
    )


LYRA_SESSION = key(SESSION, kid="kid-1")
LYRA_KEY = key()
APP_KEY = key(role="non-member", handle=None)
ADMIN_SESSION = key(SESSION, role="admin", community=None, handle="admin", kid="kid-a")
RECORDS = Records(
    roster={("demo", "lyra")},
    registered={("demo", "lyra")},
    active={("demo", "lyra", "kid-1")},
    admin_keys={"kid-a"},
)
KEYS = Keys(
    {
        "sak_session": LYRA_SESSION,
        "sak_member": LYRA_KEY,
        "sak_app": APP_KEY,
        "sak_admin": ADMIN_SESSION,
    }
)


def caller(credential, community="demo", records=RECORDS):
    return authenticate(Conn(), records, KEYS, request(credential), community)


def test_no_key_is_an_anonymous_caller():
    who = caller(None)
    assert who.anonymous and who.role is None and who.principal() == ANONYMOUS
    assert who.client_addr == "10.0.0.1"


@pytest.mark.parametrize(
    "credential, kind, role, principal",
    [
        ("sak_session", "session", "member", Principal(handle="lyra")),
        ("sak_member", "issued", "member", Principal(handle="lyra")),
        ("sak_app", "issued", "non-member", Principal(api_key_id=APP_KEY.id)),
        ("sak_admin", "session", "admin", Principal(handle="admin")),
    ],
)
def test_a_key_names_its_caller(credential, kind, role, principal):
    who = caller(credential)
    assert (who.kind, who.role, who.principal()) == (kind, role, principal)


@pytest.mark.parametrize(
    "credential",
    [
        "sak_unknown",  # unknown, revoked or expired: find answers nothing
        "sdr_" + "A" * 43,  # a read key is no credential here
        "eyJhbGciOiJFZERTQSJ9.e30.x",  # nor a JWT
    ],
)
def test_anything_but_a_live_key_is_refused_with_401(credential):
    with pytest.raises(HTTPException) as refused:
        caller(credential)
    assert refused.value.status_code == 401


def test_a_key_of_another_community_is_refused_with_403():
    with pytest.raises(HTTPException) as refused:
        caller("sak_member", community="other")
    assert refused.value.status_code == 403
    assert "belongs to demo" in refused.value.detail


def test_the_admins_session_works_in_every_community():
    assert caller("sak_admin", community="other").admin
    assert caller("sak_admin", community=None).admin


@pytest.mark.parametrize(
    "row, records, why",
    [
        (LYRA_KEY, Records(registered={("demo", "lyra")}), "no longer on the roster"),
        (LYRA_KEY, Records(roster={("demo", "lyra")}), "no registered key"),
        (
            LYRA_SESSION,
            Records(roster={("demo", "lyra")}, registered={("demo", "lyra")}),
            "retired",
        ),
        (ADMIN_SESSION, Records(), "retired"),
    ],
)
def test_a_key_loses_its_standing_with_what_it_stands_on(row, records, why):
    status, detail = standing(Conn(), records, row, "demo")
    assert status == 401 and why in detail


def test_a_non_member_key_stands_on_itself_alone():
    assert standing(Conn(), Records(), APP_KEY, "demo") is None


def anonymous() -> Caller:
    return Caller(kind="anonymous")


def signed(kind, role) -> Caller:
    return Caller(kind=kind, role=role, handle="lyra")


@pytest.mark.parametrize(
    "rule, who, status",
    [
        # anonymous: only where the operation answers without a key
        (Rule(("non-member", "member", "admin"), None), anonymous(), 401),
        (Rule(("non-member", "member", "admin"), "always"), anonymous(), None),
        (Rule(("non-member", "member", "admin"), "public"), anonymous(), None),
        # the roles the operation lists
        (Rule(("member",), None), signed("issued", "non-member"), 403),
        (Rule(("member",), None), signed("issued", "member"), None),
        (Rule(("member", "admin"), None), signed("session", "admin"), None),
        (Rule(("non-member", "member"), None), signed("session", "admin"), 403),
        # and a session where it asks for one
        (
            Rule(("member", "admin"), None, session=True),
            signed("issued", "member"),
            403,
        ),
        (
            Rule(("member", "admin"), None, session=True),
            signed("session", "member"),
            None,
        ),
        (Rule(("admin",), None, session=True), signed("session", "admin"), None),
    ],
)
def test_a_rule_lets_in_exactly_whom_it_names(rule, who, status):
    if status is None:
        assert check(rule, who) is who
        return
    with pytest.raises(HTTPException) as refused:
        check(rule, who)
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
      x-roles: [non-member, member, admin]
      x-anonymous: always
      security: [{apiKey: []}, {}]
  /b:
    get:
      operationId: public
      x-roles: [non-member, member]
      x-anonymous: public
      security: [{apiKey: []}, {}]
  /c:
    put:
      operationId: session
      x-roles: [member, admin]
      x-session: true
"""
    )
    rules = Contract(path).rules
    assert rules["always"] == Rule(("non-member", "member", "admin"), "always", False)
    assert rules["public"] == Rule(("non-member", "member"), "public", False)
    assert rules["session"] == Rule(("member", "admin"), None, True)


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
        contract=SimpleNamespace(rules={"getStatus": Rule(("admin",), "always")}),
        public_url="https://data.example.org",
    )
    try:
        dependency = access.authorize("getStatus")
        who = dependency(SimpleNamespace(**vars(request()), path_params={}))
        assert who.anonymous and who.base_url == "https://data.example.org"
        keyed = SimpleNamespace(**vars(request("sak_admin")), path_params={})
        with pytest.raises(AssertionError, match="opened a connection"):
            dependency(keyed)  # a key is looked up, so it needs the database
    finally:
        authz._wired.clear()
        authz._wired.update(saved)
