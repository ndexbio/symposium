"""Who may do what to a collection: every kind of caller against every file operation, with the
collection private, public, and private again. Each case asserts its status and its effect: the
bytes or rows an allowed read answers, and, for a refused write, that nothing was stored.

`lab` is lyra's collection. orion is granted read, nova read and write, vega nothing. app_ok is
a non-member key lyra issued and granted read, app_no one she did not grant, and app_other a
non-member key of another community, granted there.
"""

from __future__ import annotations

import base64
import hashlib
import itertools

import pytest
from conftest import Owner, enroll, init_admin, psql, set_roster
from harness import HTTP

STATES = {
    "private": [False],
    "public": [True],
    "private again": [True, False],
}

# Every caller: how it is made, and what it may do to `lab`. `reads` is the status of a read
# while `lab` is private; a public `lab` answers 200 to every caller of this community.
CALLERS = {
    "anonymous": {"reads": 401, "writes": 401, "manage": 401},
    "admin session": {"reads": 200, "writes": "all", "manage": 200},
    "lyra session": {"reads": 200, "writes": "all", "manage": 200},
    "lyra member key": {"reads": 200, "writes": "all", "manage": 403},
    "orion session": {"reads": 200, "writes": 403, "manage": 403},
    "orion member key": {"reads": 200, "writes": 403, "manage": 403},
    "nova session": {"reads": 200, "writes": "create", "manage": 403},
    "nova member key": {"reads": 200, "writes": "create", "manage": 403},
    "vega session": {"reads": 403, "writes": 403, "manage": 403},
    "vega member key": {"reads": 403, "writes": 403, "manage": 403},
    "app_ok": {"reads": 200, "writes": 403, "manage": 403},
    "app_no": {"reads": 403, "writes": 403, "manage": 403},
    "app_other": {"reads": 403, "writes": 403, "manage": 403, "elsewhere": True},
}
DATA = b"lab result"


def bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def world(server):
    admin = init_admin(server)
    set_roster(server, admin, "demo", ["lyra", "orion", "nova", "vega", "rigel"])
    owners = {}
    for handle in ("lyra", "orion", "nova", "vega"):
        owners[handle] = Owner(server, handle)
        assert enroll(admin, owners[handle], "demo").status_code == 201
    lyra = owners["lyra"]
    r = HTTP.post(
        lyra.url("/collections"), json={"name": "lab"}, headers=lyra.headers()
    )
    assert r.status_code == 201, r.text
    for handle, perms in (("orion", ["read"]), ("nova", ["read", "write"])):
        for perm in perms:
            r = HTTP.put(
                lyra.url("/collections/lab/grants"),
                json={"handle": handle, "perm": perm},
                headers=lyra.headers(),
            )
            assert r.status_code == 200, r.text
    app_ok = lyra.issue("app ok", role="non-member")
    r = HTTP.put(
        lyra.url("/collections/lab/grants"),
        json={"api_key_id": app_ok["id"], "perm": "read"},
        headers=lyra.headers(),
    )
    assert r.status_code == 200, r.text
    app_no = lyra.issue("app no", role="non-member")

    set_roster(server, admin, "other", ["bob"])
    bob = Owner(server, "bob")
    enroll(admin, bob, "other")
    r = HTTP.post(bob.url("/collections"), json={"name": "lab"}, headers=bob.headers())
    assert r.status_code == 201, r.text
    app_other = HTTP.post(
        bob.url("/api-keys"),
        json={"label": "app other", "role": "non-member"},
        headers=bob.headers(),
    ).json()
    r = HTTP.put(
        bob.url("/collections/lab/grants"),
        json={"api_key_id": app_other["id"], "perm": "read"},
        headers=bob.headers(),
    )
    assert r.status_code == 200, r.text

    headers = {
        "anonymous": {},
        "admin session": admin.headers(),
        "app_ok": bearer(app_ok["key"]),
        "app_no": bearer(app_no["key"]),
        "app_other": bearer(app_other["key"]),
    }
    for handle in ("lyra", "orion", "nova", "vega"):
        headers[f"{handle} session"] = owners[handle].headers()
        headers[f"{handle} member key"] = bearer(
            owners[handle].issue("notebook")["key"]
        )
    assert set(headers) == set(CALLERS)

    the_file = lyra.put("demo", "lab", "result.csv", DATA).json()
    # one file of lyra's per caller, for that caller to try to version and delete
    targets = {
        who: lyra.put("demo", "lab", f"target-{n}.csv", b"target").json()["file_id"]
        for n, who in enumerate(CALLERS)
    }
    return server, admin, lyra, headers, the_file, targets


