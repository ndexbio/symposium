"""The API's operations: the hand-written implementation of the generated `Service` interface.

Every argument and return value is a generated model, so nothing here redeclares the contract.
Reads answer from the derived index (`index.Index`), folded up to the record before each read;
publishing writes a submission into `inbox` exactly as `tools/publish.py` does; the gate stays
`/symposium gate`, and the API reports what it decided.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import Enum
from urllib.parse import quote

from fastapi.responses import Response
from pydantic import RootModel
from symposium_rules.checks import naming_refusal, payload_refusal, skip_reason
from symposium_rules.validate import (
    NON_GROUNDABLE_TYPES,
    passed,
    resolve,
    validate,
    verify_content,
)

from .authz import standing
from .caller import Caller
from .errors import ApiError
from .generated import models as m
from .generated.service import Service
from .index import Index, members_of
from .streams import HEARTBEAT, Caps, Notifier

API = "/api/v1"
MARK_SUBMISSION = "symposium_submission"
MARK_REPLY = "symposium_reply"
MARK_CITATION = "symposium_submission_citation"


# ── values ─────────────────────────────────────────────────────────────────────────────────
def plain(value):
    """A generated argument as a plain value: a RootModel's root, an enum's value."""
    if isinstance(value, RootModel):
        return plain(value.root)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def iso(value) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def now() -> str:
    return iso(datetime.now(UTC))


def encode(**fields) -> str:
    raw = json.dumps(fields, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor, **fields) -> dict:
    """A cursor this server issued, holding at most `fields`, each of its declared type
    (int fields are non-negative). Anything else answers 400."""
    cursor = plain(cursor)
    if cursor is None:
        return {}
    refused = ApiError(400, "the cursor is not one this server issued")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error):
        raise refused from None
    if not isinstance(value, dict) or set(value) - set(fields):
        raise refused
    for key, kind in fields.items():
        item = value.get(key)
        if item is None:
            continue
        if kind is int and (type(item) is not int or item < 0):
            raise refused
        if kind is str and not isinstance(item, str):
            raise refused
    return value


def parse_citation(citation: str):
    """`symposium-data:<uuid>@v<n>` -> (file id, version number), or None."""
    if not isinstance(citation, str) or not citation.startswith("symposium-data:"):
        return None
    body = citation.split(":", 1)[1]
    file_id, _, version = body.partition("@v")
    try:
        return uuid.UUID(file_id), int(version)
    except ValueError:
        return None


class ApiService(Service):
    def __init__(self, runtime, keys, contract):
        self.runtime = runtime
        self.records = runtime.records
        self.index = Index(runtime.records, runtime.store)
        self.keys = keys
        self.contract = contract
        self.caps = Caps(runtime.db)
        self.notifier = Notifier(runtime.settings.database_url)
        self.findings_cache: dict = {}

    # ── plumbing ───────────────────────────────────────────────────────────────────────────
    @contextmanager
    def connection(self):
        with self.runtime.db.connection() as conn:
            yield conn

    def community(self, conn, value) -> str:
        name = plain(value)
        found = self.records.community_name(conn, name) if name else None
        if found is None:
            raise ApiError(404, f"no community '{name}'")
        return found

    def fresh(self, conn, value) -> str:
        """The community, with the index folded up to its record."""
        community = self.community(conn, value)
        self.index.catch_up(conn, community)
        return community

    def position(self, conn, community: str) -> dict:
        seq = self.index.position(conn, community)
        newest = self.index.newest(conn, community)
        return {
            "cursor": encode(r=seq),
            "seq": seq,
            "created": iso(newest["created"]) if newest else None,
            "as_of": now(),
        }

    @staticmethod
    def base(caller: Caller) -> str:
        return caller.base_url + API

    def artifact_url(self, caller, community, name) -> str:
        return (
            f"{self.base(caller)}/{quote(community)}/artifacts/{quote(name, safe='')}"
        )

    def member_url(self, caller, community, handle) -> str:
        return (
            f"{self.base(caller)}/{quote(community)}/members/{quote(handle, safe='')}"
        )

    def address_url(
        self, caller, community, address: str, kind: str | None = None
    ) -> str:
        """The canonical URL of what an address names (api/DESIGN.md §1.4)."""
        base, _, schema = address.partition("#")
        segs = base[1:].split(".")
        if schema or kind is None and len(segs) > 1:
            return f"{self.base(caller)}/{quote(community)}/resolve?address=" + quote(
                address, safe=""
            )
        if kind == "member":
            return self.member_url(caller, community, segs[0])
        url = self.artifact_url(caller, community, segs[0])
        if kind == "object":
            return f"{url}/objects/{quote(segs[1], safe='')}"
        if kind == "property":
            return f"{url}/properties/{quote(segs[1], safe='')}"
        if kind == "object_property":
            return (
                f"{url}/objects/{quote(segs[1], safe='')}"
                f"/properties/{quote(segs[2], safe='')}"
            )
        return url

    def doc_row(self, conn, community, name):
        row = self.index.artifact(conn, community, plain(name))
        if row is None:
            raise ApiError(
                404, f"no artifact '{plain(name)}' in the record of {community}"
            )
        return row

    @staticmethod
    def window(items: list, cursor, limit) -> tuple[list, str | None]:
        """An offset page over a bounded list."""
        start = decode(cursor, o=int).get("o", 0)
        limit = int(plain(limit) or 100)
        chunk = items[start : start + limit]
        more = start + limit < len(items)
        return chunk, encode(o=start + limit) if more else None

    def members(self, conn, community) -> set:
        published = self.index.publishers(conn, community)
        return members_of(conn, self.records, community, published)

    # ── summaries ──────────────────────────────────────────────────────────────────────────
    def summary(self, conn, caller, community, row) -> dict:
        doc, header = row["doc"], row["doc"]["artifact"]
        objects = doc.get("objects", [])
        grounds = [o for o in objects if o.get("type") == "Ground"]
        later = [
            r["from_name"]
            for r in self.index.superseded_by(conn, community, row["name"])
        ]
        groundable = not (
            header.get("type") in NON_GROUNDABLE_TYPES
            or header.get("groundable") is False
        )
        out = {
            "name": row["name"],
            "address": f"@{row['name']}",
            "url": self.artifact_url(caller, community, row["name"]),
            "type": header.get("type", ""),
            "published_by": row["published_by"],
            "created": iso(row["created"]),
            "groundable": groundable,
            "supersedes": list(header.get("supersedes") or []),
            "superseded_by": [f"@{n}" for n in later],
            "counts": {
                "objects": len(objects),
                "grounds": len(grounds),
                "tests": sum(1 for g in grounds if g.get("criterion")),
                "findings": len(row["findings"]),
            },
        }
        if header.get("title"):
            out["title"] = header["title"]
        return out

    def summary_page(self, conn, caller, community, cursor, limit, order, **filters):
        after = decode(cursor, r=int).get("r")
        descending = plain(order) == "-created"
        rows = self.index.page(
            conn,
            community,
            after=after,
            limit=int(plain(limit) or 100) + 1,
            descending=descending,
            **filters,
        )
        limit = int(plain(limit) or 100)
        more, rows = len(rows) > limit, rows[:limit]
        return {
            "items": [self.summary(conn, caller, community, r) for r in rows],
            "next": encode(r=rows[-1]["seq"]) if more else None,
            "position": self.position(conn, community),
        }

    # ── the contract ───────────────────────────────────────────────────────────────────────
    def get_open_api_yaml(self, caller):
        return Response(self.contract.text, media_type="application/yaml")

    def get_open_api_json(self, caller):
        return Response(self.contract.json, media_type="application/json")

    # ── the record ─────────────────────────────────────────────────────────────────────────
    def get_record(self, caller, *, community):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            rows = self.index.docs(conn, community)
            versions = sorted(
                {r["doc"]["artifact"].get("specification_version", "") for r in rows}
                - {""}
            )
            return m.RecordState.model_validate(
                {
                    "community": community,
                    "url": f"{self.base(caller)}/{quote(community)}/record",
                    "position": self.position(conn, community),
                    "counts": self.index.counts(conn, community),
                    "members": len(self.records.roster(conn, community)),
                    "first_created": iso(rows[0]["created"]) if rows else None,
                    "specification_versions": versions,
                }
            )

    def list_artifacts(
        self,
        caller,
        *,
        community,
        cursor,
        limit,
        order,
        type,
        published_by,
        created_after,
    ):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            return m.ArtifactSummaryPage.model_validate(
                self.summary_page(
                    conn,
                    caller,
                    community,
                    cursor,
                    limit,
                    order,
                    types=plain(type),
                    published_by=plain(published_by),
                    created_after=created_after,
                )
            )

    def get_artifact(self, caller, *, community, name):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row = self.doc_row(conn, community, name)
            header = row["doc"]["artifact"]
            url = self.artifact_url(caller, community, row["name"])
            links = {
                "member": self.member_url(caller, community, row["published_by"]),
                "supersedes": [
                    self.address_url(caller, community, a, "artifact")
                    for a in header.get("supersedes") or []
                ],
                "superseded_by": [
                    self.artifact_url(caller, community, r["from_name"])
                    for r in self.index.superseded_by(conn, community, row["name"])
                ],
                "cited_by": f"{url}/cited-by",
                "findings": f"{url}/findings",
                "content": f"{url}/content",
            }
            if isinstance(header.get("produced_by"), str):
                links["produced_by"] = self.address_url(
                    caller, community, header["produced_by"], "artifact"
                )
            return m.ArtifactResource.model_validate(
                {
                    "url": url,
                    "address": f"@{row['name']}",
                    "position": self.position(conn, community),
                    "links": links,
                    "canonical": row["doc"],
                }
            )

    def get_artifact_content(self, caller, *, community, name):
        """The Artifact's canonical JSON exactly as the gate stored it."""
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row = self.doc_row(conn, community, name)
            try:
                version = self.records.version(
                    conn, community, row["file_id"], "latest"
                )
                stored = self.runtime.store.open_read(version["s3_key"])["Body"].read()
            except Exception:
                raise ApiError(
                    404, f"no stored content for '{row['name']}' in {community}"
                ) from None
        return Response(stored, media_type="application/json")

    def get_artifact_property(self, caller, *, community, name, property):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row = self.doc_row(conn, community, name)
            header, prop = row["doc"]["artifact"], plain(property)
            if prop not in header:
                raise ApiError(404, f"'{row['name']}' has no property '{prop}'")
            address = f"@{row['name']}.{prop}"
            return m.PropertyResource.model_validate(
                {
                    "url": self.address_url(caller, community, address, "property"),
                    "address": address,
                    "property": prop,
                    "value": header[prop],
                    "position": self.position(conn, community),
                }
            )

    def objects_of(self, conn, community, name) -> tuple[dict, list]:
        row = self.doc_row(conn, community, name)
        return row, row["doc"].get("objects", [])

    def object_of(self, conn, community, name, object) -> tuple[dict, dict]:
        row, objects = self.objects_of(conn, community, name)
        wanted = plain(object)
        for obj in objects:
            if obj.get("name") == wanted:
                return row, obj
        raise ApiError(404, f"'{row['name']}' has no Object '{wanted}'")

    def list_objects(self, caller, *, community, name, cursor, limit, type):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row, objects = self.objects_of(conn, community, name)
            if plain(type):
                objects = [o for o in objects if o.get("type") == plain(type)]
            chunk, nxt = self.window(objects, cursor, limit)
            items = []
            for obj in chunk:
                address = f"@{row['name']}.{obj['name']}"
                items.append(
                    {
                        "url": self.address_url(caller, community, address, "object"),
                        "address": address,
                        "object": obj,
                    }
                )
            return m.ObjectPage.model_validate(
                {
                    "items": items,
                    "next": nxt,
                    "position": self.position(conn, community),
                }
            )

    def get_object(self, caller, *, community, name, object):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row, obj = self.object_of(conn, community, name, object)
            address = f"@{row['name']}.{obj['name']}"
            url = self.artifact_url(caller, community, row["name"])
            return m.ObjectResource.model_validate(
                {
                    "url": self.address_url(caller, community, address, "object"),
                    "address": address,
                    "artifact_url": url,
                    "object": obj,
                    "relationships_url": f"{url}/relationships",
                    "position": self.position(conn, community),
                }
            )

    def get_object_property(self, caller, *, community, name, object, property):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row, obj = self.object_of(conn, community, name, object)
            prop = plain(property)
            if prop not in obj:
                raise ApiError(404, f"Object '{obj['name']}' has no property '{prop}'")
            address = f"@{row['name']}.{obj['name']}.{prop}"
            return m.PropertyResource.model_validate(
                {
                    "url": self.address_url(
                        caller, community, address, "object_property"
                    ),
                    "address": address,
                    "property": prop,
                    "value": obj[prop],
                    "position": self.position(conn, community),
                }
            )

    def list_relationships(self, caller, *, community, name, cursor, limit, rel):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row = self.doc_row(conn, community, name)
            rels = row["doc"].get("relationships", [])
            if plain(rel):
                rels = [
                    r for r in rels if (r.get("rel") or r.get("type")) == plain(rel)
                ]
            chunk, nxt = self.window(rels, cursor, limit)
            return m.RelationshipPage.model_validate(
                {
                    "items": chunk,
                    "next": nxt,
                    "position": self.position(conn, community),
                }
            )

    def list_cited_by(self, caller, *, community, name, cursor, limit, via):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row = self.doc_row(conn, community, name)
            limit = int(plain(limit) or 100)
            state = decode(cursor, o=int)
            rows = self.index.cited_by(
                conn,
                community,
                row["name"],
                after=None,
                limit=100000,
                vias=plain(via),
            )
            start = state.get("o", 0)
            chunk = rows[start : start + limit]
            items = []
            for c in chunk:
                item = {
                    "via": c["via"],
                    "address": c["address"],
                    "from": f"@{c['from_name']}",
                    "from_url": self.artifact_url(caller, community, c["from_name"]),
                    "from_type": c["from_type"],
                    "from_created": iso(c["from_created"]),
                }
                if c["ground"]:
                    item["ground"] = c["ground"]
                items.append(item)
            nxt = encode(o=start + limit) if start + limit < len(rows) else None
            return m.CitationPage.model_validate(
                {
                    "items": items,
                    "next": nxt,
                    "position": self.position(conn, community),
                }
            )

    def list_supersession(self, caller, *, community, name, cursor, limit):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            start = self.doc_row(conn, community, name)
            chain, frontier = {}, [(start["name"], 0, None)]
            seen = {start["name"]}
            while frontier:
                current, distance, _ = frontier.pop(0)
                row = self.index.artifact(conn, community, current)
                earlier = [
                    a.lstrip("@").split(".")[0].split("#")[0]
                    for a in (
                        row["doc"]["artifact"].get("supersedes") or [] if row else []
                    )
                ]
                later = [
                    r["from_name"]
                    for r in self.index.superseded_by(conn, community, current)
                ]
                for direction, names in (("earlier", earlier), ("later", later)):
                    for other in names:
                        if other in seen:
                            continue
                        seen.add(other)
                        target = self.index.artifact(conn, community, other)
                        if target is None:
                            continue
                        chain[other] = (target, direction, distance + 1)
                        frontier.append((other, distance + 1, direction))
            entries = []
            for other, (target, direction, distance) in sorted(
                chain.items(), key=lambda kv: kv[1][0]["seq"]
            ):
                entry = {
                    "address": f"@{other}",
                    "url": self.artifact_url(caller, community, other),
                    "created": iso(target["created"]),
                    "direction": direction,
                    "distance": distance,
                }
                rationale = target["doc"]["artifact"].get("supersedes_rationale")
                if rationale:
                    entry["supersedes_rationale"] = rationale
                entries.append(entry)
            chunk, nxt = self.window(entries, cursor, limit)
            return m.SupersessionPage.model_validate(
                {
                    "items": chunk,
                    "next": nxt,
                    "position": self.position(conn, community),
                }
            )

    def current_findings(self, conn, community, row) -> list:
        """The validator's findings against the whole record now, computed once per index
        position: a record that has not moved answers from the cache."""
        position = self.index.position(conn, community)
        key = (community, row["name"], position)
        if key not in self.findings_cache:
            others = [
                r["doc"]
                for r in self.index.docs(conn, community)
                if r["name"] != row["name"]
            ]
            if len(self.findings_cache) >= 4096:
                self.findings_cache.clear()
            self.findings_cache[key] = validate(
                row["doc"], others, self.members(conn, community)
            )
        return list(self.findings_cache[key])

    def list_findings(self, caller, *, community, name, cursor, limit, basis, level):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row = self.doc_row(conn, community, name)
            basis = plain(basis) or "current"
            if basis == "accepted":
                findings = list(row["findings"])
            else:
                findings = self.current_findings(conn, community, row)
            if plain(level):
                findings = [f for f in findings if f["level"] == plain(level)]
            findings.sort(key=lambda f: (f["check"], f["msg"]))
            chunk, nxt = self.window(findings, cursor, limit)
            return m.FindingPage.model_validate(
                {
                    "items": chunk,
                    "basis": basis,
                    "next": nxt,
                    "position": self.position(conn, community),
                }
            )

    def resolve_address(self, caller, *, community, address):
        address = plain(address)
        with self.connection() as conn:
            community = self.fresh(conn, community)
            vindex, _ = self.index.validator_index(conn, community)
            ok, info, reason = resolve(address, vindex, self.members(conn, community))
            if not ok:
                status = 400 if reason.startswith("malformed") else 404
                raise ApiError(status, reason)
            kind = info["kind"]
            out = {
                "address": address,
                "kind": kind,
                "url": self.address_url(
                    caller, community, address, None if info.get("method") else kind
                ),
                "position": self.position(conn, community),
            }
            if kind == "member":
                return m.Resolution.model_validate(out)
            for key in ("artifact", "object", "property", "node_type", "method", "ref"):
                if info.get(key) is not None:
                    out[key] = info[key]
            rec = info["rec"]
            holder = (
                rec["objects"][info["object"]] if info.get("object") else rec["header"]
            )
            if info.get("property") and not info.get("method"):
                out["value"] = holder[info["property"]]
            if info.get("method"):
                method = info["method_obj"]
                out["verified"] = not verify_content(info)
                for key in ("location", "access_method"):
                    if isinstance(method.get(key), str):
                        out[key] = method[key]
            return m.Resolution.model_validate(out)

    # ── members ────────────────────────────────────────────────────────────────────────────
    def member(self, conn, caller, community, handle, roster: dict) -> dict:
        counts = self.index.member_counts(conn, community, handle)
        url = self.member_url(caller, community, handle)
        return {
            "handle": handle,
            "address": f"@{handle}",
            "url": url,
            "registered": bool(roster.get(handle, {}).get("registered")),
            "counts": counts,
            "artifacts_url": f"{url}/artifacts",
            "messages_url": f"{url}/messages",
            "position": self.position(conn, community),
        }

    def handles(self, conn, community) -> tuple[list, dict]:
        roster = {r["handle"]: r for r in self.records.roster(conn, community)}
        published = self.index.publishers(conn, community)
        return sorted(set(roster) | published), roster

    def list_members(self, caller, *, community, cursor, limit):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            handles, roster = self.handles(conn, community)
            chunk, nxt = self.window(handles, cursor, limit)
            return m.MemberPage.model_validate(
                {
                    "items": [
                        self.member(conn, caller, community, h, roster) for h in chunk
                    ],
                    "next": nxt,
                    "position": self.position(conn, community),
                }
            )

    def get_member(self, caller, *, community, handle):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            handles, roster = self.handles(conn, community)
            if plain(handle) not in handles:
                raise ApiError(404, f"no member '{plain(handle)}' in {community}")
            return m.MemberResource.model_validate(
                self.member(conn, caller, community, plain(handle), roster)
            )

    def list_member_artifacts(self, caller, *, community, handle, cursor, limit, order):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            return m.ArtifactSummaryPage.model_validate(
                self.summary_page(
                    conn,
                    caller,
                    community,
                    cursor,
                    limit,
                    order,
                    published_by=plain(handle),
                )
            )

    def list_member_messages(self, caller, *, community, handle, cursor, limit, order):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            return m.ArtifactSummaryPage.model_validate(
                self.summary_page(
                    conn,
                    caller,
                    community,
                    cursor,
                    limit,
                    order,
                    recipient=plain(handle),
                )
            )

    def get_me(self, caller, *, community):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            row = self.keys.row(conn, caller.community, caller.key_id)
            out = {
                "handle": caller.handle,
                "label": caller.label,
                "role": caller.role,
                "community": row["community"],
                "key_id": str(caller.key_id),
                "expires": iso(row["expires"]),
                "position": self.position(conn, community),
            }
            if caller.handle:
                out["member_url"] = self.member_url(caller, community, caller.handle)
            return m.Me.model_validate(out)

    # ── submissions ────────────────────────────────────────────────────────────────────────
    def read_json(self, row) -> dict | None:
        try:
            value = json.loads(
                self.runtime.store.open_read(row["s3_key"])["Body"].read()
            )
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def reply_for(self, conn, community, citation):
        rows = self.records.query(
            conn, community, "inbox", {MARK_REPLY: True, MARK_CITATION: citation}, 0, 1
        )
        return rows[0] if rows else None

    def accepted_for(self, conn, community, citation):
        rows = self.records.query(
            conn, community, "record", {MARK_CITATION: citation}, 0, 1
        )
        return rows[0] if rows else None

    def submission(self, conn, caller, community, row, members=None) -> dict:
        """One inbox submission and the gate's decision on it."""
        citation = f"symposium-data:{row['file_id']}@v{row['n']}"
        name = row["name"].partition("@")[0]
        out = {
            "id": str(row["file_id"]),
            "url": f"{self.base(caller)}/{quote(community)}/submissions/{row['file_id']}",
            "name": name,
            "submitted_by": row["created_by"],
            "submitted": iso(row["created"]),
            "citation": citation,
            "decided": None,
            "position": self.position(conn, community),
        }
        doc = self.read_json(row)
        header = (doc or {}).get("artifact") or {}
        if header.get("type"):
            out["type"] = header["type"]
        accepted = self.accepted_for(conn, community, citation)
        reply = None if accepted else self.reply_for(conn, community, citation)
        if accepted is not None:
            out["status"], out["decided"] = "accepted", iso(accepted["created"])
            out["artifact_url"] = self.artifact_url(caller, community, accepted["name"])
        elif reply is not None:
            out["status"], out["decided"] = "rejected", iso(reply["created"])
            text = ((self.read_json(reply) or {}).get("artifact") or {}).get("text", "")
            out["reply"] = {
                "sender": reply["created_by"],
                "sent": iso(reply["created"]),
                "text": text,
                "failures": [
                    line[2:] for line in text.splitlines() if line.startswith("- ")
                ],
            }
        else:
            members = members if members is not None else self.members(conn, community)
            why = skip_reason(
                row["name"], row["created_by"], header.get("name"), members
            )
            out["status"] = "skipped" if why else "pending"
        return out

    def visible(self, caller, row) -> bool:
        return row["created_by"] == caller.handle

    def submissions_after(self, conn, caller, community, since, want, status=None):
        """Visible submissions after inbox seq `since`, up to `want`. -> (items, last seq
        scanned, whether the feed has more)."""
        members = self.members(conn, community)
        items, last = [], since
        while len(items) < want:
            rows = self.records.changes(conn, community, "inbox", last, 200)
            if not rows:
                return items, last, False
            for row in rows:
                if len(items) >= want:
                    return items, last, True
                last = row["seq"]
                meta = row["metadata"] or {}
                if (
                    not meta.get(MARK_SUBMISSION)
                    or row["deleted"]
                    or not self.visible(caller, row)
                ):
                    continue
                item = self.submission(conn, caller, community, row, members)
                if status is None or item["status"] == status:
                    items.append(item)
            if len(rows) < 200:
                return items, last, False
        return items, last, True

    def list_submissions(self, caller, *, community, cursor, limit, status):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            limit = int(plain(limit) or 100)
            items, last, more = self.submissions_after(
                conn,
                caller,
                community,
                decode(cursor, i=int).get("i", 0),
                limit,
                plain(status),
            )
            return m.SubmissionPage.model_validate(
                {
                    "items": items,
                    "next": encode(i=last) if more else None,
                    "position": self.position(conn, community),
                }
            )

    def get_submission(self, caller, *, community, submission):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            try:
                row = self.records.version(conn, community, plain(submission), 1)
            except Exception:
                raise ApiError(404, f"no submission '{plain(submission)}'") from None
            meta = row["metadata"] or {}
            if row["collection"] != "inbox" or not meta.get(MARK_SUBMISSION):
                raise ApiError(404, f"no submission '{plain(submission)}'")
            if not self.visible(caller, row):
                raise ApiError(403, "a member reads only its own submissions")
            return m.SubmissionResource.model_validate(
                self.submission(conn, caller, community, row)
            )

    def checks(self, conn, caller, community, doc: dict) -> list:
        """Every refusal the gate would make, plus `publish`'s own: the API's
        `/symposium validate`."""
        header = doc.get("artifact") or {}
        findings = []
        if header.get("created") is not None:
            findings.append(
                {
                    "check": "STRUCT",
                    "level": "FAIL",
                    "msg": "created must be null: the gate stamps it",
                }
            )
        if header.get("published_by") != f"@{caller.handle}":
            findings.append(
                {
                    "check": "ATTRIBUTION",
                    "level": "FAIL",
                    "msg": f"published_by must be @{caller.handle}, this key's Member",
                }
            )
        refusal = naming_refusal(header.get("name", ""), caller.handle)
        if refusal:
            findings.append({"check": "NAMING", "level": "FAIL", "msg": refusal})
        refusal = payload_refusal(doc)
        if refusal:
            findings.append({"check": "SIZE", "level": "FAIL", "msg": refusal})
        # a provisional `created` the way `publish` stamps one: one second after the later of
        # now and the newest acceptance, so the ordering rule sees what the gate will see
        rows = self.index.docs(conn, community)
        base = max([datetime.now(UTC), *(r["created"] for r in rows)])
        provisional = json.loads(json.dumps(doc))
        provisional["artifact"]["created"] = (base + timedelta(seconds=1)).isoformat(
            timespec="seconds"
        )
        record = [r["doc"] for r in rows]
        findings += validate(
            provisional, record, self.members(conn, community) | {caller.handle}
        )
        return findings

    def check_submission(self, caller, *, community, body, raw):
        # the rules judge the JSON as sent; the generated model already checked its shape
        doc = raw
        with self.connection() as conn:
            community = self.fresh(conn, community)
            findings = self.checks(conn, caller, community, doc)
            return m.SubmissionCheck.model_validate(
                {
                    "ok": passed(findings)
                    and not any(f["level"] == "FAIL" for f in findings),
                    "findings": findings,
                    "position": self.position(conn, community),
                }
            )

    def submit_artifact(self, caller, *, community, body, raw):
        # the rules judge, and inbox stores, the JSON as sent; the model checked its shape
        doc = raw
        name = (doc.get("artifact") or {}).get("name", "")
        runtime, records = self.runtime, self.records
        with self.connection() as conn:
            community = self.fresh(conn, community)
            if not records.can_create(conn, caller.handle, community, "inbox"):
                raise ApiError(403, f"'{caller.handle}' may not submit to {community}")
            # a name already in the record is a conflict, before the validator says so
            if self.index.artifact(conn, community, name) is not None:
                raise ApiError(409, f"'{name}' is already in the record of {community}")
            findings = self.checks(conn, caller, community, doc)
            if any(f["level"] == "FAIL" for f in findings):
                raise ApiError(
                    422,
                    f"the validator refused '{name}'",
                    code="validation_failed",
                    findings=findings,
                )
            data = (json.dumps(doc, indent=2) + "\n").encode()
            pid, s3_key = records.begin_payload(conn, community, caller.handle)
            conn.commit()
        runtime.store.put_bytes(s3_key, data)
        when = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.connection() as conn:
            try:
                payload, _ = records.commit_payload(
                    conn,
                    pid,
                    community,
                    hashlib.sha256(data).hexdigest(),
                    len(data),
                    caller.handle,
                    runtime.settings.quota(),
                )
            except Exception as e:
                conn.rollback()
                if type(e).__name__ == "QuotaExceeded":
                    raise ApiError(413, str(e)) from None
                raise
            file_id = records.create_live_file(
                conn, community, "inbox", f"{name}@{when}"
            )
            records.add_version(
                conn,
                file_id,
                payload,
                {MARK_SUBMISSION: True},
                "application/json",
                caller.handle,
                None,
            )
            conn.commit()
            row = records.version(conn, community, file_id, 1)
            resource = self.submission(conn, caller, community, row)
        return m.SubmissionResource.model_validate(resource)

    # ── streams ────────────────────────────────────────────────────────────────────────────
    def still_allowed(self, caller: Caller, community: str) -> bool:
        """The re-check at every event and heartbeat: revoked, expired, off the roster or
        unbound keys lose their stream, and an anonymous stream ends once the record it
        follows is made private."""
        with self.connection() as conn:
            if caller.kind == "anonymous":
                return bool(
                    self.records.collection_row(conn, community, "record")["public"]
                )
            if caller.kind != "api_key":
                return True
            row = self.keys.live(conn, caller.key_id)
            return (
                row is not None and standing(conn, self.records, row, community) is None
            )

    def stream_record(self, caller, *, community, last__event__i_d):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            start = decode(last__event__i_d, r=int).get("r")
            if start is None:
                start = self.index.position(conn, community)
        stream_id = self.caps.open(caller.key_id, caller.role, caller.client_addr)
        return self.record_events(caller, community, int(start), stream_id)

    async def record_events(self, caller, community, seq, stream_id):
        def read(after):
            with self.connection() as conn:
                self.index.catch_up(conn, community)
                rows = self.index.page(conn, community, after=after, limit=200)
                return [
                    (r["seq"], self.summary(conn, caller, community, r)) for r in rows
                ]

        def heartbeat():
            with self.connection() as conn:
                return self.position(conn, community)

        try:
            beat = time.monotonic()
            while True:
                generation = self.notifier.generation
                rows = await asyncio.to_thread(read, seq)
                for row_seq, summary in rows:
                    if not await asyncio.to_thread(
                        self.still_allowed, caller, community
                    ):
                        return
                    seq = row_seq
                    yield m.RecordStreamEvent.model_validate(
                        {"id": encode(r=seq), "event": "artifact", "data": summary}
                    )
                if rows:
                    continue
                if time.monotonic() - beat >= HEARTBEAT or not await self.notifier.wait(
                    HEARTBEAT - (time.monotonic() - beat), generation
                ):
                    if not await asyncio.to_thread(
                        self.still_allowed, caller, community
                    ):
                        return
                    await asyncio.to_thread(self.caps.beat, stream_id)
                    beat = time.monotonic()
                    position = await asyncio.to_thread(heartbeat)
                    yield m.RecordStreamEvent.model_validate(
                        {
                            "id": encode(r=seq),
                            "event": "heartbeat",
                            "data": {"position": position},
                        }
                    )
        finally:
            # synchronously: a client that disconnects cancels this generator, and an await
            # here would be cancelled with it, leaving the slot taken until the sweep
            self.caps.close(stream_id)

    def stream_submissions(self, caller, *, community, last__event__i_d):
        with self.connection() as conn:
            community = self.fresh(conn, community)
            start = decode(last__event__i_d, i=int, r=int)
            if "i" not in start:
                start = {
                    "i": self.records.collection_row(conn, community, "inbox")["seq"],
                    "r": self.records.collection_row(conn, community, "record")["seq"],
                }
        stream_id = self.caps.open(caller.key_id, caller.role, caller.client_addr)
        return self.submission_events(
            caller, community, int(start["i"]), int(start.get("r", 0)), stream_id
        )

    def submission_changes(self, caller, community, inbox, record):
        """The events after the (inbox, record) positions. -> [(inbox, record, event, data)]"""
        out = []
        with self.connection() as conn:
            members = self.members(conn, community)
            for row in self.records.changes(conn, community, "inbox", inbox, 200):
                inbox = row["seq"]
                meta = row["metadata"] or {}
                if row["deleted"]:
                    continue
                if meta.get(MARK_SUBMISSION) and self.visible(caller, row):
                    item = self.submission(conn, caller, community, row, members)
                    out.append((inbox, record, "submission.received", item))
                    if item["status"] == "skipped":
                        out.append((inbox, record, "submission.skipped", item))
                elif meta.get(MARK_REPLY):
                    cited = parse_citation(meta.get(MARK_CITATION))
                    source = self.submission_row(conn, community, cited)
                    if source is not None and self.visible(caller, source):
                        item = self.submission(conn, caller, community, source, members)
                        out.append((inbox, record, "submission.rejected", item))
            for row in self.records.changes(conn, community, "record", record, 200):
                record = row["seq"]
                cited = parse_citation((row["metadata"] or {}).get(MARK_CITATION))
                source = self.submission_row(conn, community, cited)
                if source is not None and self.visible(caller, source):
                    item = self.submission(conn, caller, community, source, members)
                    out.append((inbox, record, "submission.accepted", item))
            if not out:
                # nothing visible moved: still advance past what was scanned
                out.append((inbox, record, None, None))
        return out

    def submission_row(self, conn, community, cited):
        if cited is None:
            return None
        try:
            return self.records.version(conn, community, cited[0], cited[1])
        except Exception:
            return None

    async def submission_events(self, caller, community, inbox, record, stream_id):
        def heartbeat():
            with self.connection() as conn:
                self.index.catch_up(conn, community)
                return self.position(conn, community)

        try:
            beat = time.monotonic()
            while True:
                generation = self.notifier.generation
                changes = await asyncio.to_thread(
                    self.submission_changes, caller, community, inbox, record
                )
                moved = False
                for new_inbox, new_record, event, data in changes:
                    moved = moved or (new_inbox, new_record) != (inbox, record)
                    inbox, record = new_inbox, new_record
                    if event is None:
                        continue
                    if not await asyncio.to_thread(
                        self.still_allowed, caller, community
                    ):
                        return
                    yield m.SubmissionStreamEvent.model_validate(
                        {"id": encode(i=inbox, r=record), "event": event, "data": data}
                    )
                if moved:
                    continue
                if time.monotonic() - beat >= HEARTBEAT or not await self.notifier.wait(
                    HEARTBEAT - (time.monotonic() - beat), generation
                ):
                    if not await asyncio.to_thread(
                        self.still_allowed, caller, community
                    ):
                        return
                    await asyncio.to_thread(self.caps.beat, stream_id)
                    beat = time.monotonic()
                    position = await asyncio.to_thread(heartbeat)
                    yield m.SubmissionStreamEvent.model_validate(
                        {
                            "id": encode(i=inbox, r=record),
                            "event": "heartbeat",
                            "data": {"position": position},
                        }
                    )
        finally:
            # synchronously: a client that disconnects cancels this generator, and an await
            # here would be cancelled with it, leaving the slot taken until the sweep
            self.caps.close(stream_id)
