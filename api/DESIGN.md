# Symposium API: design notes

The Symposium API lets any application read a community record, follow it as it changes,
and publish to it through the gate as a Member. It speaks the specification's model
(Artifacts, Objects, properties, relationships, Members and addresses), not the data
server's model of files and versions.

These notes go with [`openapi.yaml`](openapi.yaml), the OpenAPI 3.1 document. The YAML is
the contract. These notes say why it has the shape it has. They cover issue #23. Building
the API, the API-key commands and the new table belongs to a later issue.

## 0. Where this lives

| File | Holds |
|---|---|
| `api/openapi.yaml` | the contract: every endpoint, its schemas, its roles and its errors |
| `api/DESIGN.md` | these notes |
| `api/redocly.yaml` | the linter's ruleset, `recommended-strict` |
| `tests/api/test_openapi.py` | checks the contract against the rules below and against these notes' tables |

The API gets its own top-level directory because it is a third face of Symposium. It sits
beside `spec/`, the model, and `data-server/`, the storage. The data server's process
serves it, from its own package. §10 lays out how the code depends on what, and §11
settles where the server runs.

Lint it with:

```bash
npx --yes @redocly/cli@2.59.0 lint --config api/redocly.yaml api/openapi.yaml
```

`make test` runs it, then `tests/api/`, and CI runs `make test`.

## 1. The resource model

### 1.1 From the specification to resources

Every type in the specification and in the profile (`tools/CANONICAL.md`) is shown below
with how the API reaches it. A **resource** has its own URL. A **sub-resource** has a URL
under its parent. A **traversal** is an endpoint that follows a relationship the record
holds only implicitly. The server computes each traversal from its index (§1.3).

| Specification type | API shape | URL |
|---|---|---|
| CommunityRecord (§1.1) | resource: the record's state | `/{community}/record` |
| Member (§1.4) | resource; exposes its name and nothing inside it | `/{community}/members/{handle}` |
| Artifact (§1.5), every type | resource, read-only | `/{community}/artifacts/{name}` |
| Artifact property | sub-resource | `/{community}/artifacts/{name}/properties/{property}` |
| Object (§1.6), every type | sub-resource of its Artifact | `/{community}/artifacts/{name}/objects/{object}` |
| Object property | sub-resource | `…/objects/{object}/properties/{property}` |
| Relationship (§1.7) | listed under its Artifact; it has no address, so it gets no URL of its own | `/{community}/artifacts/{name}/relationships` |
| Address (§1.8), schema references included | resolved | `/{community}/resolve?address=…` |
| Content (§1.8.1) | an Object, listed with `?type=Content`; the internal graph lists it too | `…/objects?type=Content` |

The Artifact types the specification defines, and the profile's community types, all use
the one Artifact resource. Their type-specific properties are documented on
`ArtifactHeader` and `RecordObject`. Each type also has its own traversals and views:

| Type | What the API adds for it |
|---|---|
| Argument (§2.2): Assertion, Ground, Assumption; verdict, rationale, purpose | `claim-graph`, `evidence`; its Grounds show up in the cited Artifact's `cited-by?via=ground` |
| Argument, extracted (`extracted_from`) | `cited-by?via=extracted_from` on the source |
| Non-Ground citation (§2.2.5) | `cited-by?via=prose` on the cited Artifact; `ProseCitation` nodes in the claim graph |
| Grounding on another Argument's primary Assertion | `cited-by?via=testimony`; `External` nodes in the claim graph |
| Data (§2.3), ScientificPublication (§2.4), Model (§2.6) | `internal-graph`; `grounded-spans` for `text_span` content |
| Analysis (§2.5): `inputs`, outputs by `produced_by` | `cited-by?via=produced_by` gives an Analysis's outputs; `cited-by?via=inputs` on a Data gives the Analyses that used it |
| NonGroundable (§2.7), Message (§2.8) | `members/{handle}/messages` gives the Messages addressed to a Member |
| ResearchGoal (profile §2.1), `serves_goals` | `cited-by?via=serves_goals` on the goal gives the work that serves it |
| `genre` (profile) | carried on the header; filterable through the summary |

### 1.2 Properties of the model that shape the API

- **Temporal ordering (§1.9).** `created` is stamped by the gate, and the record's `seq`
  grows in the same order. So "the record's `created` order" is a single total order.
  Every listing that defaults to it can page on `seq`.
- **Supersession.** `supersedes` points backwards. The API adds `superseded_by`, the
  forward direction, to each summary. `supersession` returns the whole chain. A superseded
  Artifact stays readable at its URL forever.
- **Groundability.** `groundable` is on the summary, so a client can tell from a listing
  that nothing in an Analysis, a NonGroundable, a Message or a ResearchGoal can be evidence.
