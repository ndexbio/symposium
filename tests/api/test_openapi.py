"""The Symposium API's contract (`api/openapi.yaml`) against the rules its design notes
(`api/DESIGN.md`) set: every operation names its grants and its security, every listing that
grows with the record is paged, every read of the record states its position, every error
shares one body, and the notes' tables agree with the contract. The linter checks that the
document is valid OpenAPI; these check that it says what Symposium needs it to say."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
API = REPO / "api"
SERVICE = REPO / "data-server" / "service"
# the tags of the routes that set a community up and decide who has access; the rest read and
# write its data
CONTROL_TAGS = {
    "server",
    "sessions",
    "users",
    "communities",
    "roster",
    "keys",
    "collections",
    "curation",
}
# The grants an operation may name (`symposium_data/access/rbac.py`)
GRANTS = (
    "read",
    "write",
    "manage",
    "publish",
    "gate",
    "members",
    "export",
    "communities",
    "delegate",
)
METHODS = ("get", "post", "put", "patch", "delete")
# the verbs the resource paths never use as a segment: an action is a method on a noun
VERBS = {
    "challenge",
    "token",
    "rebind",
    "import",
    "export",
    "check",
    "resolve",
    "verify",
    "query",
    "find",
    "stat",
    "purge",
    "promote",
    "register",
    "assign",
    "unassign",
}

# The skill's commands (skills/symposium/SKILL.md) that have an API equivalent; DESIGN.md
# must map every one, and map nothing that lacks an endpoint.
SKILL_COMMANDS = [
    "publish",
    "validate",
    "sync",
    "users list",
]


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load((API / "openapi.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def design() -> str:
    return (API / "DESIGN.md").read_text(encoding="utf-8")


def operations(spec):
    for path, item in spec["paths"].items():
        for method in METHODS:
            if method in item:
                yield path, method, item[method]


def deref(spec, node):
    """`node` with every top-level `$ref` followed."""
    while isinstance(node, dict) and "$ref" in node:
        target = spec
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def flatten(spec, schema) -> tuple[dict, set]:
    """A schema's properties and required names, with `allOf` merged in."""
    schema = deref(spec, schema)
    properties, required = (
        dict(schema.get("properties", {})),
        set(schema.get("required", [])),
    )
    for part in schema.get("allOf", []):
        more, needed = flatten(spec, part)
        properties.update(more)
        required |= needed
    return properties, required


def success_json(spec, op):
    """The schema of an operation's 2xx JSON response, or None."""
    for code, response in op["responses"].items():
        if code.startswith("2"):
            content = deref(spec, response).get("content", {})
            if "application/json" in content:
                return content["application/json"]["schema"]
    return None


def params(spec, op):
    return {deref(spec, p)["name"] for p in op.get("parameters", [])}


def grants_line(op) -> str:
    """The `Grants:` line an operation's description states, from `x-grants` and
    `x-anonymous`."""
    named = ", ".join(op["x-grants"]) or "none"
    anonymous = {
        "always": "; anonymous always",
        "public": "; anonymous when the collection is public",
    }.get(op.get("x-anonymous"), "")
    return f"Grants: {named}{anonymous}."


def test_every_operation_names_its_grants(spec):
    for path, method, op in operations(spec):
        grants = op.get("x-grants")
        where = f"{method.upper()} {path}"
        assert isinstance(grants, list), f"{where}: no x-grants"
        assert set(grants) <= set(GRANTS), f"{where}: x-grants is {grants}"
        assert f"\n{grants_line(op)}\n" in "\n" + op["description"], (
            f"{where}: the description states no '{grants_line(op)}'"
        )
        # the credentials, in the words of the data server README's Authentication column
        assert f"\nAuthentication: {authentication(op)}.\n" in op["description"], (
            f"{where}: the description states no 'Authentication: {authentication(op)}.'"
        )


def test_every_operation_states_its_security(spec):
    schemes = set(spec["components"]["securitySchemes"])
    for path, method, op in operations(spec):
        where = f"{method.upper()} {path}"
        security = op.get("security")
        assert security, f"{where}: states no security requirement"
        named = {name for requirement in security for name in requirement}
        assert named <= schemes, f"{where}: security is {security}"
        assert named == {"apiKey"}, f"{where}: takes {named}, not an API key alone"
        anonymous = {} in security
        assert anonymous == ("x-anonymous" in op), (
            f"{where}: `{{}}` and x-anonymous disagree"
        )
        if anonymous:
            assert op["x-anonymous"] in ("always", "public"), (
                f"{where}: x-anonymous is {op['x-anonymous']!r}"
            )
            # an anonymous caller reads, and only reads
            assert set(op["x-grants"]) <= {"read"}, f"{where}: anonymous beyond read"


