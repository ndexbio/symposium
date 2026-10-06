"""The Symposium API's contract (`api/openapi.yaml`) against the rules its design notes
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
ROLES = {"reader", "member", "admin"}
METHODS = ("get", "post", "put", "patch", "delete")

# Each view of the record browser (tools/browse.py) and each command of the skill
# (skills/symposium/SKILL.md), as issue #23 names them; DESIGN.md must map every one.
BROWSER_VIEWS = [
    "Overview graph",
    "Artifact page",
    "Argument claim graph",
    "Reading page and evidence table",
    "Readings: CSV tables",
    "Grounded text spans",
    "Validator findings per Artifact",
    "Member colours and counts",
]
SKILL_COMMANDS = [
    "setup",
    "bootstrap",
    "use",
    "publish",
    "validate",
    "sync",
    "gate",
    "serve",
    "admin-config",
    "roster list",
    "roster add",
    "invite",
    "rebind-key",
    "suspect-after",
    "purge",
    "export",
    "port",
    "data",
    "gen-api-key",
    "list-api-keys",
    "revoke-api-key",
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
        assert roles and set(roles) <= ROLES, f"{where}: x-roles is {roles}"
        stated = re.search(r"^Roles: (.+)$", op["description"], re.M)
        assert stated, f"{where}: the description states no 'Roles:' line"
        named = set(re.findall(r"\b(reader|member|admin)\b", stated.group(1)))
        assert named == set(roles), (
            f"{where}: description names {named}, x-roles {roles}"
        )


def test_every_operation_states_its_security(spec):
    schemes = set(spec["components"]["securitySchemes"])
    for path, method, op in operations(spec):
        where = f"{method.upper()} {path}"
        security = op.get("security")
        assert security, f"{where}: states no security requirement"
        named = {name for requirement in security for name in requirement}
        assert "apiKey" in named and named <= schemes, (
            f"{where}: security is {security}"
        )
        anonymous = {} in security
        assert anonymous == ("x-anonymous" in op), (
            f"{where}: `{{}}` and x-anonymous disagree"
        )
        if anonymous:
            assert "reader" in op["x-roles"], (
                f"{where}: anonymous on a non-reader operation"
            )


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
        if method != "get" or path.startswith("/admin/"):
            continue
        schema = success_json(spec, op)
        if schema is None:
            continue
        _, required = flatten(spec, schema)
        assert "position" in required, f"GET {path}: response omits `position`"


def test_every_stream_resumes_from_a_cursor(spec):
    streams = 0
    for path, _method, op in operations(spec):
        for response in op["responses"].values():
            if "text/event-stream" in deref(spec, response).get("content", {}):
                streams += 1
                assert "Last-Event-ID" in params(spec, op), f"{path}: no Last-Event-ID"
    assert streams >= 3


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
    for name in [n for n in schemas if n.endswith("Resource")] + [
        "ArtifactSummary",
        "ApiKey",
    ]:
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
    rows = table(design, "### 4.2 Endpoint × role")
    documented = {}
    for operation, route, reader, member, admin in rows:
        roles = {
            r
            for r, cell in zip(("reader", "member", "admin"), (reader, member, admin))
            if cell.startswith("✓")
        }
        documented[operation] = (route, roles)
    assert set(documented) == set(contract)
    for operation, (method, path, roles) in contract.items():
        route, listed = documented[operation]
        assert route == f"{method} {path}", operation
        assert listed == roles, operation


def test_the_design_maps_every_view_and_command(spec, design):
    operation_ids = {op["operationId"] for _, _, op in operations(spec)}
    views = table(design, "## 2. The record browser's views → endpoints")
    for view in BROWSER_VIEWS:
        assert any(row[0].startswith(view) for row in views), f"unmapped view: {view}"
    commands = table(design, "## 3. The skill's commands → endpoints")
    for command in SKILL_COMMANDS:
        assert any(
            re.search(rf"`{re.escape(command)}\b", row[0]) for row in commands
        ), command
    for row in views + commands:
        for named in re.findall(r"`?\b([a-z]+[A-Z][A-Za-z]+)\b", row[2]):
            assert named in operation_ids, (
                f"the notes name {named}, which the contract lacks"
            )