- **Attribution and import (§1.10).** `authors`, `import_method` and `published_by` are
  header properties, read as they are. `published_by` is permanent. That is why §5.4 ties
  a publishing key to one Member.
- **Immutability.** No operation changes or deletes a recorded Artifact. The only writes
  are a submission into `inbox`, the gate's own operations, and API keys.

### 1.3 The index

The traversals and views need facts that no single Artifact holds: who cites whom, what
supersedes what, findings, and grounded spans. The server keeps a **derived index** of
these facts in its PostgreSQL. It folds in each Artifact the moment `record` gains it. The
index is a cache of the record and is never the source of truth. `POST gate/rebuild`
rebuilds it from the `record` feed, and `GET gate/verify` compares the two. Every read
answers from the index and states the index's `position` (§6.2).

### 1.4 Canonical URLs

Every resource body carries `url`: an absolute URL on the data server, under
`/api/v1/{community}`. It is the same whichever host or application asks. This removes the
record browser's `localhost` link problem. An application links to the API URL, or to its
own page built from it.

An address maps to a URL by a fixed rule:

| Address | URL |
|---|---|
| `@<member>` | `/{community}/members/<member>` |
| `@<artifact>` | `/{community}/artifacts/<artifact>` |
| `@<artifact>.<object>` | `/{community}/artifacts/<artifact>/objects/<object>` |
| `@<artifact>.<property>` | `/{community}/artifacts/<artifact>/properties/<property>` |
| `@<artifact>.<object>.<property>` | `…/objects/<object>/properties/<property>` |
| anything with `#<schema reference>` | `/{community}/resolve?address=<the address, URL-encoded>` |

`@a.x` can name either an Object or a property. The profile forbids an Object's name from
colliding with its Artifact's property names, so the server always knows which one is
meant. A client that does not know asks `resolve`.

## 2. The record browser's views → endpoints

The record browser (`tools/browse.py`, `tools/templates.py`, `tools/serve.py`) builds
static pages from one host's copy of the record. Each view it computes maps to an
endpoint. "Server-side" marks a view that only the server can answer efficiently, because
it needs every address in the record resolved.

| Browser view | Data it needs | Endpoint | Server-side |
|---|---|---|---|
| Overview graph (`index.html`) | one node per Artifact; citation edges counted by kind; counts | `getOverview` | yes: edges need every citation resolved |
| Artifact page (`<name>.html`, non-Argument) | header, non-groundable banner, Content Objects, properties | `getArtifact` | |
| Internal graph on the Artifact page | Objects other than Content, relationships, legend | `getInternalGraph` | |
| Argument claim graph (`<name>.html`) | Assertions, Grounds, Assumptions, cited sources, prose citations, verdict panel | `getClaimGraph` (`mode=claim` or `full`) | yes: source nodes need cited addresses resolved |
| Reading page and evidence table (`<name>_reading.html`) | verdict, purpose, rationale, description, text, supersession; one row per Ground | `getArtifact` + `getEvidence` | |
| Readings: CSV tables with cell anchors | the property's CSV and its `csv` Content | `getArtifactProperty` + `listObjects?type=Content`; a cell by `resolveAddress` | |
| Grounded text spans (`<mark>`) | every `text_span` quote that a later Ground cites | `listGroundedSpans` | yes: a back-reference across the record |
| Validator findings per Artifact | `{check, level, msg}` | `listFindings` (`basis=current` as the browser shows; `accepted` as the gate saw) | yes: computed against the record |
| Member colours and counts | members, a stable colour order, counts by member and by type | `listMembers` (`palette_index`) + `getRecord` | |
| Contents list (`contents.html`) | summaries grouped by type, newest first, verdict excerpt, Ground/test/finding counts | `listArtifacts?order=-created` (filter by `type` to group) | |
| Build summary (`browser_manifest.json`) | counts by type, by member, findings | `getRecord` | |
| Reload counter (`GET /__build`) | "has the record changed" | `streamRecord` (or `position` on any read) | |
| Navigation from a cited address | where an address leads | `resolveAddress` | |

The browser's layout file (`.browser_layout.json`), pinned positions, member colours and
the PNG/SVG export are presentation. They stay in the client.

## 3. The skill's commands → endpoints

Each command in `skills/symposium/SKILL.md` falls into one of four classes: a read
(`GET`), a write (`POST`, `PUT`, `DELETE`), a stream (SSE), or **not an API operation**.