def test_the_api_takes_api_keys_alone(spec):
    """One credential, an API key, and one sign-in for every user: no route under
    `/admin`."""
    assert list(spec["components"]["securitySchemes"]) == ["apiKey"]
    for path, method, _ in operations(spec):
        assert not path.startswith("/admin"), (
            f"{method.upper()} {path} is an admin path"
        )


def test_changing_access_takes_a_signed_in_user(spec):
    """The operations that change users, roles, invites or keys take a session key: an issued
    key never widens what any key may do."""
    for path, method, op in operations(spec):
        name = op["operationId"]
        changes = any(
            w in name for w in ("Role", "Invite", "User")
        ) and not name.startswith(("list", "get"))
        if changes or op["operationId"] in (
            "createApiKey",
            "revokeApiKey",
            "rotateKey",
        ):
            assert op.get("x-session"), f"{method.upper()} {path} takes an issued key"


def test_no_path_begins_with_a_variable_and_none_names_a_verb(spec):
    """Every resource has its own namespace: no path under `/v1` starts with a variable that
    could overlap a literal beside it, and every segment is a noun (an action is a method)."""
    for path, method, _ in operations(spec):
        segments = path.strip("/").split("/")
        assert not segments[0].startswith("{"), f"{method.upper()} {path}"
        verbs = VERBS & set(segments)
        assert not verbs, f"{method.upper()} {path} names {verbs}"


def test_every_create_answers_201_with_its_location(spec):
    """A request that creates a resource answers 201 and names it in `Location`."""
    for path, method, op in operations(spec):
        created = op["responses"].get("201")
        if created is None:
            continue
        created = deref(spec, created)
        assert "Location" in created.get("headers", {}), (
            f"{method.upper()} {path}: 201 without Location"
        )


def test_preconditions_are_declared_where_required(spec):
    """Creating a file by name takes `If-None-Match: *`; replacing a role's whole value takes
    `If-Match` with its ETag."""
    for path, _method, op in operations(spec):
        names = {deref(spec, p)["name"] for p in op.get("parameters", [])}
        if op["operationId"] == "putFile":
            assert "If-None-Match" in names and "412" in op["responses"], path
        if op["operationId"].startswith("set") and op["operationId"].endswith("Role"):
            assert "If-Match" in names, path
            assert {"412", "428"} <= set(op["responses"]), path


def test_the_api_takes_one_credential_at_one_path(spec):
    """One API at `/v1`, and one credential, an API key: no Ed25519 token, no JWT, no read key.
    (A Member's registered Ed25519 *key* is named, as what a sign-in and a Member's key stand
    on.)"""
    text = (API / "openapi.yaml").read_text(encoding="utf-8")
    assert [server["url"] for server in spec["servers"]] == ["https://{host}/v1"]
    for word in ("/api/v1", "Ed25519 token", "JWT", "adminToken", "sdr_", "read key"):
        assert word not in text, f"the contract mentions {word}"


def test_the_record_is_read_only(spec):
    for path, item in spec["paths"].items():
        if path.startswith(("/{community}/artifacts", "/{community}/members")):
            written = [m for m in METHODS if m in item and m != "get"]
            assert not written, f"{path} writes with {written}"


def test_every_growing_listing_is_paged(spec):
    """A page is `items` with the cursor to the next: `next` (paged by `cursor` and `limit`) or
    `next_since` (paged by `since` and `limit`, as a collection's feed is)."""
    for path, method, op in operations(spec):
        where = f"{method.upper()} {path}"
        schema = success_json(spec, op)
        if schema is None:
            continue
        properties, _ = flatten(spec, schema)
        listing = any(
            deref(spec, p).get("type") == "array" for p in properties.values()
        )
        paged = "items" in properties and bool({"next", "next_since"} & set(properties))
        if paged and "next" in properties:
            assert {"cursor", "limit"} <= params(spec, op), (
                f"{where}: `next` without cursor/limit"
            )
        if paged and "next_since" in properties:
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            taken = params(spec, op) | (
                set(flatten(spec, body["schema"])[0]) if body else set()
            )
            assert {"since", "limit"} <= taken, (
                f"{where}: `next_since` without since/limit"
            )
        if listing and not paged:
            assert op.get("x-bounded"), (
                f"{where}: lists without paging or an x-bounded reason"
            )