def set_public(server, headers, public: bool):
    return HTTP.put(
        f"{server.url}/v1/demo/collections/lab/public",
        json={"public": public},
        headers=headers,
    )


def count(server, sql: str) -> int:
    return int(psql(server, sql))


def files_in_lab(server) -> int:
    return count(
        server,
        "SELECT count(*) FROM files WHERE community = 'demo' AND collection = 'lab'",
    )


def versions_of(server, file_id) -> int:
    return count(server, f"SELECT count(*) FROM versions WHERE file_id = '{file_id}'")


def check_reads(server, who, headers, the_file, expected):
    """Content, stat, versions and the three listings: `expected` for each, with the file's
    bytes or row when allowed."""
    fid, base = the_file["file_id"], f"{server.url}/v1/demo"
    content = HTTP.get(f"{base}/files/{fid}/v/1", headers=headers)
    assert content.status_code == expected, (who, "content", content.text)
    if expected == 200:
        assert content.content == DATA, who
    stat = HTTP.get(f"{base}/files/{fid}/v/1/stat", headers=headers)
    assert stat.status_code == expected, (who, "stat", stat.text)
    if expected == 200:
        assert stat.json()["sha256"] == the_file["sha256"], who
    versions = HTTP.get(f"{base}/files/{fid}/versions", headers=headers)
    assert versions.status_code == expected, (who, "versions", versions.text)
    if expected == 200:
        assert [v["version"] for v in versions.json()["versions"]] == [1], who

    changes = HTTP.get(f"{base}/collections/lab/changes", headers=headers)
    assert changes.status_code == expected, (who, "changes", changes.text)
    if expected == 200:
        assert fid in {i["file_id"] for i in changes.json()["items"]}, who
    query = HTTP.post(
        f"{base}/collections/lab/query", json={"contains": {}}, headers=headers
    )
    assert query.status_code == expected, (who, "query", query.text)
    if expected == 200:
        assert fid in {i["file_id"] for i in query.json()["items"]}, who
    found = HTTP.get(
        f"{base}/collections/lab/find", params={"name": "result.csv"}, headers=headers
    )
    assert found.status_code == expected, (who, "find", found.text)
    if expected == 200:
        assert found.json()["file_id"] == fid, who


def check_lookups(server, who, headers, the_file, readable: bool, elsewhere: bool):
    """The content lookups never refuse a caller of this community: they answer only what it
    may read. A key of another community is refused."""
    base, fid = f"{server.url}/v1/demo", the_file["file_id"]
    sha = hashlib.sha256(DATA).hexdigest()
    by_hash = HTTP.get(f"{base}/sha256/{sha}", headers=headers)
    verify = HTTP.get(
        f"{base}/verify", params={"cite": the_file["citation"]}, headers=headers
    )
    if elsewhere:
        assert (by_hash.status_code, verify.status_code) == (403, 403), who
        return
    assert by_hash.status_code == 200, (who, by_hash.text)
    found = [i["file_id"] for i in by_hash.json()["items"]]
    assert found == ([fid] if readable else []), who
    assert verify.status_code == 200, (who, verify.text)
    assert verify.json()["exists"] is readable, who


