"""The CLI's access-role module (tools/symposium-data/rbac.py) is the server's: the same grants,
roles and collection-scoped grants, and `allowsRequest` deciding every case the same way."""

import itertools

import rbac as client
from symposium_data.access import rbac as server


def test_the_grants_and_roles_are_the_servers():
    assert client.GRANTS == server.GRANTS
    assert client.COLLECTION_SCOPED == server.COLLECTION_SCOPED
    assert (client.ALL, client.INBOX) == (server.ALL, server.INBOX)
    assert set(client.ROLES) == set(server.ROLES)
    assert client.TAKES_COLLECTIONS == {
        r.id for r in server.ROLES.values() if r.takes_collections
    }


def test_allows_request_decides_every_case_as_the_server_does():
    values = [None, (), (client.ALL,), ("c1",), ("c1", "c2")]
    communities = [None, "demo", "other"]
    collections = [None, "c1", "c3", "inbox"]
    owners = [None, "me", "someone"]
    for grant, value, own, via_session, asked, name, owner in itertools.product(
        ("read", "publish"),
        values,
        communities,
        (True, False),
        communities,
        collections,
        owners,
    ):
        if (grant == "publish") != (value is None):
            continue
        grants = {grant: value}
        ours = client.UserContext("me", own, via_session, grants)
        theirs = server.UserContext("me", "me", own, via_session, grants)
        collection = None if name is None else client.CollectionRef(name, owner)
        reference = None if name is None else server.CollectionRef(name, owner)
        assert ours.allowsRequest(grant, asked, collection) == theirs.allowsRequest(
            grant, asked, reference
        ), (grant, value, own, via_session, asked, name, owner)
        assert not ours.allowsRequest("gate", asked)


def rbac_doc_table(heading: str) -> dict:
    """A table of RBAC.md, by its first column's name: {name: the row's other cells}."""
    from suite import REPO

    doc = (REPO / "data-server" / "RBAC.md").read_text(encoding="utf-8")
    section = doc.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        if line.startswith("| `"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            rows[cells[0].strip("`")] = cells[1:]
    return rows


def test_rbac_md_defines_the_nine_grants():
    """RBAC.md's grants table names exactly the grants the server defines."""
    assert set(rbac_doc_table("Grants")) == set(server.GRANTS)


def test_rbac_md_gives_each_role_the_servers_grants():
    """RBAC.md's roles table names exactly the six roles, each with exactly its grants, and
    with the collections a user holding it always reads."""
    roles = rbac_doc_table("Roles")
    assert set(roles) == set(server.ROLES)
    for role in server.ROLES.values():
        grants_cell = roles[role.id][1]
        named = {g for g in server.GRANTS if f"`{g}`" in grants_cell}
        assert named == set(role.grants), role.id
        for collection in role.user_reads:
            assert f"always reads `{collection}`" in grants_cell, role.id
