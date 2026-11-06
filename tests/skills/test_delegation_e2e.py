"""Delegated administration end to end: the runbook's walkthroughs and recipes (RUNBOOK.md
§8), run with the real skill and CLI against the data server's image. Each person is an
`Actor` with a HOME of their own; only invite files move between them. A refusal is the
server's answer, or the skill's own when the session's access lacks the grant a command
takes."""

from __future__ import annotations

import base64
import hashlib
import json
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from harness import HTTP, MAX_WAIT, TEST_ENV, Output, OwnerKey, Server, place_key
from previous import PREVIOUS, seed
from skills.test_workflow import note
from suite import ROOT, SKILL, Actor, community_file, place_root_key


# ── the people ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def people(suite, server, tmp_path):
    """Make actors on demand: `people("ana")`; root works on the suite's own machine, where
    its key is."""
    made = {}

    def actor(handle: str) -> Actor:
        if handle not in made:
            home = suite.home if handle == ROOT else tmp_path / handle
            made[handle] = Actor(suite, home, handle)
        return made[handle]

    return actor


@pytest.fixture
def root(people, server) -> Actor:
    """Root, with its server-level session: `admin-config` reuses the key it bound."""
    root = people(ROOT)
    root.ok("admin-config", "--handle", ROOT, "--data-server-url", server.url)
    return root


def server_admin(root: Actor, people, handle: str) -> Actor:
    """Root delegates a server admin, who joins on their own machine."""
    admin = people(handle)
    admin.join(root.invite(handle, "server-admin"))
    return admin


def community(
    server, admin: Actor, people, name="demo", first_admin="steward"
) -> Actor:
    """A server admin bootstraps a community; its first community admin joins."""
    spec = community_file(admin.work, server, name, first_admin=first_admin)
    files = admin.ok("bootstrap", "--community-file", spec)["invite_files"]
    [invite] = [Path(f) for f in files if f.endswith(f"{name}-{first_admin}.invite")]
    steward = people(first_admin)
    steward.join(invite)
    return steward


def member(steward: Actor, people, handle: str, access="community-member:*") -> Actor:
    """A community admin invites a user, who joins on their own machine."""
    person = people(handle)
    person.join(steward.invite(handle, access))
    return person


def grants(actor: Actor) -> dict:
    return actor.ok("access")["context"]["grants"]


def roles(actor: Actor) -> list:
    return actor.ok("access")["roles"]


# ── calls an application makes with an issued key ──────────────────────────────────────────
def api(server, key: str | None, method: str, path: str, community="demo", **kw):
    headers = kw.pop("headers", {})
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    return HTTP.request(
        method, f"{server.url}/v1/communities/{community}{path}", headers=headers, **kw
    )


def changes(server, key, collection, community="demo") -> int:
    return api(
        server, key, "GET", f"/collections/{collection}/changes", community
    ).status_code


def upload(server, key: str, collection: str, name: str, community="demo") -> int:
    """An application's upload with an issued key: a new file, by name."""
    data = b"a,b\n"
    digest = (
        "sha-256=:" + base64.b64encode(hashlib.sha256(data).digest()).decode() + ":"
    )
    headers = {
        "If-None-Match": "*",
        "Content-Type": "text/csv",
        "Repr-Digest": digest,
    }
    path = f"/collections/{collection}/files/{name}"
    return api(
        server, key, "PUT", path, community, content=data, headers=headers
    ).status_code


def put_file(actor: Actor, collection: str, name: str) -> dict:
    source = actor.work / name
    source.write_text("gene,score\nBST2,0.91\n")
    return actor.ok("data", "put", source, "--collection", collection, "--name", name)


def publish(actor: Actor, topic: str) -> Path:
    artifact = note(actor.work, actor.handle, topic)
    code, out = actor.report("publish", artifact)
    assert code == 0 and "submitted  symposium-data:" in out, out
    return artifact


def gate(actor: Actor) -> str:
    code, out = actor.report("gate")
    assert code == 0, out
    return out


