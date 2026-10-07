"""The Symposium API, live: the data-server container this suite starts, over HTTP.

Every operation in api/openapi.yaml is called and every answer is validated against the
contract's schemas, errors included; every row of the endpoint × role table in api/DESIGN.md
§3.2 is checked for each kind of caller; API keys are taken through their whole life with the
skill's commands; publishing goes through the API and the unchanged gate; and the streams are
read frame by frame. The record the tests build is published through the API and decided by
`tools/gate.py`, exactly as a community's would be.
"""

from __future__ import annotations

import base64
import json
import re
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from openapi_schema_validator import OAS30Validator
from suite import ADMIN, CLI_DIR, REPO, enroll, place_admin_key

API_DIR = REPO / "api"
SPEC = yaml.safe_load((API_DIR / "openapi.yaml").read_text(encoding="utf-8"))
DESIGN = (API_DIR / "DESIGN.md").read_text(encoding="utf-8")
TOOLS = REPO / "tools"
ROLES = ("non-member", "member", "admin")
OPERATIONS = {
    op["operationId"]: (method.upper(), path, op)
    for path, item in SPEC["paths"].items()
    for method, op in item.items()
    if isinstance(op, dict) and "operationId" in op
}


# ── the contract ───────────────────────────────────────────────────────────────────────────
def deref(node: dict) -> dict:
    while "$ref" in node:
        target = SPEC
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def conforms(operation_id: str, response: httpx.Response, body=None):
    """The answer is one the contract lists for this operation, and its body validates."""
    responses = OPERATIONS[operation_id][2]["responses"]
    status = str(response.status_code)
    assert status in responses, (
        f"{operation_id} answered {status}, which the contract does not list: "
        f"{response.text[:300]}"
    )
    declared = deref(responses[status])
    for name, header in declared.get("headers", {}).items():
        value = response.headers.get(name)
        assert value is not None, f"{operation_id} {status} lacks its {name} header"
        allowed = deref(header).get("schema", {}).get("enum")
        assert allowed is None or value in allowed, (operation_id, name, value)
    content = declared.get("content", {})
    media = response.headers.get("content-type", "").split(";")[0]
    if not content:
        return
    assert media in content, (
        f"{operation_id} answered {media}, contract lists {list(content)}"
    )
    if media == "application/json":
        schema = {**content[media]["schema"], "components": SPEC["components"]}
        OAS30Validator(schema).validate(response.json() if body is None else body)


def event_conforms(operation_id: str, frame: dict):
    """One SSE frame validates against the stream's event schema."""
    schema = OPERATIONS[operation_id][2]["responses"]["200"]["content"][
        "text/event-stream"
    ]
    item = {**schema["schema"]["items"], "components": SPEC["components"]}
    OAS30Validator(item).validate(frame)


def role_table() -> dict:
    """DESIGN §3.2 -> {operationId: (allowed key roles, admin token only)}."""
    section = DESIGN.split("### 3.2 Endpoint × role", 1)[1]
    rows = [line for line in section.splitlines() if line.startswith("|")][2:]
    table = {}
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) != 5:
            break
        operation, _route, *marks = cells
        allowed = {r for r, mark in zip(ROLES, marks) if mark.startswith("✓")}
        table[operation] = (allowed, any("token" in mark for mark in marks))
    return table


# ── the community the tests use ────────────────────────────────────────────────────────────
def head(name, kind, publisher, **extra):
    return {
        "name": name,
        "type": kind,
        "specification_version": "1.0",
        "published_by": f"@{publisher}",
        "created": None,
        **extra,
    }


def artifact(header, objects=(), relationships=()):
    return {
        "artifact": header,
        "objects": list(objects),
        "relationships": list(relationships),
    }


NOTE_A = artifact(
    head(
        "lyra_note_a_v1",
        "NonGroundable",
        "lyra",
        groundable=False,
        title="A first note",
        text="A short note for the API tests.",
    )
)
DATA_D = artifact(
    head(
        "lyra_data_d_v1",
        "Data",
        "lyra",
        title="Scores",
        authors=["Example, A."],
        import_method="Typed in by hand for the API tests: two rows, one score column.",
        values="Gene,Score\nBST2,0.06\nLY6E,0.24\n",
    ),
    [
        {
            "name": "csv",
            "type": "Content",
            "groundable": True,
            "description": "The scores, held in the `values` property.",
            "addressing_method": "row=<Gene>&col=<column name>",
            "location": "embedded in the `values` property",
            "access_method": "read the `values` property as CSV",
        }
    ],
)
NOTE_B1 = artifact(
    head(
        "vega_note_b_v1",
        "NonGroundable",
        "vega",
        groundable=False,
        text="Builds on [the first note](@lyra_note_a_v1).",
    )
)
NOTE_B2 = artifact(
    head(
        "vega_note_b_v2",
        "NonGroundable",
        "vega",
        groundable=False,
        text="The corrected note.",
        supersedes=["@vega_note_b_v1"],
        supersedes_rationale="Correction: restates the first version.",
    )
)
MESSAGE_C = artifact(
    head(
        "lyra_msg_c_v1",
        "Message",
        "lyra",
        groundable=False,
        recipients=["@vega"],
        text="Please look at the scores.",
    )
)
ARGUMENT_G = artifact(
    head(
        "vega_arg_g_v1",
        "Argument",
        "vega",
        authors=["vega"],
        primary_assertion="a_primary",
        verdict="Supported for this table.",
        rationale="The score is low.",
        purpose="Testing the API.",
    ),
    [
        {
            "name": "a_primary",
            "type": "Assertion",
            "claim": "BST2 scores low.",
            "scope": "This table only.",
        },
        {
            "name": "g_score",
            "type": "Ground",
            "citation": "@lyra_data_d_v1.values#csv.row=BST2&col=Score",
            "rationale": "The score is 0.06.",
            "criterion": "A score near 1 would refute it.",
        },
    ],
    [{"rel": "grounded_by", "source": "a_primary", "target": "g_score"}],
)
RECORD = [NOTE_A, DATA_D, NOTE_B1, NOTE_B2, MESSAGE_C, ARGUMENT_G]
ADDRESS = "@lyra_data_d_v1.values#csv.row=BST2&col=Score"