| Command | Class | Endpoint | Why |
|---|---|---|---|
| `setup --invite-file` | not an API operation | `/v1/{community}/owners` | Joining makes the Member's Ed25519 key on its own machine and registers it with the invite. An API key comes from the admin. If an API key could join, the admin could make a Member's key, which breaks the life cycle. |
| `bootstrap --community-file` | not an API operation | `/v1/communities`, `/v1/{community}/roster`, `/v1/{community}/invites` | Creates the community and mints invites with the server admin's Ed25519 key. These are identity operations, and they stay on the one door that already guards them. |
| `use [<community> <handle>]` | not an API operation | none | It sets local state for one agent session. The server never sees it. |
| `publish [--role] <artifact.json>` | write | `submitArtifact` | |
| `publish --roles` | read | `listPublishRoles` | |
| `validate [--role] <artifact.json>` | write (stores nothing) | `checkSubmission` | A POST because it carries an Artifact in its body. |
| `sync` | read | `listArtifacts` (from a cursor) + `listReplies` | |
| `sync --watch` | stream | `streamRecord` + `streamReplies` | |
| `gate` | write | `runGatePass` | |
| `gate --dry-run` | write (stores nothing) | `runGatePass` with `dry_run: true` | |
| `gate --verify` | read | `verifyGate` | |
| `gate --rebuild` | write | `rebuildGate` | |
| `gate --watch` | stream | `streamSubmissions`, then `runGatePass` on each event | |
| `serve` | not an API operation | none | It serves pages from a local copy. The API replaces what it computes (§2). The pages themselves are an application. |
| `admin-config` | not an API operation | none | It makes the server admin's key on the admin's machine and places a file on the server's volume. |
| `roster list` | read | `listMembers` | |
| `roster add`, `roster remove` | not an API operation | `/v1/{community}/roster/{handle}` | Identity: who may join. It stays on `/v1` under the admin's Ed25519 key, beside invites. |
| `invite` | not an API operation | `/v1/{community}/invites` | Invites carry the secret a Member joins with. It stays with `setup`. |
| `rebind-key` | not an API operation | `/v1/{community}/owners/{handle}/rebind` | It retires a Member's Ed25519 keys. That is identity. |
| `suspect-after` | not an API operation | `/v1/{community}/owners/{handle}/suspect-after` | It marks a Member's file versions as suspect. That is custody of files, below the Artifact level. |
| `purge` | not an API operation | `/v1/{community}/files/{id}/v/{n}/purge` | It deletes stored bytes. An Artifact is immutable, so the Artifact-level API offers nothing that removes content. |
| `export`, `import` | not an API operation | `/v1/{community}/export`, `/v1/communities/import` | They move a whole community as a tar of files. The API sits above that. |
| `port` | not an API operation | `/v1/{community}/port-ndex` | Server-to-server migration of files. |
| `data <command>` | not an API operation | `/v1` directly | It is the file-level CLI by design. |
| `gen-api-key <username> <role>` (new) | write | `createApiKey` | |
| `list-api-keys` (new) | read | `listApiKeys` | |
| `revoke-api-key <key id>` (new) | write | `revokeApiKey` | |

The "not an API operation" commands fall into three groups. Local session state: `use`,
`serve`. Identity, guarded by Ed25519 keys made on their owners' machines: `setup`,
`bootstrap`, `admin-config`, `roster add|remove`, `invite`, `rebind-key`. Custody of files
below the Artifact level: `suspect-after`, `purge`, `export`, `import`, `port`, `data`.
Each already has its `/v1` route. Copying it into this API would put a second door on the
same identity or the same bytes.

## 4. Roles

### 4.1 The three roles

An API key holds exactly **one** role. There are three, and that is the whole set. Each
role holds everything the one before it holds.

| Role | Allows |
|---|---|
| `non-member` | every read of the record: Artifacts, views, Members, the record stream |
| `member` | everything `non-member` has, plus publishing as its Member and reading its own submissions, replies and their streams |
| `admin` | everything `member` has, plus every submission and reply, and the gate's operations: passes, verify and rebuild |

- **`non-member`** is for an application or a person outside the roster that shows the
  record. It reads and does nothing else. The data server already has this precedent in
  read keys (`sdr_…`) and public collections. A `non-member` key names an application, not
  a Member, so a leaked one can publish nothing.
- **`member`** is a Member on the roster. It publishes as that Member and sees its own
  traffic with the gate.
- **`admin`** is the server's admin. It holds the gate's operations: deciding submissions
  belongs to the admin, as `/symposium gate` does today. `promote` is admin-only on `/v1`,
  and the profile keeps the party that sets goals apart from the party that decides
  publication.

Provisioning API keys sits outside the three roles. It takes the server admin's Ed25519
token (§5.5), so no API key of any role can read or make another key.

Anonymous access is a separate case from the roles. When a community's `record`
collection is public on the data server, every record read also answers with no
credential. The operation says so in `x-anonymous`, and its `security` includes `{}`. This
is the API's version of a public collection.

The roles here belong to API keys. They are a different thing from the **publishing
roles** in `tools/roles/` (`researcher`, `analyst`, …). Those are limits a Member sets on
itself, and `submitArtifact` applies them through `role=` as `--role` does.

