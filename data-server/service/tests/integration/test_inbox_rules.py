"""`inbox`: a submission takes `publish`, a reply takes `gate`, and nothing else goes in. The
submitter sees its own items and the replies addressed to it, the gate sees every item, and an
item never changes. `inbox` is never public and has no owner."""

from conftest import EVERY, Owner, community_with, enroll, steward_of
from harness import HTTP

SUBMISSION = {"symposium_submission": True}


def reply_to(*handles):
    return {"symposium_reply": True, "recipients": list(handles)}


def inbox_items(owner, headers=None):
    r = HTTP.get(
        owner.url("/collections/inbox/changes"), headers=headers or owner.headers()
    )
    assert r.status_code == 200, r.text
    return {i["name"] for i in r.json()["items"]}


def test_a_submission_takes_publish(server):
    root, owners = community_with(server, members=("lyra", "olive"))
    lyra, olive = owners["lyra"], owners["olive"]
    steward = steward_of(server)
    gate = Owner(server, "bob")
    enroll(steward, gate, "demo", roles=[{"role": "gate-keeper", "collections": None}])
    root.unassign("community-member", None, "olive", "demo")
    root.assign("community-observer", EVERY, "olive", "demo")
    olive._session = None
    assert lyra.put("demo", "inbox", "a@1", b"{}", SUBMISSION).status_code == 201
    for refused in (olive, steward, gate, root):  # no publish
        assert refused.put("demo", "inbox", "x@1", b"{}", SUBMISSION).status_code == 403
    assert lyra.put("demo", "inbox", "plain", b"{}").status_code == 403  # unmarked


def test_a_reply_takes_gate(server):
    _, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    steward = steward_of(server)
    gate = Owner(server, "bob")
    enroll(steward, gate, "demo", roles=[{"role": "gate-keeper", "collections": None}])
    assert lyra.put("demo", "inbox", "r0", b"{}", reply_to("lyra")).status_code == 403
    assert gate.put("demo", "inbox", "r1", b"{}", reply_to("lyra")).status_code == 201
    assert (
        steward.put("demo", "inbox", "r2", b"{}", reply_to("lyra")).status_code == 201
    )


def test_each_caller_sees_its_own_items_and_the_gate_sees_all(server):
    root, owners = community_with(server, members=("lyra", "vega", "olive"))
    lyra, vega, olive = owners["lyra"], owners["vega"], owners["olive"]
    steward = steward_of(server)
    root.unassign("community-member", None, "olive", "demo")
    root.assign("community-observer", EVERY, "olive", "demo")
    olive._session = None
    mine = lyra.put("demo", "inbox", "lyra_a@1", b"{}", SUBMISSION).json()["file_id"]
    vega.put("demo", "inbox", "vega_a@1", b"{}", SUBMISSION)
    steward.put("demo", "inbox", "to_lyra", b"{}", reply_to("lyra"))
    assert inbox_items(steward) == {"lyra_a@1", "vega_a@1", "to_lyra"}
    assert inbox_items(lyra) == {"lyra_a@1", "to_lyra"}
    assert inbox_items(vega) == {"vega_a@1"}
    assert steward.get(mine).status_code == 200
    assert vega.get(mine).status_code == 403
    assert olive.get(mine).status_code == 403
    listed = HTTP.get(olive.url("/collections/inbox/changes"), headers=olive.headers())
    assert listed.status_code == 403  # no publish, no gate
    # a member key carries publish: it submits and sees its member's items
    key = lyra.issue("script")
    bearer = {"Authorization": f"Bearer {key['key']}"}
    assert inbox_items(lyra, bearer) == {"lyra_a@1", "to_lyra"}
    observer = steward.issue(
        "app",
        roles=[{"role": "community-observer", "collections": EVERY}],
        non_member=True,
    )
    by_app = {"Authorization": f"Bearer {observer['key']}"}
    assert (
        HTTP.get(steward.url("/collections/inbox/changes"), headers=by_app).status_code
        == 403
    )


def test_an_inbox_item_never_changes_and_inbox_is_never_public(server):
    root, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    steward = steward_of(server)
    fid = lyra.put("demo", "inbox", "lyra_a@1", b"{}", SUBMISSION).json()["file_id"]
    for actor in (lyra, steward, root):
        assert actor.version(fid, b"{}", SUBMISSION).status_code == 403
        assert actor.delete(fid).status_code == 403
    public = HTTP.patch(
        steward.url("/collections/inbox"),
        json={"public": True},
        headers=root.headers(),
    )
    assert public.status_code == 403
    assert HTTP.get(lyra.url(f"/files/{fid}/versions/latest")).status_code == 401