# ── S0: the runbook's walkthrough, command for command ─────────────────────────────────────
def test_s0_from_an_empty_server_to_a_community_run_by_its_own_admin(
    server, root, people
):
    # 1. root delegates a server admin
    ana = server_admin(root, people, "ana")
    assert [r["role"] for r in roles(ana)] == ["server-admin"]
    held = grants(ana)
    assert "delegate" not in held and held["read"] == ["*"]
    listed = root.ok("users", "list", "--server")["users"]
    assert "ana" in [u["handle"] for u in listed]

    # 2. the server admin creates a community; 3. its community admin invites a member
    steward = community(server, ana, people)
    assert [r["role"] for r in roles(steward)] == ["community-admin"]
    assert {"gate", "members", "export"} <= set(grants(steward))
    lyra = member(steward, people, "lyra")
    assert "publish" in grants(lyra)

    # the member publishes; 4. the community admin runs the gate to a decision
    publish(lyra, "seed")
    assert "ACCEPTED" in gate(steward)
    code, out = lyra.report("sync")
    assert code == 0 and "+1: lyra_note_seed_v1" in out, out

    # 5. a member's collection-limited key for an application
    for name in ("c1", "c2", "c3"):
        lyra.ok("data", "collection", "create", "--name", name)
        put_file(lyra, name, f"{name}.csv")
    issued = lyra.ok(
        "gen-api-key", "app", "--non-member", "--access", "community-observer:c1,c2"
    )
    key = lyra.api_key(issued)
    assert [changes(server, key, c) for c in ("c1", "c2", "c3")] == [200, 200, 403]
    lyra.ok("assign", "--api-key", issued["id"], "--access", "community-observer:c3")
    lyra.ok("unassign", "--api-key", issued["id"], "--access", "community-observer:c1")
    assert [changes(server, key, c) for c in ("c1", "c2", "c3")] == [403, 200, 200]

    # 6. a whole-community observer key reads the record, and nothing more
    issued = lyra.ok("gen-api-key", "script", "--access", "community-observer:*")
    key = lyra.api_key(issued)
    listed = api(server, key, "GET", "/artifacts").json()["items"]
    assert [a["name"] for a in listed] == ["lyra_note_seed_v1"]
    one = api(server, key, "GET", "/artifacts/lyra_note_seed_v1")
    assert one.status_code == 200
    submitted = api(
        server,
        key,
        "POST",
        "/submissions",
        json=json.loads(note(lyra.work, "lyra", "more").read_text()),
    )
    assert submitted.status_code == 403
    lyra.ok("revoke-api-key", issued["id"])
    assert api(server, key, "GET", "/artifacts").status_code == 401


def refused(
    result: tuple[int, dict], status: int | None = 403, grant: str | None = None
):
    """A command the server refused with `status`, or the skill before it, naming the grant
    the session's access lacks."""
    code, out = result
    assert code == 1, out
    if grant is not None and "status" not in out:
        assert f"`{grant}`" in out["error"], out
    else:
        assert out.get("status") == status, out
    return out


def accepted(steward: Actor, author: Actor, topic: str) -> str:
    """`author` publishes, and the gate accepts it. -> the artifact's name."""
    publish(author, topic)
    assert "ACCEPTED" in gate(steward)
    return f"{author.handle}_note_{topic}_v1"


@pytest.fixture
def demo(server, root, people):
    """root, the server admin ana, and `demo`, run by its community admin steward, with lyra
    a community-member on every collection."""
    ana = server_admin(root, people, "ana")
    steward = community(server, ana, people)
    lyra = member(steward, people, "lyra")
    return ana, steward, lyra


# ── S1: delegation stops at server admins ──────────────────────────────────────────────────
def test_s1_a_server_admin_cannot_delegate_and_nobody_assigns_server_root(root, people):
    ana = server_admin(root, people, "ana")
    out = ana.work / "ben.invite"
    refused(
        ana.run("invite", "--handle", "ben", "--access", "server-admin", "--out", out)
    )
    refused(
        root.run("assign", "--handle", "ana", "--server", "--access", "server-root")
    )
    assert [r["role"] for r in roles(ana)] == ["server-admin"]