def note(handle: str, topic: str) -> dict:
    return artifact(
        head(
            f"{handle}_note_{topic}_v1",
            "NonGroundable",
            handle,
            groundable=False,
            text=f"A note on {topic}.",
        )
    )


def tool(suite, cwd: Path, script: str, *args) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(TOOLS / script), *map(str, args)],
        cwd=cwd,
        env=suite.env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode, result.stdout + result.stderr


def gate(suite, admin_dir: Path) -> str:
    code, out = tool(suite, admin_dir, "gate.py")
    assert code == 0, out
    return out


def admin_token(suite, admin_dir: Path) -> str:
    """The server admin's Ed25519 token, signed in the way the CLI signs in."""
    code = (
        f"import sys; sys.path.insert(0, {str(CLI_DIR)!r}); "
        "from main import Commands; print(Commands().admin().token)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=admin_dir,
        env=suite.env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class Api:
    def __init__(self, server):
        self.base = server.url + "/api/v1"
        self.http = httpx.Client(timeout=30)

    def call(self, method, path, credential=None, body=None, headers=None):
        headers = dict(headers or {})
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        return self.http.request(method, self.base + path, json=body, headers=headers)


def key_value(cli_output: dict) -> str:
    return json.loads(Path(cli_output["key_file"]).read_text())["key"]


@pytest.fixture
def world(suite, server, cli, admin_dir):
    """The `demo` community: members lyra and vega, a key of every role, and the six
    artifacts of RECORD published through the API and accepted by the gate."""
    enroll(cli, admin_dir, "lyra")
    enroll(cli, admin_dir, "vega")
    keys = {
        "lyra": key_value(cli.ok(admin_dir, "gen-api-key", "lyra", "member")),
        "vega": key_value(cli.ok(admin_dir, "gen-api-key", "vega", "member")),
        "non-member": key_value(
            cli.ok(
                admin_dir,
                "gen-api-key",
                "viewer-app",
                "non-member",
                "--label",
                "an app",
            )
        ),
        "admin": key_value(
            cli.ok(admin_dir, "gen-api-key", ADMIN, "admin", "--server")
        ),
    }
    api = Api(server)
    for doc in RECORD:
        publisher = doc["artifact"]["published_by"].lstrip("@")
        response = api.call("POST", "/demo/submissions", keys[publisher], doc)
        assert response.status_code == 201, response.text
        gate(suite, admin_dir)
    return {
        "api": api,
        "keys": keys,
        "token": admin_token(suite, admin_dir),
        "admin_dir": admin_dir,
    }


# ── the published contract ─────────────────────────────────────────────────────────────────
def test_the_contract_is_served_anonymously(server):
    api = Api(server)
    served = api.call("GET", "/openapi.yaml")
    assert served.status_code == 200
    assert served.text == (API_DIR / "openapi.yaml").read_text(encoding="utf-8")
    conforms("getOpenApiYaml", served)
    as_json = api.call("GET", "/openapi.json")
    assert as_json.status_code == 200 and as_json.json() == SPEC
    conforms("getOpenApiJson", as_json)


# ── every operation, live, against the contract ────────────────────────────────────────────
def test_every_operation_answers_as_the_contract_says(world, suite):
    api, keys, token = world["api"], world["keys"], world["token"]
    lyra = keys["lyra"]
    called = set()

    def check(operation_id, method, path, credential=lyra, body=None, status=None):
        response = api.call(method, path, credential, body)
        conforms(operation_id, response)
        if status is not None:
            assert response.status_code == status, response.text
        called.add(operation_id)
        return response

    check("getOpenApiYaml", "GET", "/openapi.yaml", None, status=200)
    check("getOpenApiJson", "GET", "/openapi.json", None, status=200)
    state = check("getRecord", "GET", "/demo/record", status=200).json()
    assert state["counts"]["artifacts"] == len(RECORD)
    status = httpx.get(
        api.base.removesuffix("/api/v1") + "/v1/status", timeout=10
    ).json()
    # one server-wide figure, naming no community: /v1/status answers anyone
    assert status["api_index"] == {"behind": 0}

    # paging: two at a time, every artifact once, in created order
    names, path = [], "/demo/artifacts?limit=2"
    while path:
        page = check("listArtifacts", "GET", path, status=200).json()
        names += [item["name"] for item in page["items"]]
        path = (
            f"/demo/artifacts?limit=2&cursor={page['next']}" if page["next"] else None
        )
    assert names == [doc["artifact"]["name"] for doc in RECORD]
    newest = check(
        "listArtifacts", "GET", "/demo/artifacts?order=-created&type=Argument"
    )
    assert [i["name"] for i in newest.json()["items"]] == ["vega_arg_g_v1"]

    data = "/demo/artifacts/lyra_data_d_v1"
    whole = check("getArtifact", "GET", data, status=200).json()
    assert whole["canonical"]["artifact"]["values"] == DATA_D["artifact"]["values"]
    assert whole["canonical"]["artifact"]["created"]  # stamped by the gate
    prop = check("getArtifactProperty", "GET", f"{data}/properties/values", status=200)
    assert prop.json()["value"] == DATA_D["artifact"]["values"]
    check("listObjects", "GET", f"{data}/objects?type=Content", status=200)
    check("getObject", "GET", f"{data}/objects/csv", status=200)
    check(
        "getObjectProperty",
        "GET",
        f"{data}/objects/csv/properties/groundable",
        status=200,
    )
    check(
        "listRelationships",
        "GET",
        "/demo/artifacts/vega_arg_g_v1/relationships",
        status=200,
    )
    cited = check(
        "listCitedBy", "GET", f"{data}/cited-by?via=ground", status=200
    ).json()
    assert [c["from"] for c in cited["items"]] == ["@vega_arg_g_v1"]
    chain = check(
        "listSupersession",
        "GET",
        "/demo/artifacts/vega_note_b_v1/supersession",
        status=200,
    ).json()
    assert [(e["address"], e["direction"]) for e in chain["items"]] == [
        ("@vega_note_b_v2", "later")
    ]
    for basis in ("accepted", "current"):
        check(
            "listFindings",
            "GET",
            f"/demo/artifacts/vega_arg_g_v1/findings?basis={basis}",
            status=200,
        )
    resolved = check(
        "resolveAddress",
        "GET",
        "/demo/resolve?address=" + urllib.parse.quote(ADDRESS, safe=""),
        status=200,
    ).json()
    assert resolved["kind"] == "property" and resolved["verified"] is True

    members = check("listMembers", "GET", "/demo/members", status=200).json()
    assert {m["handle"] for m in members["items"]} >= {"lyra", "vega"}
    check("getMember", "GET", "/demo/members/lyra", status=200)
    check("listMemberArtifacts", "GET", "/demo/members/lyra/artifacts", status=200)
    messages = check(
        "listMemberMessages", "GET", "/demo/members/vega/messages", status=200
    )
    assert [i["name"] for i in messages.json()["items"]] == ["lyra_msg_c_v1"]
    me = check("getMe", "GET", "/demo/me", status=200).json()
    assert (me["username"], me["role"]) == ("lyra", "member")

    check(
        "checkSubmission",
        "POST",
        "/demo/submissions/check",
        body=note("lyra", "c"),
        status=200,
    )
    made = check(
        "submitArtifact",
        "POST",
        "/demo/submissions",
        body=note("lyra", "d"),
        status=201,
    )
    mine = check(
        "listSubmissions", "GET", "/demo/submissions?status=pending", status=200
    )
    assert [s["name"] for s in mine.json()["items"]] == ["lyra_note_d_v1"]
    check("getSubmission", "GET", f"/demo/submissions/{made.json()['id']}", status=200)

    created = check(
        "createApiKey",
        "POST",
        "/admin/api-keys",
        token,
        {
            "username": "another-app",
            "role": "non-member",
            "scope": {"kind": "community", "community": "demo"},
        },
        status=201,
    ).json()
    check("listApiKeys", "GET", "/admin/api-keys", token, status=200)
    check("getApiKey", "GET", f"/admin/api-keys/{created['id']}", token, status=200)
    check(
        "revokeApiKey", "DELETE", f"/admin/api-keys/{created['id']}", token, status=200
    )

    for operation_id, path in (
        ("streamRecord", "/demo/streams/record"),
        ("streamSubmissions", "/demo/streams/submissions"),
    ):
        with api.http.stream(
            "GET", api.base + path, headers={"Authorization": f"Bearer {lyra}"}
        ) as response:
            conforms(operation_id, response)
            assert response.headers["content-type"].startswith("text/event-stream")
        called.add(operation_id)

    # errors answer the contract's Error body too
    check("getArtifact", "GET", "/demo/artifacts/nothing_here_v1", status=404)
    check("listArtifacts", "GET", "/demo/artifacts?cursor=not-a-cursor", status=400)
    check("getRecord", "GET", "/demo/record", None, status=401)
    check("getRecord", "GET", "/elsewhere/record", status=404)

    assert called == set(OPERATIONS), f"never called: {set(OPERATIONS) - called}"


# ── roles ──────────────────────────────────────────────────────────────────────────────────
def probe(world, operation_id, caller, credential):
    """Call an operation the way the role matrix needs: harmless for whoever may call it."""
    method, path, _ = OPERATIONS[operation_id]
    path = (
        path.replace("{community}", "demo")
        .replace("{name}", "lyra_data_d_v1")
        .replace("{object}", "csv")
        .replace("{property}", "values")
        .replace("{handle}", "lyra")
        .replace("{submission}", str(uuid.uuid4()))
        .replace("{key_id}", str(uuid.uuid4()))
    )
    if operation_id == "getObjectProperty":
        path = path.replace("/properties/values", "/properties/groundable")
    if operation_id == "resolveAddress":
        path += "?address=" + urllib.parse.quote(ADDRESS, safe="")
    body = None
    if operation_id in ("submitArtifact", "checkSubmission"):
        body = note("nobody", "probe")  # refused by validation, never stored
    if operation_id == "createApiKey":
        body = {"username": "nobody", "role": "member", "scope": {"kind": "server"}}
    api = world["api"]
    if operation_id.startswith("stream"):
        headers = {"Authorization": f"Bearer {credential}"} if credential else {}
        with api.http.stream("GET", api.base + path, headers=headers) as response:
            return response.status_code
    return api.call(method, path, credential, body).status_code


def test_every_role_gets_exactly_the_access_the_table_states(world, cli):
    table = role_table()
    assert set(table) == set(OPERATIONS)
    keys, token = world["keys"], world["token"]
    for public in (False, True):
        cli.ok(
            world["admin_dir"],
            "collection",
            "set-public",
            "--collection",
            "record",
            "--public" if public else "--private",
        )
        for operation_id, (allowed, token_only) in table.items():
            rule = OPERATIONS[operation_id][2]
            anonymous = rule.get("x-anonymous")
            callers = {
                "anonymous": (
                    None,
                    anonymous == "always" or (public and bool(anonymous)),
                ),
                "admin token": (token, token_only),
                **{
                    role: (
                        keys["lyra"] if role == "member" else keys[role],
                        role in allowed and not token_only,
                    )
                    for role in ROLES
                },
            }
            for caller, (credential, may) in callers.items():
                status = probe(world, operation_id, caller, credential)
                refused = status in (401, 403)
                assert refused != may, (
                    f"{operation_id} for {caller} (record public: {public}) "
                    f"answered {status}; the table says {'allowed' if may else 'refused'}"
                )


def test_a_member_reads_only_its_own_submissions(world):
    api, keys = world["api"], world["keys"]
    made = api.call("POST", "/demo/submissions", keys["lyra"], note("lyra", "own"))
    assert made.status_code == 201
    theirs = api.call("GET", f"/demo/submissions/{made.json()['id']}", keys["vega"])
    assert theirs.status_code == 403
    conforms("getSubmission", theirs)
    listed = api.call("GET", "/demo/submissions", keys["vega"]).json()["items"]
    assert all(s["submitted_by"] == "vega" for s in listed)
    everyone = api.call("GET", "/demo/submissions", keys["admin"]).json()["items"]
    assert {s["submitted_by"] for s in everyone} >= {"lyra", "vega"}


# ── API keys, end to end ───────────────────────────────────────────────────────────────────
def mode(path) -> int:
    return stat.S_IMODE(Path(path).stat().st_mode)


def sql(server, statement: str, *args) -> list:
    code = (
        "import json, sys, psycopg; from symposium_data.runtime import Settings; "
        "conn = psycopg.connect(Settings().database_url, autocommit=True); "
        "cur = conn.execute(sys.argv[1], sys.argv[2:]); "
        "print(json.dumps(cur.fetchall() if cur.description else [], default=str))"
    )
    result = server.exec("/opt/venv/bin/python", "-c", code, statement, *args)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def follow(api, credential=None, path="/demo/streams/record") -> threading.Event:
    """Read a stream in the background. -> an event set once the server ends it."""
    ended = threading.Event()

    def read():
        headers = {"Authorization": f"Bearer {credential}"} if credential else {}
        with api.http.stream(
            "GET", api.base + path, headers=headers, timeout=60
        ) as response:
            assert response.status_code == 200
            for _ in response.iter_lines():
                pass
        ended.set()

    threading.Thread(target=read, daemon=True).start()
    time.sleep(1)
    return ended


def test_api_keys_work_end_to_end(world, suite, server, cli):
    api, admin_dir = world["api"], world["admin_dir"]
    issued = cli.ok(admin_dir, "gen-api-key", "lyra", "member", "--label", "laptop")
    assert "key" not in issued and mode(issued["key_file"]) == 0o600
    key = key_value(issued)
    assert key.startswith("sak_") and len(key) == 47
    assert api.call("GET", "/demo/me", key).json()["username"] == "lyra"

    listed = cli.ok(admin_dir, "list-api-keys")
    assert mode(listed["keys_file"]) == 0o600
    assert all("key" not in item for item in listed["keys"])
    in_file = json.loads(Path(listed["keys_file"]).read_text())["keys"]
    assert {k["key"] for k in in_file if k["id"] == issued["id"]} == {key}

    # every column of every row holds a key only as its hash and its ciphertext
    rows = sql(server, "SELECT to_jsonb(k)::text FROM api_keys k")
    assert rows and all(key not in row[0] for row in rows)
    # and the ciphertext column, read as the bytes it holds rather than as hex
    sealed = sql(
        server,
        "SELECT encode(ciphertext, 'escape') FROM api_keys WHERE ciphertext IS NOT NULL",
    )
    assert sealed and all(key not in row[0] for row in sealed)

    # a stream closes within the heartbeat of its key's revocation
    ended = follow(api, key)
    revoked = cli.ok(admin_dir, "revoke-api-key", issued["id"])
    assert revoked["revoked"] is not None
    assert api.call("GET", "/demo/me", key).status_code == 401
    assert ended.wait(30), "the stream outlived its key's revocation"

    # an expired key answers 401, and its stream closes
    short = cli.ok(admin_dir, "gen-api-key", "vega", "member", "--expires-days", "1")
    short_key = key_value(short)
    assert api.call("GET", "/demo/me", short_key).status_code == 200
    ended = follow(api, short_key)
    sql(
        server,
        "UPDATE api_keys SET expires = now() - interval '1 second' WHERE id = %s",
        short["id"],
    )
    assert api.call("GET", "/demo/me", short_key).status_code == 401
    assert ended.wait(30), "the stream outlived its key's expiry"

    # a member's key stops when its handle leaves the roster, and so does its stream
    vega = world["keys"]["vega"]
    assert api.call("GET", "/demo/me", vega).status_code == 200
    ended = follow(api, vega)
    cli.ok(admin_dir, "roster", "remove", "--handle", "vega")
    assert api.call("GET", "/demo/me", vega).status_code == 401
    assert ended.wait(30), "the stream outlived its member's roster entry"

    # an admin rebind stops every admin API key
    admin_key = world["keys"]["admin"]
    assert api.call("GET", "/demo/record", admin_key).status_code == 200
    new = cli.ok(
        admin_dir,
        "admin-config",
        "--handle",
        ADMIN,
        "--data-server-url",
        server.url,
        "--new-key",
    )
    place_admin_key(server, Path(new["public_key_file"]), new["fingerprint"])
    assert api.call("GET", "/demo/record", admin_key).status_code == 401
    rows = sql(
        server,
        "SELECT revoked_by, ciphertext IS NULL FROM api_keys WHERE role = 'admin'",
    )
    assert rows and all(r == ["admin-rebind", True] for r in rows)


# ── publishing through the gate ────────────────────────────────────────────────────────────
def test_publishing_matches_validate_and_the_gate(world, suite, cli, tmp_path):
    api, keys, admin_dir = world["api"], world["keys"], world["admin_dir"]
    lyra = keys["lyra"]

    # refused by the API exactly where `/symposium validate` refuses
    bad = note("lyra", "bad")
    bad["artifact"]["supersedes"] = ["@nothing_here_v1"]
    refused = api.call("POST", "/demo/submissions", lyra, bad)
    assert refused.status_code == 422
    conforms("submitArtifact", refused)
    assert refused.json()["code"] == "validation_failed"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    member_dir = admin_dir / "lyra"
    code, out = tool(suite, member_dir, "publish.py", "--check", path)
    assert code != 0 and "FAIL" in out
    checked = api.call("POST", "/demo/submissions/check", lyra, bad).json()
    assert checked["ok"] is False
    assert {f["check"] for f in checked["findings"] if f["level"] == "FAIL"} == {
        f["check"] for f in refused.json()["findings"] if f["level"] == "FAIL"
    }
    wrong = note("vega", "spoof")  # published_by another Member
    assert api.call("POST", "/demo/submissions", lyra, wrong).status_code == 422
    taken = api.call("POST", "/demo/submissions", lyra, NOTE_A)
    assert taken.status_code == 409

    # accepted by the unchanged gate, and reported so
    made = api.call("POST", "/demo/submissions", lyra, note("lyra", "good")).json()
    assert made["status"] == "pending"
    gate(suite, admin_dir)
    decided = api.call("GET", f"/demo/submissions/{made['id']}", lyra).json()
    assert decided["status"] == "accepted" and decided["artifact_url"].endswith(
        "/demo/artifacts/lyra_note_good_v1"
    )

    # rejected by the gate: a submission written straight into inbox, around the API
    stray = note("lyra", "stray")
    stray["artifact"]["supersedes"] = ["@nothing_here_v1"]
    stray_path = tmp_path / "stray.json"
    stray_path.write_text(json.dumps(stray))
    when = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())
    cli.ok(
        member_dir,
        "put",
        stray_path,
        "--collection",
        "inbox",
        "--name",
        f"lyra_note_stray_v1@{when}",
        "--metadata",
        json.dumps({"symposium_submission": True}),
        "--content-type",
        "application/json",
    )
    gate(suite, admin_dir)
    rejected = [
        s
        for s in api.call("GET", "/demo/submissions?status=rejected", lyra).json()[
            "items"
        ]
        if s["name"] == "lyra_note_stray_v1"
    ]
    assert len(rejected) == 1
    assert rejected[0]["reply"]["failures"] and rejected[0]["reply"]["text"].startswith(
        "REJECTED"
    )

    # skipped: an inbox name that is not the artifact's own
    cli.ok(
        member_dir,
        "put",
        stray_path,
        "--collection",
        "inbox",
        "--name",
        f"lyra_note_other_v1@{when}",
        "--metadata",
        json.dumps({"symposium_submission": True}),
        "--content-type",
        "application/json",
    )
    skipped = api.call("GET", "/demo/submissions?status=skipped", lyra).json()["items"]
    assert [s["name"] for s in skipped] == ["lyra_note_other_v1"]


