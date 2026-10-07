"""The derived index (api/DESIGN.md §1.3): what no single Artifact holds, folded from each
community's `record` feed into PostgreSQL. It holds every Artifact's canonical JSON, the
citations between Artifacts, and each Artifact's findings as the gate saw them at acceptance.

The index is a cache of the record and never its source of truth. Every read first folds in
whatever the feed gained since the index's position, under a per-community advisory lock, so
a read answers from an index at least as new as the record it started with.
"""

from __future__ import annotations

import json
from datetime import datetime

from symposium_rules.validate import (
    CITATION_RE,
    CODE_SPAN_RE,
    build_index,
    parse_address,
    validate,
)

RECORD = "record"
BATCH = 200
# header properties whose values are addresses, and the citation kind each one is
HEADER_ADDRESSES = {
    "produced_by": "produced_by",
    "extracted_from": "extracted_from",
    "inputs": "inputs",
    "supersedes": "supersedes",
    "serves_goals": "serves_goals",
    "recipients": "recipients",
}


def members_of(conn, records, community: str, published: set) -> set:
    """Member names as the gate counts them: the roster, the admin, and every publisher."""
    roster = {r["handle"] for r in records.roster(conn, community)}
    admin = records.config(conn, "admin")
    return roster | published | ({admin} if admin else set())


def prose(value):
    """The addresses cited in a free-text value, skipping code spans."""
    if not isinstance(value, str):
        return []
    text = CODE_SPAN_RE.sub("", value)
    return [m.group(1) or m.group(2) for m in CITATION_RE.finditer(text)]


def citations(doc: dict, docs_by_name: dict) -> list[dict]:
    """Every citation `doc` makes of another Artifact: {target, via, address, ground}."""
    header, own = doc.get("artifact", {}), doc.get("artifact", {}).get("name")
    out = []

    def add(address, via, ground=None):
        parsed = parse_address(address)
        if parsed and parsed["root"] != own:
            out.append(
                {
                    "target": parsed["root"],
                    "via": via,
                    "address": address,
                    "ground": ground,
                }
            )

    for prop, via in HEADER_ADDRESSES.items():
        value = header.get(prop)
        for address in value if isinstance(value, list) else [value]:
            if isinstance(address, str):
                add(address, via)
    for obj in doc.get("objects", []):
        if obj.get("type") == "Ground" and isinstance(obj.get("citation"), str):
            parsed = parse_address(obj["citation"])
            target = docs_by_name.get(parsed["root"]) if parsed else None
            testimony = bool(
                target
                and target["artifact"].get("type") == "Argument"
                and parsed["segs"]
                and any(
                    o.get("name") == parsed["segs"][0] and o.get("type") == "Assertion"
                    for o in target.get("objects", [])
                )
            )
            add(
                obj["citation"],
                "testimony" if testimony else "ground",
                f"@{own}.{obj.get('name')}",
            )
    for holder in [header, *doc.get("objects", [])]:
        for key, value in holder.items():
            if key != "citation":
                for address in prose(value):
                    add(address, "prose")
    return out