# ── S2: a community is created with its first community admin ──────────────────────────────
def test_s2_a_community_needs_its_first_admin(server, root, people):
    ana = server_admin(root, people, "ana")
    spec = ana.work / "community.json"
    spec.write_text(json.dumps({"community": "demo", "data-server-url": server.url}))
    code, out = ana.run("bootstrap", "--community-file", spec)
    assert code == 1 and any("admin: missing" in p for p in out["problems"]), out
    steward = community(server, ana, people)
    context = steward.ok("access")["context"]
    assert context["community"] == "demo"
    assert {g: context["grants"][g] for g in ("read", "write", "manage")} == {
        "read": ["*"],
        "write": ["*"],
        "manage": ["*"],
    }


# ── S3: a gate-keeper gates, an observer reads ─────────────────────────────────────────────
def test_s3_a_gate_keeper_gates_and_an_observer_only_reads(demo, people):
    _, steward, lyra = demo
    gwen = member(steward, people, "gwen", "gate-keeper")
    assert set(grants(gwen)) == {"read", "gate"}
    publish(lyra, "seed")
    assert "ACCEPTED" in gate(gwen)
    out = gwen.work / "x.invite"
    refused(
        gwen.run(
            "invite", "--handle", "x", "--access", "community-member:*", "--out", out
        ),
        grant="members",
    )
    refused(gwen.run("export", "--out", gwen.work / "demo.tar"), grant="export")
    refused(
        gwen.run(
            "purge", "--cite", "symposium-data:00000000-0000-0000-0000-000000000000@v1"
        ),
        grant="manage",
    )

    olive = member(steward, people, "olive", "community-observer:*")
    code, out = olive.report("sync")  # setup synced it already
    assert code == 0 and "up to date — 1 artifact(s)" in out, out
    code, out = olive.report("publish", note(olive.work, "olive", "no"))
    assert code == 1 and "`publish`" in out, out
    refused(olive.run("data", "collection", "create", "--name", "mine"))


# ── S4: a member limited to what it creates ────────────────────────────────────────────────
def test_s4_an_empty_collection_value_reaches_what_its_holder_creates(demo, people):
    _, steward, lyra = demo
    lyra.ok("data", "collection", "create", "--name", "c1")
    mia = member(steward, people, "mia", "community-member:")
    assert grants(mia)["read"] == ["record"]  # a publisher reads the record
    mia.ok("data", "collection", "create", "--name", "m1")
    made = put_file(mia, "m1", "m.csv")
    assert (
        mia.ok("data", "changes", "--collection", "m1")["items"][0]["name"] == "m.csv"
    )
    mia.ok("data", "collection", "set-public", "--collection", "m1", "--public")
    mia.ok("data", "version", made["file_id"], mia.work / "m.csv")
    refused(mia.run("data", "changes", "--collection", "c1"))
    refused(mia.run("data", "changes", "--collection", "files"))


# ── S5: administrative roles never publish; members never reply ────────────────────────────
def test_s5_admins_cannot_publish_and_members_cannot_reply(demo):
    ana, steward, lyra = demo
    code, out = steward.report("publish", note(steward.work, "steward", "mine"))
    assert code == 1 and "`publish`" in out, out
    ana.ok("use-community", "demo")
    code, out = ana.report("publish", note(ana.work, "ana", "mine"))
    assert code == 1 and "`publish`" in out, out
    reply = lyra.work / "reply.json"
    reply.write_text("{}")
    refused(
        lyra.run(
            "data",
            "put",
            reply,
            "--collection",
            "inbox",
            "--name",
            "reply.json",
            "--metadata",
            json.dumps({"symposium_reply": True}),
        )
    )