### 4.2 Endpoint × role

`tests/api/test_openapi.py` checks this table against `x-roles` in the contract.

| Operation | Method and path | non-member | member | admin |
|---|---|---|---|---|
| getRecord | GET /{community}/record | ✓ | ✓ | ✓ |
| listArtifacts | GET /{community}/artifacts | ✓ | ✓ | ✓ |
| getArtifact | GET /{community}/artifacts/{name} | ✓ | ✓ | ✓ |
| getArtifactProperty | GET /{community}/artifacts/{name}/properties/{property} | ✓ | ✓ | ✓ |
| listObjects | GET /{community}/artifacts/{name}/objects | ✓ | ✓ | ✓ |
| getObject | GET /{community}/artifacts/{name}/objects/{object} | ✓ | ✓ | ✓ |
| getObjectProperty | GET /{community}/artifacts/{name}/objects/{object}/properties/{property} | ✓ | ✓ | ✓ |
| listRelationships | GET /{community}/artifacts/{name}/relationships | ✓ | ✓ | ✓ |
| listCitedBy | GET /{community}/artifacts/{name}/cited-by | ✓ | ✓ | ✓ |
| listSupersession | GET /{community}/artifacts/{name}/supersession | ✓ | ✓ | ✓ |
| listFindings | GET /{community}/artifacts/{name}/findings | ✓ | ✓ | ✓ |
| getClaimGraph | GET /{community}/artifacts/{name}/claim-graph | ✓ | ✓ | ✓ |
| getEvidence | GET /{community}/artifacts/{name}/evidence | ✓ | ✓ | ✓ |
| getInternalGraph | GET /{community}/artifacts/{name}/internal-graph | ✓ | ✓ | ✓ |
| listGroundedSpans | GET /{community}/artifacts/{name}/grounded-spans | ✓ | ✓ | ✓ |
| resolveAddress | GET /{community}/resolve | ✓ | ✓ | ✓ |
| getOverview | GET /{community}/overview | ✓ | ✓ | ✓ |
| listMembers | GET /{community}/members | ✓ | ✓ | ✓ |
| getMember | GET /{community}/members/{handle} | ✓ | ✓ | ✓ |
| listMemberArtifacts | GET /{community}/members/{handle}/artifacts | ✓ | ✓ | ✓ |
| listMemberMessages | GET /{community}/members/{handle}/messages | ✓ | ✓ | ✓ |
| getMe | GET /{community}/me | ✓ | ✓ | ✓ |
| streamRecord | GET /{community}/streams/record | ✓ | ✓ | ✓ |
| listPublishRoles | GET /{community}/publish-roles | | ✓ | ✓ |
| checkSubmission | POST /{community}/submissions/check | | ✓ | ✓ |
| submitArtifact | POST /{community}/submissions | | ✓ | ✓ |
| listSubmissions | GET /{community}/submissions | | ✓ own | ✓ all |
| getSubmission | GET /{community}/submissions/{submission} | | ✓ own | ✓ all |
| listReplies | GET /{community}/replies | | ✓ own | ✓ all |
| getReply | GET /{community}/replies/{reply} | | ✓ own | ✓ all |
| streamSubmissions | GET /{community}/streams/submissions | | ✓ own | ✓ all |
| streamReplies | GET /{community}/streams/replies | | ✓ own | ✓ all |
| runGatePass | POST /{community}/gate/passes | | | ✓ |
| verifyGate | GET /{community}/gate/verify | | | ✓ |
| rebuildGate | POST /{community}/gate/rebuild | | | ✓ |
| listApiKeys | GET /admin/api-keys | | | ✓ token |
| createApiKey | POST /admin/api-keys | | | ✓ token |
| getApiKey | GET /admin/api-keys/{key_id} | | | ✓ token |
| revokeApiKey | DELETE /admin/api-keys/{key_id} | | | ✓ token |

"own" means rows about the key's Member: its submissions, and the replies addressed to it.
"token" means the server admin's Ed25519 token alone (`adminToken`). An API key of any role or
scope is refused there. A key scoped to one community would otherwise read every decrypted
key on the server, including the server-wide admin's.

## 5. API keys

### 5.1 Format and presentation

A key is `sak_` followed by the base64url of 32 random bytes (43 characters). It is sent as
`Authorization: Bearer sak_…`. The data server already tells credentials apart by prefix
(`sdr_` is a read key, and anything else is a JWT), so `sak_` joins that scheme. The
contract declares it as the `apiKey` security scheme.

### 5.2 The table

A new Alembic migration adds this table to the data server's PostgreSQL. It follows the
style of `read_keys` and `invites`.

