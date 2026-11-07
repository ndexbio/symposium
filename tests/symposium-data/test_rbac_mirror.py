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


def test_the_runbooks_role_table_names_the_six_roles():
    """RUNBOOK.md §8.1 describes exactly the roles the server defines."""
    from suite import REPO

    runbook = (REPO / "data-server" / "RUNBOOK.md").read_text(encoding="utf-8")
    section = runbook.split("### 8.1 The model", 1)[1].split("###", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    named = {line.split("`")[1] for line in rows if line.split("`")[1] in server.ROLES}
    assert named == set(server.ROLES)