# ── S6: communities are tenants ────────────────────────────────────────────────────────────
def test_s6_homed_users_stay_in_their_community_and_server_admins_reach_both(
    server, demo, people
):
    ana, steward, lyra = demo
    otto = community(server, ana, people, "other", "otto")
    for actor, own in ((steward, "demo"), (lyra, "demo"), (otto, "other")):
        issued = actor.ok("gen-api-key", "probe", "--access", "community-observer:*")
        key = actor.api_key(issued)
        foreign = "other" if own == "demo" else "demo"
        assert changes(server, key, "record", own) == 200
        assert changes(server, key, "record", foreign) == 403
    for name in ("demo", "other"):
        ana.ok("use-community", name)
        assert ana.ok("data", "changes", "--collection", "record")["items"] == []


# ── S7: community admins appoint and demote each other ─────────────────────────────────────
def test_s7_community_admins_hand_over_and_the_last_one_stays(demo):
    _, steward, lyra = demo
    steward.ok("assign", "--handle", "lyra", "--access", "community-admin")
    lyra.ok("unassign", "--handle", "steward", "--access", "community-admin")
    assert [r["role"] for r in roles(steward)] == []
    refused(steward.run("unassign", "--handle", "lyra", "--access", "community-admin"))
    refused(
        lyra.run("unassign", "--handle", "lyra", "--access", "community-admin"),
        status=409,
    )
    steward_roles = steward.ok("users", "list")["users"]
    assert any(
        u["handle"] == "lyra" and "community-admin" in [r["role"] for r in u["roles"]]
        for u in steward_roles
    )