```sql
CREATE TABLE api_keys (
    id          uuid PRIMARY KEY,
    hash        text NOT NULL UNIQUE,        -- hex SHA-256 of the whole key; the lookup
    ciphertext  bytea,                       -- AES-256-GCM of the key; NULL once revoked
    nonce       bytea,                       -- the 12-byte GCM nonce; NULL once revoked
    enc_kid     text,                        -- which encryption key sealed it
    username    text NOT NULL,
    role        text NOT NULL CHECK (role IN ('non-member', 'member', 'admin')),
    admin_kid   text,                        -- admin keys: the admin_keys.kid active at creation
    community   text,                        -- the scope; NULL means the whole server
    label       text,
    created_by  text NOT NULL,
    created     timestamptz NOT NULL,
    expires     timestamptz,                 -- NULL lasts until revoked
    revoked     timestamptz,
    revoked_by  text,
    last_used   timestamptz,
    uses        bigint NOT NULL DEFAULT 0,
    CHECK (community IS NOT NULL OR role = 'admin'),
    CHECK ((role = 'admin') = (admin_kid IS NOT NULL))
);
CREATE INDEX api_keys_scope ON api_keys (community, username);
```

`export` leaves the table out, as it already does with invites. A key is a credential for
one server, so it does not travel with a community.

### 5.3 Encryption at rest

The admin must be able to read a key back, so a key is stored **retrievably**, and **never
in plain text**:

- **Authentication** computes SHA-256 of the presented key and looks up `hash`. It decrypts
  nothing. A 256-bit random secret needs no slow hash, which is the same reasoning the
  server already applies to read keys.
- **The admin's listing** decrypts `ciphertext` with AES-256-GCM, from `cryptography`, which
  is already a dependency of the service. The associated data is `id ‖ username ‖
  community`, so a ciphertext copied onto another row fails to decrypt.
- **The secret** is 32 random bytes in `API_KEY_ENC_KEY_FILE`, by default
  `/apps/data/config/api_key_enc.key`, mode 0600. `docker/scripts/start.sh` generates it on
  first boot beside `token_ed25519.pem` and writes its path into `service.env`, which is
  where the server keeps all its other secrets. On Kubernetes it lives on the same `/apps`
  volume. A database dump alone reveals no key.
- **Rotation**: `enc_kid` names the key that sealed each row. A new file becomes the key for
  new rows, and a one-off re-seal moves old rows over.
- **Revocation** erases `ciphertext` and `nonce`, as the server already erases a used
  invite's secret.

This is stricter than invites, which `/v1` keeps in plain text.

### 5.4 Username, the roster and the admin binding

Every check below runs at creation **and on every request**, so a key loses its standing
the moment the thing it stands on changes.

| Role | `username` must be | Checked on every request |
|---|---|---|
| `member` | a handle on the scope community's roster that has **registered** (an `owners` row) | the handle is still on the roster and registered |
| `admin` | the server's admin handle | `admin_kid` is still an active row of `admin_keys`, and its handle is still the server's admin |
| `non-member` | a label for the application, matching no handle on the roster | the label still matches no handle on the roster |

A key that publishes must publish as a Member, because `published_by` is permanent
attribution. `submitArtifact` refuses a body whose `published_by` is anything other than
`@<username>`, or whose `name` does not carry the `<username>_` prefix.

- **A Member leaves the roster:** its `member` keys stop authenticating at once. They stay
  listed until the admin revokes them.
- **The admin rebinds its key** (a new admin public key placed on the server, after a
  compromise or a rotation): the old `admin_keys` row is retired, so every `admin` API key
  bound to it stops authenticating at once. The server also revokes those keys at startup,
  when it retires the old admin key, which erases their values. The admin issues new ones
  with the new token.
- **A handle joins the roster** with the same name as a `non-member` key's label: the key
  stops authenticating, so a label can never be mistaken for a Member.

### 5.5 Life cycle

All four key operations take the server admin's Ed25519 token and nothing else. An API
key, whatever its role or scope, can read, make or revoke no key.

Keys move as files, never through a terminal or a chat, because the repository's rule is
that a credential pasted into a transcript has been disclosed (`AGENTS.md`). So both
commands that see key values write them to a file and print only where it is.

1. **`/symposium gen-api-key <username> <role> [--community <c> | --server]
   [--expires-days N] [--label …]`** calls `createApiKey` with the admin's Ed25519 token.
   It writes the key to `~/.symposium/admin/api-keys/<id>.key`, mode 0600, and prints the
   id, the username, the role and that path. The default scope is the session's community.
2. **`/symposium list-api-keys [--community <c>]`** calls `listApiKeys` with the same token.
   It writes every key, with its username, its value (decrypted), its role, its scope, its
   creation, expiry and revocation, and its last use, to
   `~/.symposium/admin/api-keys/list-<timestamp>.json`, mode 0600. It prints each key's id,
   username, role and state, and the file's path. This follows the precedent of
   `GET /v1/{community}/invites`, which hands pending invites back to the admin. A revoked
   key shows `key: null`.