# ── streams ────────────────────────────────────────────────────────────────────────────────
def frames(response, until, seconds: float = 60) -> list[dict]:
    """SSE frames as {id, event, data}, read until `until(frames)` holds."""
    out, current, deadline = [], {}, time.time() + seconds
    for line in response.iter_lines():
        if line == "" and current:
            out.append(current)
            current = {}
            if until(out):
                return out
        elif ":" in line:
            field, _, value = line.partition(":")
            value = value.lstrip(" ")
            current[field] = json.loads(value) if field == "data" else value
        assert time.time() < deadline, f"{len(out)} frames in {seconds}s: {out[-3:]}"
    return out


def seen(*events):
    return lambda out: set(events) <= {f["event"] for f in out}


def test_streams_deliver_resume_and_cap(world, suite, cli):
    api, keys, admin_dir = world["api"], world["keys"], world["admin_dir"]
    lyra = keys["lyra"]
    auth = {"Authorization": f"Bearer {lyra}"}
    url = api.base + "/demo/streams/record"

    def publish(topic):
        response = api.call("POST", "/demo/submissions", lyra, note("lyra", topic))
        assert response.status_code == 201
        gate(suite, admin_dir)

    with api.http.stream("GET", url, headers=auth, timeout=60) as response:
        threading.Timer(0.5, publish, ("one",)).start()
        artifact_frames = [
            f for f in frames(response, seen("artifact")) if f["event"] == "artifact"
        ]
    assert artifact_frames and artifact_frames[0]["data"]["name"] == "lyra_note_one_v1"
    event_conforms("streamRecord", artifact_frames[0])
    resume_from = artifact_frames[0]["id"]

    publish("two")
    with api.http.stream(
        "GET", url, headers={**auth, "Last-Event-ID": resume_from}, timeout=60
    ) as response:
        first = frames(response, seen("artifact"))[-1]
    assert first["event"] == "artifact" and first["data"]["name"] == "lyra_note_two_v1"

    # submissions: received, then accepted, for the submitter
    with api.http.stream(
        "GET", api.base + "/demo/streams/submissions", headers=auth, timeout=60
    ) as response:
        threading.Timer(0.5, publish, ("three",)).start()
        events = [
            f
            for f in frames(
                response, seen("submission.received", "submission.accepted")
            )
            if f["event"] != "heartbeat"
        ]
    assert [e["event"] for e in events[:2]] == [
        "submission.received",
        "submission.accepted",
    ]
    for event in events:
        event_conforms("streamSubmissions", event)

    # caps: 8 streams per key, then 429 (vega's key holds none yet)
    auth = {"Authorization": f"Bearer {keys['vega']}"}
    opened = []
    try:
        for _ in range(8):
            stream = api.http.stream("GET", url, headers=auth, timeout=60)
            response = stream.__enter__()
            assert response.status_code == 200
            opened.append(stream)
        with api.http.stream("GET", url, headers=auth) as ninth:
            assert ninth.status_code == 429
            ninth.read()
            conforms("streamRecord", ninth)
    finally:
        for stream in opened:
            stream.__exit__(None, None, None)

    # anonymous streams on a public record: 4 per address, then 429
    cli.ok(admin_dir, "collection", "set-public", "--collection", "record", "--public")
    time.sleep(0.5)
    opened = []
    try:
        for _ in range(4):
            stream = api.http.stream("GET", url, timeout=60)
            assert stream.__enter__().status_code == 200
            opened.append(stream)
        with api.http.stream("GET", url) as fifth:
            assert fifth.status_code == 429
    finally:
        for stream in opened:
            stream.__exit__(None, None, None)