class Index:
    def __init__(self, records, store):
        self.records, self.store = records, store

    def read(self, row) -> dict:
        return json.loads(self.store.open_read(row["s3_key"])["Body"].read())

    def position(self, conn, community: str) -> int:
        row = conn.execute(
            "SELECT seq FROM api_index_position WHERE community = %s", (community,)
        ).fetchone()
        return row["seq"] if row else 0

    def catch_up(self, conn, community: str) -> int:
        """Fold every record version after the index's position into the index. -> position."""
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('symposium_api_index:' || %s))",
            (community,),
        )
        since = self.position(conn, community)
        while True:
            rows = self.records.changes(conn, community, RECORD, since, BATCH)
            if not rows:
                break
            known = {r["name"]: r["doc"] for r in self.docs(conn, community)}
            for row in rows:
                since = row["seq"]
                if (
                    row["deleted"]
                    or row["purged"]
                    or not (row["metadata"] or {}).get("symposium_record")
                ):
                    continue
                doc = self.read(row)
                header = doc.get("artifact", {})
                name = header.get("name")
                if not name or name in known:
                    continue
                prior = list(known.values())
                published = {
                    d["artifact"].get("published_by", "@").lstrip("@") for d in prior
                } | {header.get("published_by", "@").lstrip("@")}
                members = members_of(conn, self.records, community, published)
                findings = validate(doc, prior, members)
                conn.execute(
                    "INSERT INTO api_index (community, name, seq, created, type, "
                    "published_by, file_id, sha256, doc, findings) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (
                        community,
                        name,
                        row["seq"],
                        row["created"],
                        header.get("type", ""),
                        header.get("published_by", "@").lstrip("@"),
                        row["file_id"],
                        row["sha256"],
                        json.dumps(doc),
                        json.dumps(findings),
                    ),
                )
                known[name] = doc
                for c in citations(doc, known):
                    conn.execute(
                        "INSERT INTO api_citations (community, target, via, address, "
                        "from_name, from_seq, from_created, from_type, ground) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            community,
                            c["target"],
                            c["via"],
                            c["address"],
                            name,
                            row["seq"],
                            row["created"],
                            header.get("type", ""),
                            c["ground"],
                        ),
                    )
            conn.execute(
                "INSERT INTO api_index_position (community, seq) VALUES (%s, %s) "
                "ON CONFLICT (community) DO UPDATE SET seq = EXCLUDED.seq",
                (community, since),
            )
            if len(rows) < BATCH:
                break
        conn.commit()
        return since

    # ── reads ──────────────────────────────────────────────────────────────────────────────
    def docs(self, conn, community: str) -> list:
        return conn.execute(
            "SELECT * FROM api_index WHERE community = %s ORDER BY seq", (community,)
        ).fetchall()

    def artifact(self, conn, community: str, name: str):
        return conn.execute(
            "SELECT * FROM api_index WHERE community = %s AND name = %s",
            (community, name),
        ).fetchone()

    def newest(self, conn, community: str):
        return conn.execute(
            "SELECT seq, created FROM api_index WHERE community = %s "
            "ORDER BY seq DESC LIMIT 1",
            (community,),
        ).fetchone()

    def page(
        self,
        conn,
        community: str,
        *,
        after: int | None,
        limit: int,
        descending: bool = False,
        types=None,
        published_by=None,
        created_after: datetime | None = None,
        recipient: str | None = None,
    ) -> list:
        clauses, args = ["community = %s"], [community]
        if after is not None:
            clauses.append("seq < %s" if descending else "seq > %s")
            args.append(after)
        if types:
            clauses.append("type = ANY(%s)")
            args.append(list(types))
        if published_by:
            clauses.append("published_by = %s")
            args.append(published_by)
        if created_after:
            clauses.append("created > %s")
            args.append(created_after)
        if recipient:
            clauses.append("type = 'Message' AND doc->'artifact'->'recipients' ? %s")
            args.append(f"@{recipient}")
        order = "DESC" if descending else "ASC"
        return conn.execute(
            f"SELECT * FROM api_index WHERE {' AND '.join(clauses)} "
            f"ORDER BY seq {order} LIMIT %s",
            (*args, limit),
        ).fetchall()

    def cited_by(self, conn, community, target, *, after, limit, vias=None) -> list:
        clauses, args = ["community = %s", "target = %s"], [community, target]
        if after is not None:
            clauses.append("from_seq > %s")
            args.append(after)
        if vias:
            clauses.append("via = ANY(%s)")
            args.append(list(vias))
        return conn.execute(
            f"SELECT * FROM api_citations WHERE {' AND '.join(clauses)} "
            "ORDER BY from_seq, from_name, via, address LIMIT %s",
            (*args, limit),
        ).fetchall()

    def superseded_by(self, conn, community, name) -> list:
        return conn.execute(
            "SELECT DISTINCT from_name, from_seq FROM api_citations "
            "WHERE community = %s AND target = %s AND via = 'supersedes' ORDER BY from_seq",
            (community, name),
        ).fetchall()

    def counts(self, conn, community) -> dict:
        rows = conn.execute(
            "SELECT type, published_by, findings FROM api_index WHERE community = %s",
            (community,),
        ).fetchall()
        by_type, by_member, findings = {}, {}, {}
        for r in rows:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
            by_member[r["published_by"]] = by_member.get(r["published_by"], 0) + 1
            for f in r["findings"]:
                findings[f["level"]] = findings.get(f["level"], 0) + 1
        return {
            "artifacts": len(rows),
            "by_type": by_type,
            "by_member": by_member,
            "findings": findings,
        }

    def validator_index(self, conn, community) -> tuple[dict, list]:
        """(the validator's index of the whole record, every Artifact's canonical JSON)."""
        docs = [r["doc"] for r in self.docs(conn, community)]
        return build_index(docs), docs