3. The admin hands the key file to its user out of band, as invite files already move.
4. Each request updates `last_used` and `uses`.
5. **`/symposium revoke-api-key <key id>`** calls `revokeApiKey`. The key stops working at
   once, its value is erased, and its row stays as a record of who held it.
6. A key past `expires` fails with 401. A janitor erases its value on the same schedule that
   `forget_expired_invites` uses.

## 6. Paging, freshness and streams

### 6.1 Paging

There is one convention:

- **Request:** `cursor` (opaque base64url, at most 256 characters) and `limit` (1–1000,
  default 100), the same bounds as `changes` on `/v1` (`MAX_PAGE = 1000`).
- **Response:** `items` and `next`. `next` is the cursor of the following page, or `null`
  on the last page. Every record page also carries `position`.
- **Order:** each listing states its order. The default is the record's `created` order,
  ascending.

A cursor wraps the same `seq` that `/v1`'s `since` takes, so a page boundary in the API is
a page boundary in the feed. The API fixes a quirk of `/v1`: there, `more` can be true while
a filtered page comes back empty. The API keeps reading until the page is full or the feed
ends, so `next: null` always means the end. A cursor stays valid for the life of the record.
A cursor the server did not issue answers 400.

The contract marks every listing that grows with the record as paged. An endpoint that
answers one bounded thing (one Argument's claim graph, one Artifact's internal graph, the
charter list, a verify report) says why in `x-bounded`, and the test checks that one of the
two holds for each operation.

### 6.2 Freshness

Every read response carries `position`, `{cursor, seq, created, as_of}`. These are the
index's place in the `record` feed, the `created` of the newest Artifact it reflects, and
when the server read it. A client compares two `position`s to see which is newer. It can
also open `streamRecord` to be told. This removes the record browser's "a member who has
not synced sees an older record" problem: there is one index on the one server, and every
answer says how current it is.

### 6.3 Streams

Server-Sent Events on three streams, each `text/event-stream`:

| Stream | Events | Parity with |
|---|---|---|
| `streamRecord` | `artifact` (an `ArtifactSummary`), `heartbeat` | `sync --watch` |
| `streamSubmissions` | `submission.received`, `submission.accepted`, `submission.rejected`, `submission.deferred`, `submission.skipped` (a `SubmissionResource`), `heartbeat` | `gate --watch` |
| `streamReplies` | `reply` (a `ReplyResource`), `heartbeat` | `sync --watch`'s reply lines |

- Each event's `id` is a cursor. A client that reconnects with `Last-Event-ID` resumes
  right after the last event it saw, so it misses nothing. A stream opened without one
  starts at the present.
- A `heartbeat` every 30 seconds carries `position`, so a quiet stream still proves it is
  live.
- **The key is re-checked at every event and every heartbeat**, by the same checks a
  request runs (§5.4). A stream whose key is revoked, expires, or loses its roster entry or
  its admin binding closes within 30 seconds. Revocation reaches an open stream as surely
  as a new request.
- The server keeps nothing per client: the cursor holds the state. Any replica can serve a
  reconnect. PostgreSQL `LISTEN/NOTIFY` on promote and inbox writes wakes the waiting
  streams.

## 7. Publishing keeps the gate's guarantees

| Guarantee | How the API keeps it |
|---|---|
| Nothing enters the record without the gate | `submitArtifact` writes only to `inbox`, as `publish.py` does: the file `{name}@{when}`, metadata `{"symposium_submission": true}`, `created_by` the key's Member. The API never writes to `record`. Only `runGatePass` promotes. |
| Every check `publish` makes | `checkSubmission` and `submitArtifact` run what `publish.py` runs, in its order: the naming rule (`<username>_` prefix); the publishing role's `may_publish`; its `may_import` for an Artifact carrying `import_method`; the 250 KB limit on embedded payload (`EMBED_REFUSE`); then `tools/validate.py`, the validator the gate runs, against the record as it stands. Any refusal answers 422 with every finding. Nothing is stored. |
| Serial `created` order | One Artifact per call. `created` must be null, and the gate stamps it at promote. The gate's ordering (`order_submissions`) runs unchanged in `runGatePass`. |
| Attribution | `published_by` must be `@<username>` and `name` must carry its prefix, so the gate's own check (the inbox name prefix is the submitter's handle, and the submitter is on the roster) passes for the same reason it passes today. |
| One decision per submission | This holds with any number of gates running, the API's and the skill's together. The storage enforces it: a promote writes `record/<name>` and a reply writes `inbox/<admin>_REPLY_<item>`, and the data server refuses a second file of either name with 409. The first gate to decide wins; a second sees 409 and reads the decision as made. `runGatePass` also takes a PostgreSQL advisory lock per community, so two server passes do no duplicate work. |
| Replies to rejections | The gate's reply is the same `NonGroundable` in `inbox`, readable by its recipient. `listReplies`, `getReply` and `streamReplies` expose it. A Member answers a rejection by submitting a corrected Artifact, which is the same path as today. |
| Publishing roles are self-imposed | `role=` applies the charter's limits before submitting, by a name the server looks up in the charters it ships. The gate ignores roles, as it does today. |