def test_the_v1_api_is_unchanged_beside_it(server, admin_dir, cli):
    """The data server's own routes and bodies are untouched by the API mounted beside them."""
    status = httpx.get(server.url + "/v1/status", timeout=10).json()
    assert status["mode"] == "operational"
    missing = httpx.get(
        server.url + "/v1/demo/collections/record/find?name=x", timeout=10
    )
    assert missing.status_code in (401, 404) and set(missing.json()) == {"detail"}
    assert re.match(r"^\d", status["api"])


# ── what the review asked to see covered ───────────────────────────────────────────────────
CAPS = """
import json, uuid
from symposium_api.errors import ApiError
from symposium_api.streams import Caps
from symposium_data.runtime import Database, Settings
db = Database(Settings())
db.open()
caps = Caps(db, total=8, per_key=2, per_anonymous_address=2, anonymous_total=3,
            admin_reserved=2)
a, b, c, d, e, f = (uuid.uuid4() for _ in range(6))
steps = [
    (a, "member", "x"), (a, "member", "x"), (a, "member", "x"),
    (None, None, "10.0.0.1"), (None, None, "10.0.0.1"), (None, None, "10.0.0.1"),
    (None, None, "10.0.0.2"), (None, None, "10.0.0.3"),
    (b, "member", "x"), (e, "member", "x"),
    (c, "admin", "x"), (d, "admin", "x"), (f, "admin", "x"),
]
out = []
for key, role, address in steps:
    try:
        caps.open(key, role, address)
        out.append(200)
    except ApiError as e:
        out.append(e.status)
with db.connection() as conn:
    conn.execute("DELETE FROM api_streams")
print(json.dumps(out))
"""