def test_every_read_of_the_record_states_its_position(spec):
    for path, method, op in operations(spec):
        if method != "get" or not path.startswith("/{community}"):
            continue
        if not op.get(
            "x-generated"
        ):  # the record's reads, not the files' or the control's
            continue
        if op.get("x-stored"):  # answers the stored bytes themselves, untouched
            continue
        schema = success_json(spec, op)
        if schema is None:
            continue
        properties, required = flatten(spec, schema)
        assert "position" in required, f"GET {path}: response omits `position`"
        assert properties["position"] == {"$ref": "#/components/schemas/Position"}, path


def test_every_stream_resumes_from_a_cursor(spec):
    streams = 0
    for path, _method, op in operations(spec):
        for response in op["responses"].values():
            if "text/event-stream" in deref(spec, response).get("content", {}):
                streams += 1
                assert "Last-Event-ID" in params(spec, op), f"{path}: no Last-Event-ID"
    assert streams >= 2


def test_every_error_shares_one_body(spec):
    """Every refusal answers the Error body. `getStatus` is the one exception: its 503 is the
    health report itself, the same body as its 200."""
    for path, _method, op in operations(spec):
        for code, response in op["responses"].items():
            if op["operationId"] == "getStatus" and code == "503":
                continue
            if code[0] in "45":
                schema = deref(spec, response)["content"]["application/json"]["schema"]
                assert schema == {"$ref": "#/components/schemas/Error"}, (
                    f"{path} {code}"
                )


def test_every_addressable_resource_carries_its_url(spec):
    schemas = spec["components"]["schemas"]
    for name in [n for n in schemas if n.endswith("Resource")] + ["ArtifactSummary"]:
        _, required = flatten(spec, schemas[name])
        assert "url" in required, f"{name} omits `url`"


def table(design, heading):
    """The rows of the first markdown table after `heading`, as lists of cells."""
    lines = design.split(heading, 1)[1].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows[2:]


def grants_cell(op) -> str:
    """An operation's grants as DESIGN.md's endpoint table writes them."""
    if op["x-grants"]:
        return " or ".join(f"`{g}`" for g in op["x-grants"])
    if op.get("x-anonymous") == "always":
        return "no key"
    return "any key; the handler decides"


def test_the_grant_table_matches_the_contract(spec, design):
    contract = {
        op["operationId"]: (
            f"{method.upper()} {path}",
            grants_cell(op),
            "✓" if op.get("x-session") else "",
            op.get("x-anonymous", ""),
        )
        for path, method, op in operations(spec)
    }
    rows = table(design, "### 3.3 Endpoint × grants")
    documented = {operation: tuple(cells) for operation, *cells in rows}
    assert documented == contract


def test_the_design_maps_every_command_to_a_real_endpoint(spec, design):
    routes = {
        op["operationId"]: f"{method.upper()} {path}"
        for path, method, op in operations(spec)
    }
    commands = table(design, "## 2. The skill's commands → endpoints")
    for command in SKILL_COMMANDS:
        assert any(
            re.search(rf"`{re.escape(command)}\b", row[0]) for row in commands
        ), command
    for command, endpoints, named in commands:
        named = re.findall(r"`(\w+)`", named)
        assert named, f"{command} maps to no operation"
        assert set(named) <= set(routes), f"{command} names {named}"
        listed = {e.split("?")[0] for e in re.findall(r"`([A-Z]+ /[^`]+)`", endpoints)}
        assert listed == {routes[n] for n in named}, command


# ── one contract for every route ───────────────────────────────────────────────────────────
def hand_written_routes() -> set:
    """(METHOD, path) of every route `symposium_data/app.py` declares, read from its source:
    the app reads the server's settings as it is imported, so it is not imported here."""
    tree = ast.parse(
        (SERVICE / "symposium_data" / "app.py").read_text(encoding="utf-8")
    )
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in METHODS
                and getattr(decorator.func.value, "id", None) == "app"
            ):
                path = decorator.args[0].value
                assert path.startswith("/v1/"), path
                routes.add((decorator.func.attr.upper(), path.removeprefix("/v1")))
    return routes