**Where each submission state comes from.** The server learns every state from what it
stores or computes, so a submission reads the same state whichever gate is running.

| State | Learned from |
|---|---|
| `pending` | an `inbox` item marked `symposium_submission`, with no record version or reply naming it |
| `skipped` | the gate's own rule, applied by the server when it reads the item: the inbox name before `@` is the artifact's name prefixed with its submitter's handle, and the submitter is on the roster. An item failing either is `skipped`, as the gate would set it aside |
| `deferred` | a `runGatePass` that ordered the submission behind an Analysis still missing from the record. The pass records it in the index. A deferral by the skill's client-side gate stays in its local `.gate_state.json`, so the submission reads `pending` until it is decided |
| `accepted` | a `record` version whose `symposium_submission_citation` names it |
| `rejected` | an `inbox` reply whose `symposium_submission_citation` names it |

## 8. Coexistence with today's access

Nothing that exists today changes for the skill or the CLI.

| Credential | Where it works | Changes |
|---|---|---|
| Member Ed25519 token (JWT) | `/v1` | none |
| Server admin Ed25519 token (JWT) | `/v1`; also the API's gate operations, and the API-key operations, which accept it alone (`adminToken`) | it is newly accepted on those API operations |
| Read key `sdr_…` | `/v1` reads of its collection | none; the API does not accept it |
| Public collection | anonymous `/v1` reads | a public `record` also opens the API's record reads anonymously |
| API key `sak_…` | `/api/v1` only | new; `/v1` refuses it |

The API is a new path prefix, `/api/v1`, served by the same process as `/v1` (§10). `/v1`
keeps every route, body and rule. A member's API key goes through the same roster and grant
checks a member token would. It cannot read another Member's inbox files, because the
`inbox` visibility rule (the first writer, the admin, and `metadata.recipients`) applies to
the key's Member.

## 9. Errors, versioning and limits

- **Errors.** Every error uses the `Error` body: `{detail, code, findings?}`. `detail` is
  the sentence `/v1` writes, and `code` is stable for programs. FastAPI's default 422
  validation body is mapped onto it, so there is exactly one error shape.
- **Versioning.** The major version is in the path: `/api/v1`. Additive changes (a new
  endpoint, a new optional field, a new event type) stay in v1. A breaking change opens
  `/api/v2` beside it. `info.version` tracks the contract.
- **Limits.**
  - A request body is at most 8 MiB, which answers 413. `/v1` sets none.
  - An Artifact's embedded payload is at most 250 KB, as `publish.py` refuses today, which
    answers 422 with a finding. The validator reviews any payload over 50 KB.
  - The per-Member quota, `SYMPOSIUM_DATA_QUOTA_BYTES`, applies to submissions as it does
    to `/v1` writes.
  - A page holds at most 1000 items, and a cursor is at most 256 characters. Responses are
    otherwise unbounded, like `/v1`.
  - `role=` is a name of at most 40 lower-case characters, looked up in the shipped charters.
  - There are no rate limits, matching `/v1`. A deployment that needs them puts them in its
    ingress.

## 10. How the code is arranged

The API's code and the rules it shares with the skill each get their own package, so every
dependency points one way: toward the rules, and from the API toward storage. A small
composition module outside both services assembles the running server, so no package
imports one that imports it back.

| Package | Holds | Imported by |
|---|---|---|
| `symposium_rules` (new, standard library only, Python 3.9+) | the validator (today `tools/validate.py`), the gate's ordering and skip rules (today in `tools/gate.py`), the publish checks and the charter loader (today in `tools/publish.py`), and the charters in `tools/roles/` | the skill's `tools/`, the API |
| `symposium_api` (new) | the `/api/v1` routes, the index, the streams and the gate pass, as a FastAPI router built from a records layer it is handed | `symposium_server` |
| `symposium_data` (today) | storage: `/v1`, records, identity | `symposium_api`, through its records layer; `symposium_server` |
| `symposium_server` (new, a few lines) | the composition root: it builds `symposium_data`'s app and records layer, builds `symposium_api`'s router from that records layer, and mounts the router at `/api/v1`. uvicorn starts this module | nothing |