def test_every_stream_cap_reaches_its_429(server):
    """The caps against the container's own database, with limits small enough to reach:
    2 per key, 2 per anonymous address, 3 anonymous in all, 8 in total with 2 kept for
    admin keys. Every open stream counts toward the total, anonymous ones included."""
    result = server.exec("/opt/venv/bin/python", "-c", CAPS)
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [
        200,
        200,
        429,  # the third stream on one key
        200,
        200,
        429,  # the third anonymous stream from one address
        200,
        429,  # the fourth anonymous stream in all
        200,
        429,  # members fill the total less the admin reserve: 6
        200,
        200,
        429,  # admin keys take the reserve, then the total is full
    ]


def test_a_key_acts_only_within_its_scope_and_standing(world, cli):
    api, keys, token = world["api"], world["keys"], world["token"]
    admin_dir = world["admin_dir"]
    cli.ok(admin_dir, "communities", "create", "--name", "other")

    # a community key is refused elsewhere; a server-scoped admin key is welcome everywhere
    elsewhere = api.call("GET", "/other/record", keys["lyra"])
    assert elsewhere.status_code == 403 and "scoped" in elsewhere.json()["detail"]
    conforms("getRecord", elsewhere)
    assert api.call("GET", "/other/record", keys["admin"]).status_code == 200

    # a non-member key whose label later names a member stops
    made = api.call(
        "POST",
        "/admin/api-keys",
        token,
        {
            "username": "newcomer",
            "role": "non-member",
            "scope": {"kind": "community", "community": "demo"},
        },
    )
    assert made.status_code == 201
    label = made.json()["key"]
    assert api.call("GET", "/demo/record", label).status_code == 200
    cli.ok(admin_dir, "roster", "add", "--handle", "newcomer")
    assert api.call("GET", "/demo/record", label).status_code == 401

    # every refusal createApiKey makes
    cli.ok(
        admin_dir, "roster", "add", "--handle", "ghost"
    )  # on the roster, never registered
    for body in (
        {"username": "lyra", "role": "member", "scope": {"kind": "server"}},
        {"username": "lyra", "role": "member", "scope": {"kind": "community"}},
        {"username": "lyra", "role": "admin", "scope": {"kind": "server"}},
        {
            "username": "ghost",
            "role": "member",
            "scope": {"kind": "community", "community": "demo"},
        },
        {
            "username": "lyra",
            "role": "non-member",
            "scope": {"kind": "community", "community": "demo"},
        },
    ):
        refused = api.call("POST", "/admin/api-keys", token, body)
        assert refused.status_code == 422, (body, refused.text)
        conforms("createApiKey", refused)