def check_writes(server, who, headers, target, allowed):
    """Create, version and delete: what `allowed` permits succeeds, the rest is refused and
    stores nothing."""
    base = f"{server.url}/v1/demo"
    data = f"from {who}".encode()
    digest = {
        "Repr-Digest": "sha-256=:"
        + base64.b64encode(hashlib.sha256(data).digest()).decode()
        + ":"
    }
    name = "new-" + hashlib.sha1(who.encode()).hexdigest()[:8] + ".csv"
    before = files_in_lab(server)
    created = HTTP.put(
        f"{base}/collections/lab/files/{name}",
        content=data,
        headers={**headers, **digest},
    )
    if allowed in ("all", "create"):
        assert created.status_code == 201, (who, "create", created.text)
        assert files_in_lab(server) == before + 1, who
    else:
        assert created.status_code == allowed, (who, "create", created.text)
        assert files_in_lab(server) == before, who

    expected = 201 if allowed == "all" else (403 if allowed == "create" else allowed)
    versions = versions_of(server, target)
    added = HTTP.post(
        f"{base}/files/{target}/versions", content=data, headers={**headers, **digest}
    )
    assert added.status_code == expected, (who, "version", added.text)
    assert versions_of(server, target) == versions + (1 if expected == 201 else 0), who

    versions = versions_of(server, target)
    deleted = HTTP.delete(f"{base}/files/{target}", headers=headers)
    expected = 200 if allowed == "all" else (403 if allowed == "create" else allowed)
    assert deleted.status_code == expected, (who, "delete", deleted.text)
    assert versions_of(server, target) == versions + (1 if expected == 200 else 0), who


def check_manage(server, who, headers, expected, public: bool):
    """Grant and withdraw read for rigel, and set `lab`'s public flag to what it already is:
    allowed callers leave `lab` as they found it; refused ones change nothing."""
    url = f"{server.url}/v1/demo/collections/lab/grants"
    granted = HTTP.put(url, json={"handle": "rigel", "perm": "read"}, headers=headers)
    assert granted.status_code == expected, (who, "grant", granted.text)
    rows = count(
        server,
        "SELECT count(*) FROM grants WHERE handle = 'rigel' AND collection = 'lab'",
    )
    assert rows == (1 if expected == 200 else 0), who
    if expected == 200:
        withdrawn = HTTP.put(
            url,
            json={"handle": "rigel", "perm": "read", "granted": False},
            headers=headers,
        )
        assert withdrawn.status_code == 200, who
    flagged = set_public(server, headers, public)
    assert flagged.status_code == expected, (who, "public", flagged.text)
    assert psql(
        server,
        "SELECT public FROM collections WHERE community = 'demo' AND name = 'lab'",
    ) == ("t" if public else "f"), who


@pytest.mark.parametrize("state", STATES)
def test_every_caller_gets_exactly_the_access_its_collection_gives(world, state):
    server, admin, lyra, headers, the_file, targets = world
    for public in STATES[state]:
        assert set_public(server, lyra.headers(), public).status_code == 200
    public = STATES[state][-1]

    for who, rule in CALLERS.items():
        elsewhere = rule.get("elsewhere", False)
        reads = 200 if public and not elsewhere else rule["reads"]
        check_reads(server, who, headers[who], the_file, reads)
        check_lookups(server, who, headers[who], the_file, reads == 200, elsewhere)
    for who, rule in CALLERS.items():
        check_writes(server, who, headers[who], targets[who], rule["writes"])
        check_manage(server, who, headers[who], rule["manage"], public)


def test_the_matrix_covers_every_kind_of_caller():
    """Anonymous, the admin, a Member through a session and through an issued key, for an
    owner, a reader, a writer and a Member with no grant, and non-member keys granted, not
    granted, and of another community."""
    kinds = {who.split(" ")[-1] for who in CALLERS}
    assert {"anonymous", "session", "key", "app_ok", "app_no", "app_other"} <= kinds
    members = {who.split(" ")[0] for who in CALLERS if who.endswith(("session", "key"))}
    assert members == {"admin", "lyra", "orion", "nova", "vega"}
    assert len(list(itertools.product(CALLERS, STATES))) == 39