`tools/validate.py`, `tools/gate.py` and `tools/publish.py` become thin callers of
`symposium_rules`, with the same behaviour and the same command lines. The skill bundle and
the data server image both ship the one package, so the validator the API runs is the
validator the gate runs, byte for byte. Storage imports none of the rules and none of the
API, and the rules import none of the storage. Only `symposium_server` sees all three.

## 11. Where the API server runs

### 11.1 The decision

| Question | Answer |
|---|---|
| Which image | `ndexbio/symposium-data`, the data server's own image. The API ships in the same release. |
| Which process | the `data-api` supervisord program, the one uvicorn process that serves `/v1` today. It starts `symposium_server:app`, which mounts `/api/v1` beside `/v1`. |
| Which HTTP server | uvicorn, the ASGI server the image already runs, with `--proxy-headers` as today. |
| Which port | 8080, the port the image already exposes. `/v1` and `/api/v1` share it. |
| Which language and framework | Python 3.11 and FastAPI, the data server's own. |
| Which volume | `/apps`, the image's one persistent volume. The API keeps its index in the same PostgreSQL. |

### 11.2 Why the data server image

- **The API reads PostgreSQL directly.** The index, the `api_keys` table, the roster and
  the feeds all live in the image's PostgreSQL, which listens on `127.0.0.1` alone. A process
  in the image reaches it with no new network exposure and no new credential. A separate
  image would need PostgreSQL opened to the network, or every read relayed through `/v1`
  over HTTP. The second doubles the work of every traversal and puts a token exchange in
  front of every query.
- **Streams wake on the same database.** `LISTEN/NOTIFY` on promote and inbox writes needs
  a connection to that PostgreSQL. Inside the image it is one more pooled connection.
- **The secrets are already there.** `API_KEY_ENC_KEY_FILE` sits beside
  `token_ed25519.pem` in `/apps/data/config`, generated by the same `start.sh` first-boot
  phase. The admin public key that `adminToken` checks against is already loaded by the
  data server.
- **One deployment, one release.** An operator runs one `docker run`, or one Kubernetes
  Deployment, as `skills/symposium/SKILL.md` already teaches. The API's version moves with
  the storage it reads, so the two can never be deployed out of step.

### 11.3 Why one uvicorn process, on the same port

The data server is FastAPI on uvicorn already. The API is FastAPI too, so `symposium_server`
mounts its router on the same app, and one process serves both prefixes.

- `docker run -p 127.0.0.1:8790:8080`, the Kubernetes Service on 8080, and the Ingress on
  `/` all keep their shape. `/api/v1` arrives through them with no change.
- The skill's `data-server-url` already names the server. An application uses the same URL
  with `/api/v1` after it.
- A second uvicorn on another port would need a second Service port, a second Ingress rule
  and a second health check, for no isolation the measures in §11.5 do not already give.

### 11.4 Why Python, and a Java server ruled out

The API runs the gate's own checks: the validator, the ordering and skip rules, and the
publish checks, all in `symposium_rules` (§10). They are Python, and so are the gate, the
skill and the data server. A Java server would need a second implementation of the
validator. Two validators drift, and the day they disagree, `checkSubmission` passes an
Artifact the gate rejects. That breaks the promise that a pass means the gate accepts.
Java would also add a JVM to an image that holds none today. A Go or Node server fails the
same test for the same reason.

### 11.5 Running it

- **Start flag.** `start.sh` gains `--symposium-api`, on by default with the others. Without
  it, `data-api` starts `symposium_data.app:app` as today, and `/api/v1` answers 404. An
  operator who wants `/v1` alone runs `start.sh --data-api --postgres --seaweed`.
- **CPU work leaves the event loop.** Validation, the claim graph and the overview run in
  FastAPI's thread pool, so a long validation holds no stream and no `/v1` request.
- **Streams are capped.** At most 8 open streams per API key, and at most 500 per
  process, set by `SYMPOSIUM_API_MAX_STREAMS`. Past either, a new stream answers 429 with
  the `Error` body. Each stream holds one coroutine and wakes on a shared `LISTEN`
  connection, so 500 cost little memory.
- **Workers.** One uvicorn worker by default, as today. `SYMPOSIUM_DATA_WORKERS` raises it.
  Every worker holds nothing between requests (§6.3), so any worker serves any request or
  reconnect.
- **The ingress.** SSE needs two settings on a proxy in front of the server: response
  buffering off, and a read timeout longer than the 30-second heartbeat. The API sends
  `X-Accel-Buffering: no` on every stream, which nginx honours. The commented Ingress in
  `data-server/docker/k8s-data-deployment.yml` gains
  `nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"` and
  `nginx.ingress.kubernetes.io/proxy-buffering: "off"`.
- **TLS** stays where it is today: the deployment's ingress or proxy terminates it.
- **Health.** `GET /v1/status` stays the health check. It reports the API's index position
  beside Postgres and S3 once the API is on.