def forged(**fields) -> str:
    """A cursor in the server's own encoding, carrying whatever fields it is given."""
    raw = json.dumps(fields, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_a_forged_cursor_answers_400(world):
    api, lyra, token = world["api"], world["keys"]["lyra"], world["token"]
    shapes = (
        "not-a-cursor",
        forged(o="7"),
        forged(o=-1),
        forged(o=1.5),
        forged(o=1, extra=1),
        base64.urlsafe_b64encode(b"[1,2]").decode().rstrip("="),
    )
    paged = (
        ("listArtifacts", "/demo/artifacts", lyra),
        ("listObjects", "/demo/artifacts/lyra_data_d_v1/objects", lyra),
        ("listCitedBy", "/demo/artifacts/lyra_data_d_v1/cited-by", lyra),
        ("listMembers", "/demo/members", lyra),
        ("listSubmissions", "/demo/submissions", lyra),
    )
    for operation_id, path, credential in paged:
        for cursor in shapes:
            refused = api.call("GET", f"{path}?cursor={cursor}", credential)
            assert refused.status_code == 400, (operation_id, cursor, refused.text)
            conforms(operation_id, refused)

    for cursor in (
        forged(c="yesterday", k=str(uuid.uuid4())),
        forged(c="2026-01-01T00:00:00+00:00", k="not-a-uuid"),
        forged(c=5, k=str(uuid.uuid4())),
    ):
        refused = api.call("GET", f"/admin/api-keys?cursor={cursor}", token)
        assert refused.status_code == 400, (cursor, refused.text)
        conforms("listApiKeys", refused)

    for operation_id, path in (
        ("streamRecord", "/demo/streams/record"),
        ("streamSubmissions", "/demo/streams/submissions"),
    ):
        refused = api.call(
            "GET", path, lyra, headers={"Last-Event-ID": forged(r="seven")}
        )
        assert refused.status_code == 400, (operation_id, refused.text)
        conforms(operation_id, refused)


def test_a_purged_artifact_leaves_every_read(world, cli):
    api, lyra, admin_dir = world["api"], world["keys"]["lyra"], world["admin_dir"]
    data = "/demo/artifacts/lyra_data_d_v1"
    content = api.call("GET", data, lyra).json()["links"]["content"]
    file_id = content.split("/files/")[1].split("/")[0]
    cli.ok(admin_dir, "purge", "--cite", f"symposium-data:{file_id}@v1")
    gone = api.call("GET", data, lyra)
    assert gone.status_code == 404
    conforms("getArtifact", gone)
    assert api.call("GET", f"{data}/properties/values", lyra).status_code == 404
    names = [
        i["name"] for i in api.call("GET", "/demo/artifacts", lyra).json()["items"]
    ]
    assert "lyra_data_d_v1" not in names
    resolved = api.call(
        "GET", "/demo/resolve?address=" + urllib.parse.quote(ADDRESS, safe=""), lyra
    )
    assert resolved.status_code == 404
    assert api.call("GET", "/demo/record", lyra).json()["counts"]["artifacts"] == 5


def test_an_anonymous_stream_ends_when_the_record_turns_private(world, cli):
    admin_dir = world["admin_dir"]
    cli.ok(admin_dir, "collection", "set-public", "--collection", "record", "--public")
    ended = follow(world["api"])
    cli.ok(admin_dir, "collection", "set-public", "--collection", "record", "--private")
    assert ended.wait(30), "the anonymous stream outlived its record turning private"


def refused_checks(output: str) -> set:
    """The FAIL checks `publish.py --check` printed, named as the API names them."""
    checks = set(re.findall(r"\[FAIL\s+(\w+)\s*\]", output))
    if "name must be prefixed" in output:
        checks.add("NAMING")
    if "embedded payload is" in output:
        checks.add("SIZE")
    return checks


def test_the_api_refuses_what_validate_refuses(world, suite, tmp_path):
    """A table of bad Artifacts through both: each is refused by both, for the same checks.
    The API judges the JSON as sent, so a string where a boolean belongs is refused there
    as `/symposium validate` refuses it."""
    api, lyra = world["api"], world["keys"]["lyra"]
    member_dir = world["admin_dir"] / "lyra"
    unresolved = note("lyra", "unresolved")
    unresolved["artifact"]["supersedes"] = ["@nothing_here_v1"]
    unresolved["artifact"]["supersedes_rationale"] = "Replaces something that is gone."
    loose = json.loads(json.dumps(DATA_D))
    loose["artifact"]["name"] = "lyra_data_loose_v1"
    loose["objects"][0]["groundable"] = "true"
    incomplete = json.loads(json.dumps(ARGUMENT_G))
    incomplete["artifact"].update(name="lyra_arg_incomplete_v1", published_by="@lyra")
    del incomplete["artifact"]["verdict"]
    unprefixed = note("lyra", "x")
    unprefixed["artifact"]["name"] = "note_without_a_prefix_v1"
    oversized = note("lyra", "oversized")
    oversized["artifact"]["text"] = "x" * (260 * 1024)
    for doc in (unresolved, loose, incomplete, unprefixed, oversized):
        path = tmp_path / f"{doc['artifact']['name']}.json"
        path.write_text(json.dumps(doc))
        code, out = tool(suite, member_dir, "publish.py", "--check", path)
        assert code != 0, out
        refused = api.call("POST", "/demo/submissions", lyra, doc)
        assert refused.status_code == 422, refused.text
        api_checks = {
            f["check"] for f in refused.json()["findings"] if f["level"] == "FAIL"
        }
        assert api_checks == refused_checks(out), (doc["artifact"]["name"], out)

    # a set `created`: `publish` replaces it with its own provisional stamp, while the API takes
    # the JSON as sent and refuses it, since the gate alone stamps `created`
    stamped = note("lyra", "stamped")
    stamped["artifact"]["created"] = "2026-01-01T00:00:00+00:00"
    path = tmp_path / "stamped.json"
    path.write_text(json.dumps(stamped))
    code, out = tool(suite, member_dir, "publish.py", "--check", path)
    assert code == 0, out
    refused = api.call("POST", "/demo/submissions", lyra, stamped)
    assert refused.status_code == 422, refused.text
    assert {f["check"] for f in refused.json()["findings"] if f["level"] == "FAIL"} == {
        "STRUCT"
    }

    # a clean note passes both
    clean = note("lyra", "clean")
    path = tmp_path / "clean.json"
    path.write_text(json.dumps(clean))
    code, out = tool(suite, member_dir, "publish.py", "--check", path)
    assert code == 0, out
    checked = api.call("POST", "/demo/submissions/check", lyra, clean)
    assert checked.status_code == 200 and checked.json()["ok"] is True, checked.text
    conforms("checkSubmission", checked)