def generated_routes() -> set:
    """(METHOD, path) of every route in `symposium_api/generated/routers/`."""
    routes = set()
    for module in (SERVICE / "symposium_api" / "generated" / "routers").glob("*.py"):
        for method, path in re.findall(
            r"@router\.(get|post|put|delete)\(\s*['\"]([^'\"]+)['\"]",
            module.read_text(encoding="utf-8"),
        ):
            routes.add((method.upper(), path))
    return routes


def test_the_contract_describes_every_route_of_the_server(spec):
    """Every route the server answers is in the contract, and every operation in the contract
    is a route: the hand-written ones in `app.py`, and the generated ones it marks."""
    contract = {(method.upper(), path) for path, method, _ in operations(spec)}
    generated = {
        (method.upper(), path)
        for path, method, op in operations(spec)
        if op.get("x-generated")
    }
    assert generated == generated_routes()
    assert contract - generated == hand_written_routes()


def test_every_hand_written_route_takes_the_contracts_rule(spec):
    """Each hand-written route depends on `authorize` for its own operation, so the rule the
    contract states is the rule the route applies."""
    source = (SERVICE / "symposium_data" / "app.py").read_text(encoding="utf-8")
    authorized = set(re.findall(r'Depends\(authorize\("(\w+)"\)\)', source))
    hand_written = {
        op["operationId"] for _, _, op in operations(spec) if not op.get("x-generated")
    }
    assert authorized == hand_written


def test_a_session_is_asked_for_by_control_operations_alone(spec):
    for path, method, op in operations(spec):
        where = f"{method.upper()} {path}"
        tags = set(op["tags"])
        assert tags <= CONTROL_TAGS or not tags & CONTROL_TAGS, where
        if op.get("x-session"):
            assert tags <= CONTROL_TAGS, f"{where}: x-session on a data operation"


# ── the data server README's Authentication column ─────────────────────────────────────────
README = REPO / "data-server" / "README.md"


def authentication(op) -> str:
    """The credentials an operation takes, in the README's words, from its `x-session` and
    `x-anonymous`: a session key proves a signed-in user, and the grants decide the rest."""
    if op.get("x-anonymous") == "always":
        return "no key required"
    named = ["session key"] if op.get("x-session") else ["issued key", "session key"]
    if op.get("x-anonymous") == "public":
        named.append("no key (public)")
    return ", ".join(named)


def shape(path: str) -> str:
    """A path with its parameters unnamed: the README writes `{id}` where the contract has
    `{file_id}`."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def readme_routes(cell: str, known: set) -> list:
    """The (METHOD, path shape) pairs a README route cell names, each one in `known`. A
    route written `…/x` continues the one before it, a bare `…` repeats it, a route without
    a method takes the one before it, and a Data API route, written without `/v1`, is under
    `/{community}`."""
    named, method, previous = [], None, None
    for text in re.findall(r"`([^`]+)`", cell):
        text = re.split(r" \{|\?", text)[0].strip()
        if text.split(" ", 1)[0] in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            method, text = text.split(" ", 1)
        if text.startswith("…"):
            segments = previous.split("/")
            path = next(
                shaped
                for n in range(len(segments), 0, -1)
                if (method, shaped := "/".join(segments[:n]) + shape(text[1:])) in known
            )
        elif text.startswith("/v1"):
            path = shape(text.removeprefix("/v1"))
        else:
            path = shape("/communities/{community}" + text)
        assert (method, path) in known, f"{method} {path}: no such operation ({cell})"
        named.append((method, path))
        previous = path
    return named


def test_the_readme_authentication_column_matches_the_contract(spec):
    """Each row of the data server README's Data API and Control API tables states the
    credentials its routes take, as the contract sets them."""
    contract = {
        (method.upper(), shape(path)): op for path, method, op in operations(spec)
    }
    text = README.read_text(encoding="utf-8")
    section = text.split("### Data API", 1)[1].split("## Server Runtime Configuration")[
        0
    ]
    checked = set()
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        for route in readme_routes(cells[0], set(contract)):
            op = contract[route]
            assert cells[-1] == authentication(op), (
                f"{op['operationId']}: the README says {cells[-1]!r}, "
                f"the contract {authentication(op)!r}"
            )
            checked.add(op["operationId"])
    # every operation but the contract's own two (the README names them in prose) and `getMe`
    missing = {op["operationId"] for op in contract.values()} - checked
    assert missing == {"getOpenApiYaml", "getOpenApiJson", "getMe"}, sorted(missing)
