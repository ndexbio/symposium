"""The Symposium API's contract (`api/openapi.yaml`) against the rules its design notes
(`api/DESIGN.md`) set: every operation names its roles and its security, every listing that
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
# the tags of the routes that set a community up; the rest read and write its data
CONTROL_TAGS = {
    "server",
    "sign-in",
    "communities",
    "roster",
    "keys",
    "collections",
    "admin",
}
# The roles an API key may hold: `member` holds everything `non-member` holds; `admin` is the
# server admin's session, which acts as no Member.
ROLES = ("non-member", "member", "admin")
METHODS = ("get", "post", "put", "patch", "delete")

# The skill's commands (skills/symposium/SKILL.md) that have an API equivalent; DESIGN.md
# must map every one, and map nothing that lacks an endpoint.
SKILL_COMMANDS = [
    "publish",
    "validate",
    "sync",
    "roster list",
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


def test_every_operation_names_its_roles(spec):
    for path, method, op in operations(spec):
        roles = op.get("x-roles")
        where = f"{method.upper()} {path}"
        assert roles and set(roles) <= set(ROLES), f"{where}: x-roles is {roles}"
        stated = re.search(r"^Roles: (.+)$", op["description"], re.M)
        assert stated, f"{where}: the description states no 'Roles:' line"
        named = set(
            re.findall(r"(?<![\w-])(non-member|member|admin)\b", stated.group(1))
        )
        assert named == set(roles), (
            f"{where}: description names {named}, x-roles {roles}"
        )


def test_a_member_holds_everything_a_non_member_holds(spec):
    for path, method, op in operations(spec):
        if "non-member" in op["x-roles"]:
            assert "member" in op["x-roles"], f"{method.upper()} {path}: skips member"


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
            assert "non-member" in op["x-roles"], (
                f"{where}: anonymous where a non-member is refused"
            )


def test_the_api_takes_api_keys_alone(spec):
    """One credential, an API key. The admin's sign-in pair is the one route under `/admin`:
    every other admin operation lives under its community, or under `/communities`."""
    assert list(spec["components"]["securitySchemes"]) == ["apiKey"]
    for path, method, op in operations(spec):
        assert not path.startswith("/admin") or path in (
            "/admin/challenge",
            "/admin/token",
        ), f"{method.upper()} {path} is an admin path"
        if op["x-roles"] == ["member"]:
            continue  # acts as a Member, which the admin is not
        assert "admin" in op["x-roles"], f"{method.upper()} {path} refuses the admin"


def test_every_member_operation_says_whose_key_it_needs(spec):
    """An operation that acts as a Member says it needs a key the Member made for itself, and
    that the key's handle is checked against the community in the path on every request."""
    for path, method, op in operations(spec):
        if op["x-roles"] != ["member"]:
            continue
        text = " ".join(op["description"].split())
        where = f"{method.upper()} {path}"
        assert "Requires a key that acts as a Member" in text, where
        assert "created for itself" in text, where
        assert "session key" in text, where
        assert "the community in the path" in text, where


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


def test_the_role_table_matches_the_contract(spec, design):
    contract = {
        op["operationId"]: (method.upper(), path, set(op["x-roles"]))
        for path, method, op in operations(spec)
    }
    rows = table(design, "### 3.2 Endpoint × role")
    documented = {}
    for operation, route, *cells in rows:
        roles = {r for r, cell in zip(ROLES, cells) if cell.startswith("✓")}
        documented[operation] = (route, roles)
    assert set(documented) == set(contract)
    for operation, (method, path, roles) in contract.items():
        route, listed = documented[operation]
        assert route == f"{method} {path}", operation
        assert listed == roles, operation


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
