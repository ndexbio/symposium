"""The Symposium Data API's contract (`api/openapi.yaml`) against the rules its design notes
(`api/DESIGN.md`) set: every operation names its roles and its security, every listing that
grows with the record is paged, every read of the record states its position, every error
shares one body, and the notes' tables agree with the contract. The linter checks that the
document is valid OpenAPI; these check that it says what Symposium needs it to say."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

API = Path(__file__).resolve().parents[2] / "api"
# The two roles an API key may hold; `member` holds everything `non-member` holds.
ROLES = ("non-member", "member")
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


def test_each_role_holds_everything_the_one_before_holds(spec):
    for path, method, op in operations(spec):
        allowed = [role in op["x-roles"] for role in ROLES]
        first = allowed.index(True)
        assert all(allowed[first:]), f"{method.upper()} {path}: x-roles skips a role"


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
            assert "non-member" in op["x-roles"], (
                f"{where}: anonymous where a non-member is refused"
            )


def test_the_api_takes_api_keys_alone_and_has_no_admin_operation(spec):
    assert list(spec["components"]["securitySchemes"]) == ["apiKey"]
    for path, method, op in operations(spec):
        assert not path.startswith("/admin"), (
            f"{method.upper()} {path} is an admin path"
        )
        assert "admin" not in op["x-roles"], f"{method.upper()} {path} admits admin"


def test_the_api_refers_to_nothing_outside_itself():
    """Every URL the API answers is its own: the contract names no `/v1` route, no Ed25519
    token and no read key, so a client holding an API key never needs another credential."""
    text = (API / "openapi.yaml").read_text(encoding="utf-8")
    assert not re.search(r"(?<!/api)/v1\b", text), "the contract names a /v1 route"
    for word in ("Ed25519", "adminToken", "sdr_"):
        assert word not in text, f"the contract mentions {word}"


def test_the_record_is_read_only(spec):
    for path, item in spec["paths"].items():
        if path.startswith(("/{community}/artifacts", "/{community}/members")):
            written = [m for m in METHODS if m in item and m != "get"]
            assert not written, f"{path} writes with {written}"


def test_every_growing_listing_is_paged(spec):
    for path, method, op in operations(spec):
        where = f"{method.upper()} {path}"
        schema = success_json(spec, op)
        if schema is None:
            continue
        properties, _ = flatten(spec, schema)
        listing = any(
            deref(spec, p).get("type") == "array" for p in properties.values()
        )
        paged = "next" in properties
        if paged:
            assert {"cursor", "limit"} <= params(spec, op), (
                f"{where}: `next` without cursor/limit"
            )
        if listing and not paged:
            assert op.get("x-bounded"), (
                f"{where}: lists without paging or an x-bounded reason"
            )


def test_every_read_of_the_record_states_its_position(spec):
    for path, method, op in operations(spec):
        if method != "get" or not path.startswith("/{community}"):
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
    for path, _method, op in operations(spec):
        for code, response in op["responses"].items():
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