# ── S8: unassigning gate-keeper stops a watching gate ──────────────────────────────────────
def test_s8_unassigning_gate_keeper_stops_a_watching_gate(demo, people):
    _, steward, lyra = demo
    gwen = member(steward, people, "gwen", "gate-keeper")
    watching = subprocess.Popen(
        [sys.executable, str(SKILL), "gate", "--watch"],
        cwd=gwen.work,
        env={**gwen.env, "SYMPOSIUM_POLL": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = Output(watching.stdout)
    try:
        publish(lyra, "first")
        output.wait_for("ACCEPTED")
        steward.ok("unassign", "--handle", "gwen", "--access", "gate-keeper")
        output.wait_for("nothing is being decided")
        publish(lyra, "second")
        time.sleep(3)  # three more passes, each refused
    finally:
        watching.send_signal(signal.SIGINT)
        watching.wait(MAX_WAIT)
    output.end()
    names = [
        i["name"]
        for i in steward.ok("data", "changes", "--collection", "record")["items"]
    ]
    assert names == ["lyra_note_first_v1"]


# ── S9: root removes a server admin ────────────────────────────────────────────────────────
def test_s9_a_removed_server_admin_is_shut_out_and_its_communities_run_on(
    server, root, demo
):
    ana, steward, lyra = demo
    ana.ok("use-community", "demo")
    issued = ana.ok(
        "gen-api-key", "app", "--non-member", "--access", "community-observer:*"
    )
    key = ana.api_key(issued)
    assert changes(server, key, "record") == 200
    root.ok("users", "remove", "--handle", "ana", "--server")
    out = refused(ana.run("access"), status=401)
    assert "removed" in out["error"], out
    assert changes(server, key, "record") == 401
    assert "ACCEPTED" not in gate(steward)  # the community's gate runs on
    assert accepted(steward, lyra, "after") == "lyra_note_after_v1"


# ── S10: a server of the last published release upgrades, and is handed over ─────────────────
@pytest.fixture
def previous(tmp_path):
    """A server of the last published release, seeded through that release's own API."""
    server = Server(TEST_ENV)
    server.admin_key = OwnerKey()
    try:
        server.start(place_key(tmp_path, ROOT, server.admin_key), image=PREVIOUS)
        seed(server, ROOT)
        yield server
    finally:
        server.remove()


def test_s10_an_upgraded_community_keeps_its_work_and_gets_its_own_admin(
    suite, previous, tmp_path
):
    upgraded = previous.upgrade()
    backups = upgraded.exec("ls", "/apps/data/backups").stdout.split()
    assert len(backups) == 1 and backups[0].endswith(".sql.gz"), backups

    # root moves to the 0.2.0 skill on a new machine: a key of its own, placed and bound
    root = Actor(suite, tmp_path / "root", ROOT)
    config = root.ok(
        "admin-config", "--handle", ROOT, "--data-server-url", upgraded.url
    )
    place_root_key(upgraded, Path(config["public_key_file"]), config["fingerprint"])
    root.ok("use-community", "demo")
    users = {u["handle"]: u for u in root.ok("users", "list")["users"]}
    assert {"lyra", "vega", "rigel", "nova", "gone"} <= set(users)
    assert users["gone"]["removed"]
    assert [r["role"] for r in users["lyra"]["roles"]] == ["community-member"]

    # root hands the community over: lyra becomes its community admin, on a new machine
    root.ok("assign", "--handle", "lyra", "--access", "community-admin")
    rebound = root.ok(
        "rebind-key", "--handle", "lyra", "--out", root.work / "lyra.invite"
    )
    lyra = Actor(suite, tmp_path / "lyra", "lyra")
    lyra.join(Path(rebound["invite_file"]))
    assert {r["role"] for r in roles(lyra)} == {"community-admin", "community-member"}
    assert "0 submission(s) to decide" in gate(lyra)

    # the community admin brings a member back; the work and the sharing are as they were
    rebound = lyra.ok(
        "rebind-key", "--handle", "vega", "--out", lyra.work / "vega.invite"
    )
    vega = Actor(suite, tmp_path / "vega", "vega")
    vega.join(Path(rebound["invite_file"]))
    shared = vega.ok("data", "changes", "--collection", "lab")["items"]
    assert [i["name"] for i in shared] == ["a.csv"]
    files = lyra.ok("data", "changes", "--collection", "files")["items"]
    assert {i["name"] for i in files} == {"b.csv", "gone.csv"}
    owned = lyra.ok("data", "collection", "list")["collections"]
    assert any(c["name"] == "lab" for c in owned)


# ── S11: an application key on some of a member's collections (§8.3, item 1) ───────────────
def test_s11_a_non_member_key_reads_exactly_its_collections(server, demo, people):
    ana, steward, lyra = demo
    community(server, ana, people, "other", "otto")
    files = {}
    for name in ("c1", "c2", "c3"):
        lyra.ok("data", "collection", "create", "--name", name)
        files[name] = put_file(lyra, name, f"{name}.csv")["file_id"]
    issued = lyra.ok(
        "gen-api-key", "app", "--non-member", "--access", "community-observer:c2,c3"
    )
    key = lyra.api_key(issued)

    def content(name):
        return api(
            server, key, "GET", f"/files/{files[name]}/versions/latest"
        ).status_code

    assert changes(server, key, "c2") == 200 and content("c2") == 200
    assert changes(server, key, "c1") == 403 and content("c1") == 403
    assert api(server, key, "GET", "/artifacts").status_code == 403
    assert changes(server, key, "inbox") == 403
    listed = api(server, key, "GET", "/collections").json()["collections"]
    assert sorted(c["name"] for c in listed) == ["c2", "c3"]
    assert changes(server, key, "c2", "other") == 403
    unknown = "/files/00000000-0000-0000-0000-000000000000/versions/latest"
    assert api(server, key, "GET", unknown).status_code == 404
    submitted = api(
        server,
        key,
        "POST",
        "/submissions",
        json=json.loads(note(lyra.work, "lyra", "x").read_text()),
    )
    assert submitted.status_code == 403
    assert upload(server, key, "c2", "new.csv") == 403
    lyra.ok("unassign", "--api-key", issued["id"], "--access", "community-observer:c2")
    assert changes(server, key, "c2") == 403 and changes(server, key, "c3") == 200
    lyra.ok("revoke-api-key", issued["id"])
    assert changes(server, key, "c3") == 401
    refused(
        lyra.run(
            "gen-api-key",
            "app2",
            "--non-member",
            "--access",
            "community-observer:files",
        )
    )


# ── S12: a whole-community key (§8.3, items 2 and 3) ───────────────────────────────────────
def test_s12_whole_community_keys_and_an_upload_key(server, demo):
    _, steward, lyra = demo
    name = accepted(steward, lyra, "seed")
    key = lyra.api_key(
        lyra.ok("gen-api-key", "script", "--access", "community-observer:*")
    )
    assert api(server, key, "GET", "/artifacts").status_code == 200
    assert api(server, key, "GET", f"/artifacts/{name}").status_code == 200
    assert changes(server, key, "inbox") == 403
    submitted = api(
        server,
        key,
        "POST",
        "/submissions",
        json=json.loads(note(lyra.work, "lyra", "x").read_text()),
    )
    assert submitted.status_code == 403
    refused(
        lyra.run(
            "gen-api-key", "app", "--non-member", "--access", "community-observer:*"
        )
    )
    app = steward.api_key(
        steward.ok(
            "gen-api-key", "app", "--non-member", "--access", "community-observer:*"
        )
    )
    assert api(server, app, "GET", f"/artifacts/{name}").status_code == 200

    lyra.ok("data", "collection", "create", "--name", "c1")
    uploader = lyra.api_key(
        lyra.ok("gen-api-key", "uploader", "--access", "community-member:files")
    )

    assert upload(server, uploader, "files", "u.csv") == 201
    assert (
        upload(server, uploader, "c1", "u.csv") == 403
    )  # a key has no owner allowance


# ── S13: root creates two server admins (§8.4, item 1) ─────────────────────────────────────
def test_s13_root_creates_two_server_admins_and_removes_one(server, root, people):
    ana = server_admin(root, people, "ana")
    ben = server_admin(root, people, "ben")
    listed = root.ok("users", "list", "--server")["users"]
    admins = {
        u["handle"] for u in listed if "server-admin" in [r["role"] for r in u["roles"]]
    }
    assert admins == {"ana", "ben"}
    community(server, ana, people, "alpha", "astrid")
    community(server, ben, people, "beta", "bruno")
    refused(
        ben.run(
            "invite",
            "--handle",
            "cy",
            "--access",
            "server-admin",
            "--out",
            ben.work / "cy.invite",
        )
    )
    root.ok("users", "remove", "--handle", "ana", "--server")
    assert "removed" in refused(ana.run("access"), status=401)["error"]
    ben.ok("use-community", "alpha")
    assert ben.ok("data", "changes", "--collection", "record")["items"] == []
    names = {c["name"] for c in ben.ok("data", "communities", "list")["communities"]}
    assert names == {"alpha", "beta"}


# ── S14: a read-only member (§8.4, item 2) ─────────────────────────────────────────────────
def test_s14_a_read_only_member_reads_then_becomes_a_member(demo, people):
    _, steward, lyra = demo
    accepted(steward, lyra, "seed")
    olive = member(steward, people, "olive", "community-observer:*")
    assert grants(olive) == {"read": ["*"]}
    code, out = olive.report("sync")  # setup synced it already
    assert code == 0 and "up to date — 1 artifact(s)" in out, out
    assert (
        olive.home
        / ".symposium"
        / "member"
        / "demo"
        / "olive"
        / "record"
        / "lyra_note_seed_v1.json"
    ).exists()
    for command in ("publish", "validate"):
        code, out = olive.report(command, note(olive.work, "olive", command))
        assert code == 1 and "`publish`" in out, (command, out)
    refused(olive.run("data", "collection", "create", "--name", "mine"))
    steward.ok("assign", "--handle", "olive", "--access", "community-member:*")
    steward.ok("unassign", "--handle", "olive", "--access", "community-observer")
    assert [r["role"] for r in roles(olive)] == ["community-member"]
    assert accepted(steward, olive, "now") == "olive_note_now_v1"


# ── S15: a member changes the collections on its own key (§8.4, item 3) ────────────────────
def test_s15_only_the_issuer_or_a_members_holder_changes_a_key(server, demo, people):
    _, steward, lyra = demo
    lyra.ok("data", "collection", "create", "--name", "c4")
    issued = lyra.ok("gen-api-key", "uploader", "--access", "community-member:files")
    key = lyra.api_key(issued)

    lyra.ok("assign", "--api-key", issued["id"], "--access", "community-member:c4")
    lyra.ok("unassign", "--api-key", issued["id"], "--access", "community-member:files")
    keys = {k["id"]: k for k in lyra.ok("list-api-keys")["keys"]}
    assert keys[issued["id"]]["roles"] == [
        {"role": "community-member", "collections": ["c4"]}
    ]
    assert upload(server, key, "c4", "u.csv") == 201
    assert upload(server, key, "files", "u.csv") == 403

    vega = member(steward, people, "vega")
    refused(
        vega.run(
            "assign", "--api-key", issued["id"], "--access", "community-member:files"
        )
    )
    refused(
        vega.run(
            "unassign", "--api-key", issued["id"], "--access", "community-member:c4"
        )
    )
    refused(vega.run("revoke-api-key", issued["id"]))
    steward.ok(
        "assign", "--api-key", issued["id"], "--access", "community-member:files"
    )
    assert upload(server, key, "files", "v.csv") == 201

    # a key stays within its issuer's grants, whoever changes it
    mia = member(steward, people, "mia", "community-member:")
    mine = mia.ok("gen-api-key", "own", "--access", "community-member:")
    refused(
        mia.run("assign", "--api-key", mine["id"], "--access", "community-member:c4")
    )
    refused(
        steward.run(
            "assign", "--api-key", mine["id"], "--access", "community-member:c4"
        )
    )


# ── S16: an owner shares, then withdraws, read access (§8.4, item 4) ───────────────────────
def test_s16_an_owner_shares_and_withdraws_only_its_own_collections(
    server, demo, people
):
    ana, steward, lyra = demo
    mia = member(steward, people, "mia")
    mia.ok("data", "collection", "create", "--name", "c1")
    lyra.ok("data", "collection", "create", "--name", "c2")
    olive = people("olive")
    joined = olive.join(steward.invite("olive", "community-observer:c1"))
    assert joined["record"] is None and "without a copy" in joined["record_access"]

    def reads(collection):
        code, _ = olive.run("data", "changes", "--collection", collection)
        return code == 0

    assert reads("c1") and not reads("c2")
    lyra.ok("assign", "--handle", "olive", "--access", "community-observer:c2")
    held = [r for r in roles(olive) if r["role"] == "community-observer"]
    assert sorted(held[0]["collections"]) == ["c1", "c2"]
    assert reads("c2")
    lyra.ok("unassign", "--handle", "olive", "--access", "community-observer:c2")
    assert not reads("c2") and reads("c1")
    refused(
        lyra.run("unassign", "--handle", "olive", "--access", "community-observer:c1")
    )
    refused(lyra.run("unassign", "--handle", "olive", "--access", "community-observer"))
    refused(lyra.run("assign", "--handle", "olive", "--access", "community-member:*"))
    otto = community(server, ana, people, "other", "otto")
    refused(
        otto.run(
            "assign",
            "--handle",
            "olive",
            "--community",
            "demo",
            "--access",
            "community-observer:c2",
        )
    )


# ── S17: a community admin removes a member (§8.4, item 5) ─────────────────────────────────
def test_s17_a_removed_member_is_a_tombstone_whose_work_stays(server, demo, people):
    ana, steward, lyra = demo
    name = accepted(steward, lyra, "seed")
    publish(lyra, "pending")
    member_key = lyra.api_key(
        lyra.ok("gen-api-key", "script", "--access", "community-observer:*")
    )
    lyra.ok("data", "collection", "create", "--name", "c2")
    app = lyra.api_key(
        lyra.ok(
            "gen-api-key", "app", "--non-member", "--access", "community-observer:c2"
        )
    )
    olive = member(steward, people, "olive", "community-observer:")
    lyra.ok("assign", "--handle", "olive", "--access", "community-observer:c2")
    gwen = member(steward, people, "gwen", "gate-keeper")
    otto = community(server, ana, people, "other", "otto")
    refused(gwen.run("users", "remove", "--handle", "lyra"))
    refused(otto.run("users", "remove", "--handle", "lyra", "--community", "demo"))

    steward.ok("users", "remove", "--handle", "lyra")
    [gone] = [u for u in steward.ok("users", "list")["users"] if u["handle"] == "lyra"]
    assert gone["removed"]
    assert "removed" in refused(lyra.run("access"), status=401)["error"]
    assert changes(server, member_key, "record") == 401
    assert changes(server, app, "c2") == 401
    assert steward.ok("list-api-keys")["keys"] == []
    assert "'lyra' is not an active member of this community" in gate(steward)

    reader = steward.api_key(
        steward.ok(
            "gen-api-key", "reader", "--non-member", "--access", "community-observer:*"
        )
    )
    assert (
        api(server, reader, "GET", f"/artifacts/{name}").json()["canonical"][
            "artifact"
        ]["published_by"]
        == "@lyra"
    )
    assert api(server, reader, "GET", "/members/lyra").json()["removed"]
    listed = api(server, reader, "GET", "/members/lyra/artifacts").json()["items"]
    assert [a["name"] for a in listed] == [name]
    vega = member(steward, people, "vega")
    citing = note(vega.work, "vega", "cites")
    body = json.loads(citing.read_text())
    body["artifact"]["text"] = f"As @{name} reported, and @lyra said."
    citing.write_text(json.dumps(body))
    code, out = vega.report("validate", citing)
    assert code == 0, out

    code, _ = olive.run("data", "changes", "--collection", "c2")
    assert code == 0
    steward.ok("data", "collection", "set-public", "--collection", "c2", "--public")
    refused(
        steward.run(
            "invite",
            "--handle",
            "lyra",
            "--access",
            "community-member:*",
            "--out",
            steward.work / "lyra.invite",
        ),
        status=409,
    )
    refused(steward.run("users", "remove", "--handle", "steward"), status=409)


# ── S18: a member revokes its own key ──────────────────────────────────────────────────────
def test_s18_a_revoked_key_loses_its_stream_and_every_request(server, demo, people):
    _, steward, lyra = demo
    issued = lyra.ok("gen-api-key", "watcher", "--access", "community-observer:*")
    key = lyra.api_key(issued)
    closed = threading.Event()

    def follow():
        url = f"{server.url}/v1/communities/demo/record/events"
        try:
            with HTTP.stream(
                "GET", url, headers={"Authorization": f"Bearer {key}"}, timeout=None
            ) as r:
                assert r.status_code == 200
                for _ in r.iter_lines():
                    pass
        except httpx.HTTPError:
            pass
        closed.set()

    streaming = threading.Thread(target=follow, daemon=True)
    streaming.start()
    time.sleep(1)
    assert not closed.is_set()
    vega = member(steward, people, "vega")
    refused(vega.run("revoke-api-key", issued["id"]))
    lyra.ok("revoke-api-key", issued["id"])
    assert closed.wait(10), "the stream outlived its key"
    assert changes(server, key, "record") == 401
    assert issued["id"] not in [k["id"] for k in lyra.ok("list-api-keys")["keys"]]
    refused(
        lyra.run(
            "assign", "--api-key", issued["id"], "--access", "community-observer:*"
        ),
        status=404,
    )
    fresh = lyra.api_key(
        lyra.ok("gen-api-key", "again", "--access", "community-observer:*")
    )
    assert changes(server, fresh, "record") == 200
    # an issued key cannot revoke keys
    other = lyra.ok("gen-api-key", "other", "--access", "community-observer:*")
    revoked = api(server, fresh, "DELETE", f"/api-keys/{other['id']}")
    assert revoked.status_code == 403
