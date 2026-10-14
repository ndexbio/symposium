# Symposium API: design notes

The Symposium API's record routes let any application read a community record, follow it as
it changes, and publish to it through the gate as a Member. They speak the specification's
model (Artifacts, Objects, properties, relationships, Members and addresses). They share
`/v1` with the data server's own routes for collections and files, and every route of `/v1`
takes one credential, an API key, and leaves what a key may read and write to the
collections it touches (§3, §7).

These notes go with [`openapi.yaml`](openapi.yaml), the OpenAPI 3.0.3 document. The YAML is
the contract. These notes say why it has the shape it has.

## 0. Where this lives

| File | Holds |
|---|---|
| `api/openapi.yaml` | the contract: every endpoint, its schemas, its roles and its errors |
| `api/DESIGN.md` | these notes |
| `api/redocly.yaml` | the linter's ruleset, `recommended-strict` |
| `tests/api/test_openapi.py` | checks the contract against the rules below and against these notes' tables |
| `tests/api/test_api_live.py` | runs the data-server container and checks every operation, every role and the keys live |
| `data-server/service/codegen/` | the generator script and its templates |
| `data-server/service/symposium_api/generated/` | the routers, models and service interface generated from the contract; never edited by hand |
| `data-server/service/symposium_api/`, `symposium_server/` | the hand-written implementation and the composition root (§9) |
| `tools/symposium_rules/` | the rules the gate and the API share (§9) |

The API gets its own top-level directory because it is a third face of Symposium. It sits
beside `spec/`, the model, and `data-server/`, the storage. The data server's process
serves it, from its own package. §9 lays out how the code depends on what, and §10
settles where the server runs.

Lint it with:

```bash
npx --yes @redocly/cli@2.59.0 lint --config api/redocly.yaml api/openapi.yaml
```

`make test` runs it, then `tests/api/`, and CI runs `make test`.

The contract describes every route of `/v1`. The record's routes, the operations it marks
`x-generated: true`, are generated from it, never written by hand: `fastapi-code-generator`
writes their routers and service interface from the templates in
`data-server/service/codegen/templates/`, and `datamodel-code-generator` writes the Pydantic
models of the schemas they reach. The other routes are hand-written in
`data-server/service/symposium_data/app.py`; each depends on `authorize` for its own
operation, so the rule the contract states is the rule it applies, and
`tests/api/test_openapi.py` checks that the contract and the server list the same routes.
After a change to `api/openapi.yaml`, regenerate and commit:

```bash
uv run --project data-server/service python data-server/service/codegen/generate.py
```

`make lint` regenerates into a scratch directory and fails if the committed code differs.

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
| Content (§1.8.1) | an Object, listed with `?type=Content` | `…/objects?type=Content` |

The Artifact types the specification defines, and the profile's community types, all use
the one Artifact resource. Their type-specific properties are documented on
`ArtifactHeader` and `RecordObject`. Each type also has its own traversals:

| Type | What the API adds for it |
|---|---|
| Argument (§2.2): Assertion, Ground, Assumption; verdict, rationale, purpose | its Objects and relationships under the Argument; its Grounds show up in the cited Artifact's `cited-by?via=ground` |
| Argument, extracted (`extracted_from`) | `cited-by?via=extracted_from` on the source |
| Non-Ground citation (§2.2.5) | `cited-by?via=prose` on the cited Artifact |
| Grounding on another Argument's primary Assertion | `cited-by?via=testimony` |
| Data (§2.3), ScientificPublication (§2.4), Model (§2.6) | their Objects and relationships; `cited-by?via=ground` for the Grounds that cite their content, `text_span` quotes included |
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
  header properties, read as they are. `published_by` is permanent. That is why §4.4 ties
  a publishing key to one Member.
- **Immutability.** No operation changes or deletes a recorded Artifact. The only writes
  are a submission into `inbox` and API keys.

### 1.3 The index

The traversals need facts that no single Artifact holds: who cites whom, what supersedes
what, and findings. The server keeps a **derived index** of
these facts in its PostgreSQL. It folds in each Artifact the moment `record` gains it. The
index is a cache of the record and is never the source of truth. The server rebuilds it
from the `record` feed at startup, in the background, and `GET /v1/status` reports
`api_index.behind`: how many record versions it has yet to fold in, across every community.
The figure is server-wide and names no community, because `/v1/status` answers anyone. Every read answers from the
index and states the index's `position` (§5.2).

Each Artifact's `accepted` findings are the validator's verdict against the Artifacts before
it, with the Members as the roster stands when the index first folds that Artifact in. On a
server whose index is built over a record that already exists, that roster is today's, so an
older Artifact's `accepted` findings may differ from what its gate saw on a Member address the
roster has since changed.

A version purged on `/v1` leaves every read of the index: its Artifact answers 404, and its
citations leave `cited-by` and supersession.

### 1.4 Canonical URLs

Every resource body carries `url`: an absolute URL on the data server, under
`/v1/{community}`. It is the same whichever host or application asks. This removes the
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

### 1.5 Changes to the contract while building it

Building the server against `api/openapi.yaml` changed these meanings, each for the reason
given:

| Change | Reason |
|---|---|
| OpenAPI 3.1.0 to 3.0.3, the same meaning in 3.0 forms | the code generators support 3.0 fully |
| `ArtifactHeader.created` is nullable; `SubmittedHeader` is gone | its `allOf` override contradicted `created`; a submission sends null and `checkSubmission` and `submitArtifact` refuse any other value, while every record Artifact carries the gate's stamp |
| `ArtifactHeader`, `RecordObject` and `Relationship` take any extra property | the generated models keep an Artifact's own properties only this way; an extra property takes any JSON value, as the gate's validator accepts it |
| `PropertyValue` adds `integer`, under `anyOf` | a submitted integer stays an integer |
| path, query and header parameters state their string constraints inline | FastAPI takes a parameter only as a plain type |
| a page's `next` states the cursor's constraints inline | in 3.0, `nullable` beside a non-nullable `$ref` admits no null |
| `SubmissionCheck.role` is gone | it belonged to the publishing roles, which stay in the skill |
| `RecordState.counts.findings` counts each Artifact's `accepted` findings | counting against the whole record would run the validator over every Artifact on each call |
| `getOpenApiYaml` and `getOpenApiJson` added | the API serves its own contract to any caller |
| `streamRecord` and `streamSubmissions` answer 400 | `Last-Event-ID` is a cursor, and a cursor this server never issued answers 400 everywhere |
| the `admin` role, the `adminToken` scheme and the four `/admin/api-keys` operations are gone; every key belongs to one community | the API authenticates API keys alone and exposes no admin operation; keys are issued on the data server's `/v1` (§4.5), and a key acts only in its own community |
| a `member` key carries its Member's handle, set from the Member's own session when it creates the key; `Me` answers `handle` and `label` | a submission is attributed to the Member who made the key, never to one the admin named |
| `getArtifactContent` added; `links.content` names it | an Artifact's stored bytes are reachable with the same API key. It answers those bytes untouched, so it carries no `position`; `x-stored` marks it |
| one API: the record routes moved from `/api/v1` to `/v1`, beside the data server's own | two prefixes took two credentials and checked access two ways; one prefix takes one API key, and the collections decide access (§3, §7) |
| the `admin` role returns, for the admin's session key; `x-session` added; `x-anonymous` is `always` or `public`; `Me` adds `kind`, `kid`, `suspect_after` and `grants` | an Ed25519 sign-in answers a session key, the admin's included, so the admin reads the record like any key; `getMe` replaces the data server's `whoami` |

## 2. The skill's commands → endpoints

These skill commands have an equivalent in the API. Each row names the operation in
`openapi.yaml` that does the command's work for a REST client.

| Command | Method and path | Operations |
|---|---|---|
| `publish <artifact.json>` | `POST /{community}/submissions` | `submitArtifact` |
| `validate <artifact.json>` | `POST /{community}/submissions/check` | `checkSubmission` |
| `sync` | `GET /{community}/artifacts?cursor=…`, `GET /{community}/submissions?status=rejected` | `listArtifacts`, `listSubmissions` |
| `sync --watch` | `GET /{community}/streams/record`, `GET /{community}/streams/submissions` | `streamRecord`, `streamSubmissions` |
| `roster list` | `GET /{community}/members` | `listMembers` |

The three key commands, `gen-api-key`, `list-api-keys` and `revoke-api-key`, call the data
server's own `/v1/{community}/api-keys` routes (§4.5), which take a session key.

## 3. Roles

### 3.1 Keys, roles and collections

Every request carries one API key, or none. A key holds exactly **one** role and belongs to
exactly **one** community; the admin's session key works in every community. A key used on
another community answers 403.

| Role | Who holds it | Allows |
|---|---|---|
| `non-member` | an application, with a key a collection's owner issued for it | every read of the record, while it may read `record` |
| `member` | a Member: its session key, or a key it issued for itself | everything `non-member` has, plus publishing as its Member and reading its own submissions, with the gate's decision and reply on each, and their stream |
| `admin` | the server admin's session | every read of the record |

The role is the first gate: `x-roles` names the roles that may call an operation at all. The
collection is the second: a request succeeds when its caller may use the collection it
touches.

- **Record reads** take read access to `record`: its owner (the admin), a Member with a
  `read` grant (every Member starts with one), a `non-member` key granted `read`, or anyone
  while `record` is public. A grant withdrawn on `/v1` is felt on the next request and by an
  open stream (§5.3).
- **Publishing** writes into `inbox`, so it takes the Member's `write` grant there, which every
  Member starts with. A `non-member` key never writes.
- **Submissions** are read by the Member who made them, with the gate's decision on each.

The keys:

- **A session key** answers an Ed25519 sign-in (`POST /v1/{community}/auth/token`, or
  `/v1/admin/token` for the admin) and lasts `SYMPOSIUM_SERVER_SESSION_TTL` seconds (default
  900). The skill's CLI signs in for one per command. Routes that change access, keys or the
  server take a session key (`x-session`), so a leaked issued key cannot widen what any key
  may do.
- **A `member` key** is one a Member issues **for itself**, with its session; a Member may
  hold several, each named by a label. It carries the Member's handle, and every operation
  that needs a Member takes it from the key: it publishes as that Member and sees that
  Member's own traffic with the gate. Nobody else, the admin included, can make a key that
  acts as a Member.
- **A `non-member` key** is one a Member or the admin issues for an application. It names no
  Member, so a leaked one can publish nothing, and it reads only the collections its
  owners grant it, `read` only.

Anonymous access needs no key: an operation that answers without one says so in
`x-anonymous`, and its `security` includes `{}`. `always` marks the contract itself,
`GET /v1/openapi.yaml` and `/v1/openapi.json`. `public` marks every record read, which
answers anonymously while the community's `record` collection is public.

### 3.2 Endpoint × role

`tests/api/test_openapi.py` checks this table against `x-roles` in the contract. The rows from
`getStatus` on are the hand-written routes, the ones that set a community up and its files.
Routes marked `x-session` in the contract also take a session key, and the collection a route
touches decides the rest (§3.1).

| Operation | Method and path | non-member | member | admin |
|---|---|---|---|---|
| getOpenApiYaml | GET /openapi.yaml | ✓ | ✓ | ✓ |
| getOpenApiJson | GET /openapi.json | ✓ | ✓ | ✓ |
| getRecord | GET /{community}/record | ✓ | ✓ | ✓ |
| listArtifacts | GET /{community}/artifacts | ✓ | ✓ | ✓ |
| getArtifact | GET /{community}/artifacts/{name} | ✓ | ✓ | ✓ |
| getArtifactContent | GET /{community}/artifacts/{name}/content | ✓ | ✓ | ✓ |
| getArtifactProperty | GET /{community}/artifacts/{name}/properties/{property} | ✓ | ✓ | ✓ |
| listObjects | GET /{community}/artifacts/{name}/objects | ✓ | ✓ | ✓ |
| getObject | GET /{community}/artifacts/{name}/objects/{object} | ✓ | ✓ | ✓ |
| getObjectProperty | GET /{community}/artifacts/{name}/objects/{object}/properties/{property} | ✓ | ✓ | ✓ |
| listRelationships | GET /{community}/artifacts/{name}/relationships | ✓ | ✓ | ✓ |
| listCitedBy | GET /{community}/artifacts/{name}/cited-by | ✓ | ✓ | ✓ |
| listSupersession | GET /{community}/artifacts/{name}/supersession | ✓ | ✓ | ✓ |
| listFindings | GET /{community}/artifacts/{name}/findings | ✓ | ✓ | ✓ |
| resolveAddress | GET /{community}/resolve | ✓ | ✓ | ✓ |
| listMembers | GET /{community}/members | ✓ | ✓ | ✓ |
| getMember | GET /{community}/members/{handle} | ✓ | ✓ | ✓ |
| listMemberArtifacts | GET /{community}/members/{handle}/artifacts | ✓ | ✓ | ✓ |
| listMemberMessages | GET /{community}/members/{handle}/messages | ✓ | ✓ | ✓ |
| getMe | GET /{community}/me | ✓ | ✓ | ✓ |
| streamRecord | GET /{community}/streams/record | ✓ | ✓ | ✓ |
| checkSubmission | POST /{community}/submissions/check |  | ✓ |  |
| submitArtifact | POST /{community}/submissions |  | ✓ |  |
| listSubmissions | GET /{community}/submissions |  | ✓ own |  |
| getSubmission | GET /{community}/submissions/{submission} |  | ✓ own |  |
| streamSubmissions | GET /{community}/streams/submissions |  | ✓ own |  |
| getStatus | GET /status | ✓ | ✓ | ✓ |
| adminChallenge | POST /admin/challenge | ✓ | ✓ | ✓ |
| adminSignIn | POST /admin/token | ✓ | ✓ | ✓ |
| listCommunities | GET /communities |  |  | ✓ |
| createCommunity | POST /communities |  |  | ✓ |
| importCommunity | POST /communities/import |  |  | ✓ |
| exportCommunity | GET /{community}/export |  |  | ✓ |
| startPortNdex | POST /{community}/port-ndex |  |  | ✓ |
| getPortNdex | GET /{community}/port-ndex/{port_id} |  |  | ✓ |
| challenge | POST /{community}/auth/challenge | ✓ | ✓ | ✓ |
| signIn | POST /{community}/auth/token | ✓ | ✓ | ✓ |
| register | POST /{community}/owners | ✓ | ✓ | ✓ |
| rotateKey | POST /{community}/owners/{handle}/keys |  | ✓ |  |
| rebindMember | POST /{community}/owners/{handle}/rebind |  |  | ✓ |
| setSuspectAfter | PUT /{community}/owners/{handle}/suspect-after |  |  | ✓ |
| listRoster | GET /{community}/roster |  | ✓ | ✓ |
| addMember | POST /{community}/roster/{handle} |  |  | ✓ |
| removeMember | DELETE /{community}/roster/{handle} |  |  | ✓ |
| listInvites | GET /{community}/invites |  |  | ✓ |
| createInvite | POST /{community}/invites |  |  | ✓ |
| listApiKeys | GET /{community}/api-keys |  | ✓ | ✓ |
| createApiKey | POST /{community}/api-keys |  | ✓ | ✓ |
| getApiKey | GET /{community}/api-keys/{key_id} |  | ✓ | ✓ |
| revokeApiKey | DELETE /{community}/api-keys/{key_id} |  | ✓ | ✓ |
| createCollection | POST /{community}/collections |  | ✓ | ✓ |
| setGrant | PUT /{community}/collections/{collection}/grants |  | ✓ | ✓ |
| setPublic | PUT /{community}/collections/{collection}/public |  | ✓ | ✓ |
| putFile | PUT /{community}/collections/{collection}/files/{name} |  | ✓ | ✓ |
| listFileVersions | GET /{community}/files/{file_id}/versions | ✓ | ✓ | ✓ |
| addFileVersion | POST /{community}/files/{file_id}/versions |  | ✓ | ✓ |
| deleteFile | DELETE /{community}/files/{file_id} |  | ✓ | ✓ |
| getFileContent | GET /{community}/files/{file_id}/v/{ref} | ✓ | ✓ | ✓ |
| statFileVersion | GET /{community}/files/{file_id}/v/{ref}/stat | ✓ | ✓ | ✓ |
| purgeVersion | POST /{community}/files/{file_id}/v/{n}/purge |  |  | ✓ |
| promoteVersion | POST /{community}/files/{file_id}/v/{n}/promote |  |  | ✓ |
| listChanges | GET /{community}/collections/{collection}/changes | ✓ | ✓ | ✓ |
| queryCollection | POST /{community}/collections/{collection}/query | ✓ | ✓ | ✓ |
| findFile | GET /{community}/collections/{collection}/find | ✓ | ✓ | ✓ |
| findByHash | GET /{community}/sha256/{sha} | ✓ | ✓ | ✓ |
| verifyCitation | GET /{community}/verify | ✓ | ✓ | ✓ |

"own" means rows about the key's Member: its submissions, and the replies addressed to it.

## 4. API keys

### 4.1 Format and presentation

A key is `sak_` followed by the base64url of 32 random bytes (43 characters): an opaque bearer
secret, handled like any API key. It is sent as `Authorization: Bearer sak_…`. The contract
declares it as the `apiKey` security scheme, the API's only one; any other bearer credential
answers 401. A key's row is its caller's identity.

### 4.2 The table

Alembic migration `0009` gives the data server's PostgreSQL this table, and lets a grant name
a key.

```sql
CREATE TABLE api_keys (
    id          uuid PRIMARY KEY,
    hash        text NOT NULL UNIQUE,      -- hex SHA-256 of the whole key; the lookup
    kind        text NOT NULL CHECK (kind IN ('session', 'issued')),
    role        text NOT NULL CHECK (role IN ('admin', 'member', 'non-member')),
    community   text,                      -- NULL for the admin's session alone
    handle      text,                      -- the Member, or the admin; NULL for non-member
    label       text,                      -- issued keys: its issuer's name for it
    ed25519_kid text,                      -- sessions: the Ed25519 key it was signed in with
    ciphertext  bytea,                     -- issued keys: AES-256-GCM of the key
    nonce       bytea,                     -- the 12-byte GCM nonce
    enc_kid     text,                      -- which encryption key sealed it
    created_by  text NOT NULL,             -- the issuer, or the one who signed in
    created     timestamptz NOT NULL DEFAULT now(),
    expires     timestamptz,               -- NULL: an issued key lasts until revoked
    revoked     timestamptz,
    revoked_by  text,
    last_used   timestamptz,               -- refreshed at most once a minute
    CHECK ((role = 'non-member') = (handle IS NULL)),
    CHECK (role <> 'admin' OR kind = 'session'),
    CHECK ((community IS NULL) = (role = 'admin')),
    CHECK ((kind = 'session') = (ed25519_kid IS NOT NULL)),
    CHECK ((kind = 'issued') = (label IS NOT NULL))
);
-- a label names one live issued key among its issuer's
CREATE UNIQUE INDEX api_keys_label ON api_keys (community, created_by, label)
    WHERE kind = 'issued' AND revoked IS NULL;

-- a grant names a roster Member, or a non-member key, which is granted `read` alone
ALTER TABLE grants ADD COLUMN api_key_id uuid REFERENCES api_keys (id) ON DELETE CASCADE;
ALTER TABLE grants ADD CHECK ((handle IS NULL) <> (api_key_id IS NULL));
ALTER TABLE grants ADD CHECK (api_key_id IS NULL OR perm = 'read');
```

`export` leaves keys out, and the grants made to them. A key is a credential for one server,
so it does not travel with a community.

### 4.3 Encryption at rest

An issued key's owner must be able to read it back, so it is stored **retrievably**, and
**never in plain text**:

- **Authentication** computes SHA-256 of the presented key and looks up `hash`. It decrypts
  nothing. A 256-bit random secret needs no slow hash.
- **The owner's listing** decrypts `ciphertext` with AES-256-GCM, from `cryptography`, which
  is already a dependency of the service. The associated data is `id ‖ handle ‖ label ‖
  community`, so a ciphertext copied onto another row fails to decrypt.
- **The secret** is 32 random bytes in `API_KEY_ENC_KEY_FILE`, by default
  `/apps/data/config/api_key_enc.key`, mode 0600. `docker/scripts/start.sh` generates it on
  first boot and writes its path into `service.env`, where the server keeps all its other
  secrets. On Kubernetes it lives on the same `/apps` volume. A database dump alone reveals
  no key.
- **Rotation**: `enc_kid` names the key that sealed each row. A new file becomes the key for
  new rows, and a one-off re-seal moves old rows over.
- **Revocation** erases `ciphertext` and `nonce`, as the server already erases a used
  invite's secret.
- **A session key** is never shown again, so it is stored as its hash alone.

### 4.4 Who a key acts as

A key's `role`, `handle` and community are set when it is made, never from a request body,
and they are the one source of the caller for every operation. These checks run at creation
**and on every request** (and at every stream beat), so a key loses its standing the moment
the thing it stands on changes:

| Key | At creation | On every request |
|---|---|---|
| a Member's session | a fresh challenge signed by one of the Member's active Ed25519 keys | that Ed25519 key is still active, and the Member is on the roster |
| `member` | the Member's own session, in this community, while it is on the roster and **registered** | `handle` is still on the roster and registered |
| `non-member` | a session of a registered Member, or the admin's | the key is live |
| the admin's session | a fresh challenge signed by the admin's key | the admin's key is still active |

A key that publishes must publish as a Member, because `published_by` is permanent
attribution. `submitArtifact` refuses a body whose `published_by` is anything other than
`@<handle>`, or whose `name` does not carry the `<handle>_` prefix.

- **A Member leaves the roster** (`DELETE /v1/{community}/roster/{handle}`): every key that
  acts as it, and every key it issued, is revoked in the same transaction
  (`revoked_by = 'roster-removal'`, values erased), so each stops at once and an open stream
  on one closes. The rows stay as the record of who held which key.
- **A Member rotates its key, or the admin rebinds it**: the sessions the old key signed in
  end. The Member's issued keys stop authenticating while it has no registered Ed25519 key,
  and work again once it registers the new one.
- A `non-member` key names no Member, so its label is only a name: a handle that later
  joins the roster under the same name changes nothing for it.

### 4.5 Life cycle

Keys are issued, listed and revoked on `/v1/{community}/api-keys`, community by community,
with a session key. Whoever issued a key owns it; the admin also owns every `non-member`
key.

| Route | With a Member's session | With the admin's session |
|---|---|---|
| `POST /v1/{community}/api-keys` `{label, role?, expires_days?}` | creates a `member` key bound to that Member, or with `role: non-member` a key for an application; 403 once it is off the roster | creates a `non-member` key |
| `GET /v1/{community}/api-keys` | the keys it issued, with their values | every issued key of the community: the `non-member` keys with their values, the Members' keys without |
| `GET /v1/{community}/api-keys/{key_id}` | one of the keys it issued | any key of the community, a Member's without its value |
| `DELETE /v1/{community}/api-keys/{key_id}` | revokes one of the keys it issued | revokes any `non-member` key; a Member's own key answers 404 |

Every route answers `Cache-Control: no-store` wherever it carries a key's value. A key of
another community, or one the caller may not see, answers 404; a label already on one of
the issuer's live keys answers 409.

A `non-member` key reads what its collections' owners grant it:
`PUT /v1/{community}/collections/{collection}/grants {api_key_id, perm: "read", granted}`,
with the owner's session. A `write` grant to a key answers 400.

Keys move as files, never through a terminal or a chat, because the repository's rule is
that a credential pasted into a transcript has been disclosed (`AGENTS.md`). So both
commands that see key values write them to a file and print only where it is.

1. **`/symposium gen-api-key <label> [--non-member] [--community <c>] [--expires-days N]`**,
   in a Member's session, creates one more of that Member's keys, or with `--non-member` a
   key for an application; in the admin's session, a key for an application. It writes the
   key to the session's `api-keys/<id>.key`, mode 0600, and prints the id, community, role,
   handle, label and that path.
2. **`/symposium data collection grant --collection <c> --api-key <id> --perm read`** gives an
   application key read on a collection the caller owns.
3. **`/symposium list-api-keys [--community <c>]`** writes the keys the caller issued (and,
   for the admin, the Members' keys without their values) to the session's
   `api-keys/list-<timestamp>.json`, mode 0600, and prints them without values. A revoked
   key shows `key: null`.
4. The key's owner hands the file to its application out of band, as invite files already
   move.
5. **`/symposium revoke-api-key <key id> [--community <c>]`** revokes a key its caller owns.
6. A key past `expires` fails with 401. The server erases an issued key's value at startup,
   before every listing and on every janitor pass, which also deletes ended sessions.

## 5. Paging, freshness and streams

### 5.1 Paging

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
answers one bounded thing (one key, or one Artifact's findings on a check) says why in `x-bounded`, and the test checks that one of the
two holds for each operation.

### 5.2 Freshness

Every read response carries `position`, `{cursor, seq, created, as_of}`. These are the
index's place in the `record` feed, the `created` of the newest Artifact it reflects, and
when the server read it. A client compares two `position`s to see which is newer. It can
also open `streamRecord` to be told. This removes the record browser's "a member who has
not synced sees an older record" problem: there is one index on the one server, and every
answer says how current it is.

### 5.3 Streams

Server-Sent Events on three streams, each `text/event-stream`:

| Stream | Events | Parity with |
|---|---|---|
| `streamRecord` | `artifact` (an `ArtifactSummary`), `heartbeat` | `sync --watch` |
| `streamSubmissions` | `submission.received`, `submission.skipped`, `submission.accepted`, `submission.rejected` (a `SubmissionResource`; a rejection carries the gate's reply), `heartbeat` | `sync --watch`'s reply lines |

- Each event's `id` is a cursor. A client that reconnects with `Last-Event-ID` resumes
  right after the last event it saw, so it misses nothing. A stream opened without one
  starts at the present.
- A `heartbeat` every 30 seconds carries `position`, so a quiet stream still proves it is
  live.
- **The key and its access are re-checked at every event and every heartbeat**, by the same
  checks a request runs (§3.1, §4.4). A stream whose key is revoked, expires, or loses its
  roster entry, or whose caller can no longer read the collection it follows (a withdrawn
  grant, a record made private), closes within 30 seconds. Revocation reaches an open stream
  as surely as a new request.
- The client's cursor holds the stream's position, and the server's one row per open
  stream (§10.5) lives in PostgreSQL, so no worker keeps a client's state in memory. Any
  worker can serve a reconnect. PostgreSQL `LISTEN/NOTIFY` on promote and inbox writes wakes the waiting
  streams.

## 6. Publishing keeps the gate's guarantees

| Guarantee | How the API keeps it |
|---|---|
| Nothing enters the record without the gate | `submitArtifact` writes only to `inbox`, as `publish.py` does: the file `{name}@{when}`, metadata `{"symposium_submission": true}`, `created_by` the key's Member. The API never writes to `record`. Only the gate, run from the admin's skill, promotes. |
| The gate's checks, before submitting | `checkSubmission` and `submitArtifact` run, in order: the naming rule (`<handle>_` prefix, the key's Member); the 250 KB limit on embedded payload (`EMBED_REFUSE`); then `tools/validate.py`, the validator the gate runs, against the record as it stands. Any refusal answers 422 with every finding. Nothing is stored. The skill's publishing roles (`--role`) are limits an agent session sets on itself, and stay in the skill. |
| Serial `created` order | One Artifact per call. `created` must be null, and the gate stamps it at promote. The gate orders the submissions it decides, as it does today. |
| Attribution | `published_by` must be `@<handle>`, the key's Member, and `name` must carry its prefix, so the gate's own check (the inbox name prefix is the submitter's handle, and the submitter is on the roster) passes for the same reason it passes today. |
| One decision per submission | The gate decides, as today. The storage also enforces it: a promote writes `record/<name>` and a reply writes `inbox/<admin>_REPLY_<item>`, and the data server refuses a second file of either name with 409. |
| Replies to rejections | The gate's reply is the same `NonGroundable` in `inbox`, readable by its recipient. The API carries it in the rejected submission's `reply` field, in `getSubmission`, `listSubmissions` and the `submission.rejected` event. A Member answers a rejection by submitting a corrected Artifact, which is the same path as today. |

**Where each submission state comes from.** The server learns every state from what it
stores or computes.

| State | Learned from |
|---|---|
| `pending` | an `inbox` item marked `symposium_submission`, with no record version or reply naming it |
| `skipped` | the gate's own rule, applied by the server when it reads the item: the inbox name before `@` is the artifact's name prefixed with its submitter's handle, and the submitter is on the roster. An item failing either is `skipped`, as the gate would set it aside |
| `accepted` | a `record` version whose `symposium_submission_citation` names it |
| `rejected` | an `inbox` reply whose `symposium_submission_citation` names it |

## 7. One API, one key

The record routes and the data server's own routes for communities, members, keys,
collections and files share `/v1`, one process and one access model.

| Credential | How a caller gets it | Where it works |
|---|---|---|
| Ed25519 key | made on the Member's or the admin's own machine; the server holds its public half | signs a sign-in challenge, nothing more |
| session key `sak_…` | an Ed25519 sign-in | every route of `/v1`, in its community (the admin's: every community) |
| issued key `sak_…` | issued with a session, for an application | every route of `/v1` but those that change access, keys or the server, in its community |
| no key | — | the contract, `/v1/status`, sign-in and registration, and reads of a public collection |

What a key may read and write is its collection's to decide: the owner's grants, and whether
the collection is public. A Member's key reads what the Member may, a `non-member` key what it
is granted, and nobody reads another Member's `inbox` files, because the `inbox` visibility
rule (the first writer, the admin, and `metadata.recipients`) applies to every key.

## 8. Errors, versioning and limits

- **Errors.** Every error uses the `Error` body: `{detail, code, findings?}`. `detail` is
  the sentence `/v1` writes, and `code` is stable for programs. FastAPI's default 422
  validation body is mapped onto it, so there is exactly one error shape.
- **Versioning.** The major version is in the path: `/v1`. Additive changes (a new
  endpoint, a new optional field, a new event type) stay in v1. A breaking change opens
  `/v2` beside it. `info.version` tracks the contract.
- **Limits.**
  - A request body is at most 8 MiB, which answers 413: at once from its `Content-Length`,
    or once the bytes read pass it. A file's content (`putFile`, `addFileVersion`) and an
    import stream, with no limit but the quota.
  - An Artifact's embedded payload is at most 250 KB, as `publish.py` refuses today, which
    answers 422 with a finding. The validator reviews any payload over 50 KB.
  - The per-Member quota, `SYMPOSIUM_SERVER_QUOTA_BYTES`, applies to submissions as it does
    to `/v1` writes.
  - A page holds at most 1000 items, and a cursor is at most 256 characters. Responses are
    otherwise unbounded, like `/v1`.
  - Open streams are capped, and a stream past a cap answers 429 with the `Error` body
    (§10.5): 8 per API key, 4 per anonymous client address, 200 anonymous in all, and
    `SYMPOSIUM_SERVER_MAX_STREAMS` (default 500) across the server.
  - Requests other than streams carry no rate limit, matching `/v1`. A deployment that needs
    one puts it in its ingress.

## 9. How the code is arranged

The API's code and the rules it shares with the skill each get their own package, so every
dependency points one way: toward the rules, and from the API toward storage. A small
composition module outside both services assembles the running server, so no package
imports one that imports it back.

| Package | Holds | Imported by |
|---|---|---|
| `symposium_rules` (`tools/symposium_rules/`, standard library only, Python 3.9+) | the validator (today `tools/validate.py`), the gate's skip rule (today in `tools/gate.py`), and the naming and payload checks (today in `tools/publish.py`) | the skill's `tools/`, the API |
| `symposium_api` | the record routes, the index and the streams, as FastAPI routers generated from the contract over a service built from a records layer it is handed | `symposium_server` |
| `symposium_data` | storage and the hand-written routes of `/v1`: records, identity, collections and files, the API keys (`api_keys.py`), and `access`, which authenticates every route's key and applies the contract's rules | `symposium_api`, through its records layer and `access`; `symposium_server` |
| `symposium_server` | the composition root: it builds `symposium_data`'s app and records layer, builds `symposium_api`'s routers from that records layer, and mounts them at `/v1`. uvicorn starts this module | nothing |

`tools/validate.py`, `tools/gate.py` and `tools/publish.py` become thin callers of
`symposium_rules`, with the same behaviour and the same command lines. The skill bundle and
the data server image both ship the one package (the image takes it, and the contract, as
named build contexts), so the validator the API runs is the validator the gate runs, byte
for byte. Storage imports none of the rules and none of the
API, and the rules import none of the storage. Only `symposium_server` sees all three.

## 10. Where the API server runs

### 10.1 The decision

| Question | Answer |
|---|---|
| Which image | `ndexbio/symposium-data`, the data server's own image. The API ships in the same release. |
| Which process | the `api-server` supervisord program, the one uvicorn process that serves `/v1`. It starts `symposium_server:app`, which mounts the record routes beside the data server's own. |
| Which HTTP server | uvicorn, the ASGI server the image already runs, with `--proxy-headers` as today. |
| Which port | 8080, the port the image exposes. |
| Which language and framework | Python 3.11 and FastAPI, the data server's own. |
| Which volume | `/apps`, the image's one persistent volume. The API keeps its index in the same PostgreSQL. |

### 10.2 Why the data server image

- **The API reads PostgreSQL directly.** The index, the `api_keys` table, the roster and
  the feeds all live in the image's PostgreSQL, which listens on `127.0.0.1` alone. A process
  in the image reaches it with no new network exposure and no new credential. A separate
  image would need PostgreSQL opened to the network, or every read relayed through `/v1`
  over HTTP. The second doubles the work of every traversal and puts a token exchange in
  front of every query.
- **Streams wake on the same database.** `LISTEN/NOTIFY` on promote and inbox writes needs
  a connection to that PostgreSQL. Inside the image it is one more pooled connection.
- **The secrets are already there.** `API_KEY_ENC_KEY_FILE` sits beside `service.env` in
  `/apps/data/config`, generated by the same `start.sh` first-boot phase.
- **One deployment, one release.** An operator runs one `docker run`, or one Helm install
  of one Kubernetes Deployment, as `skills/symposium/SKILL.md` teaches. The API's version moves with
  the storage it reads, so the two can never be deployed out of step.

### 10.3 Why one uvicorn process, on the same port

The data server is FastAPI on uvicorn already. The record routes are FastAPI too, so
`symposium_server` mounts their routers on the same app, and one process serves `/v1`.

- `docker run -p 127.0.0.1:8790:8080`, the Kubernetes Service on 8080, and the Ingress on
  `/` all keep their shape.
- The skill's `data-server-url` already names the server. An application uses the same URL
  with `/v1` after it.
- A second uvicorn on another port would need a second Service port, a second Ingress rule
  and a second health check, for no isolation the measures in §10.5 do not already give.

### 10.4 Why Python, and a Java server ruled out

The API runs the gate's own checks: the validator, the skip rule, and the naming and
payload checks, all in `symposium_rules` (§9). They are Python, and so are the gate, the
skill and the data server. A Java server would need a second implementation of the
validator. Two validators drift, and the day they disagree, `checkSubmission` passes an
Artifact the gate rejects. That breaks the promise that a pass means the gate accepts.
Java would also add a JVM to an image that holds none today. A Go or Node server fails the
same test for the same reason.

### 10.5 Running it

- **Always on.** The `api-server` program always starts `symposium_server:app`, so every data
  server serves the record routes. `start.sh` starts the program for its `--api-server`
  flag, which the Dockerfile's `CMD` and the Kubernetes container args pass.
- **Canonical URLs.** `SYMPOSIUM_SERVER_PUBLIC_URL`, when set, is the base of every `url` the API
  answers; otherwise the base is the URL the request reached, after `--proxy-headers`.
- **CPU work leaves the event loop.** Validation, findings and address resolution run in
  FastAPI's thread pool, so a long validation holds no stream and no other request.
- **Streams are capped, across the whole server.** Every open stream holds one row in a
  PostgreSQL table, `api_streams (id, key_id, client_addr, opened, seen)`. The row is
  written when the stream opens and deleted when it closes. The heartbeat refreshes `seen`
  every 30 seconds, and a sweep deletes rows unseen for 90 seconds, so a crashed worker
  frees its slots. A new stream counts the rows under a per-scope advisory lock, so the
  caps hold however many workers run:

  | Cap | Limit |
  |---|---|
  | per API key | 8 |
  | per anonymous client address | 4 |
  | anonymous, in all | 200 |
  | the whole server | `SYMPOSIUM_SERVER_MAX_STREAMS`, default 500 |

  Past any cap, a new stream answers 429 with the `Error` body. Anonymous streams can hold
  at most 200 slots, so key holders always keep at least 300. The client address is the one uvicorn
  reports after `--proxy-headers`, from a proxy in `SYMPOSIUM_SERVER_TRUSTED_PROXY` alone.
  Each stream holds one coroutine and wakes on a shared `LISTEN` connection, so 500 cost
  little memory.
- **Workers.** One uvicorn worker by default, as today. `SYMPOSIUM_SERVER_WORKERS` is a new
  setting that raises it, passed to `--workers` by the `api-server` program. Every worker
  keeps no client's state in memory (§5.3), and the stream caps live in PostgreSQL, so any
  worker serves any request or reconnect.
- **The ingress.** SSE needs two settings on a proxy in front of the server: response
  buffering off, and a read timeout longer than the 30-second heartbeat. The API sends
  `X-Accel-Buffering: no` on every stream, which nginx honours. On Kubernetes the Helm
  chart (`data-server/helm/symposium-helm`) carries both: its Gateway API HTTPRoute turns
  the route's timeouts off (`timeouts: {request: 0s, backendRequest: 0s}`), and its Ingress
  takes the controller's own settings in `expose.ingress.annotations`.
- **TLS** stays where it is today: the deployment's gateway, ingress or proxy terminates it.
- **Browsers.** `SYMPOSIUM_SERVER_CORS_ORIGINS` (the Helm chart's `corsOrigins`) lists the
  origins a browser app may call the API from. None by default. The server then allows the
  `Authorization`, `Content-Type`, `Repr-Digest`, `If-Match`, `Range`, `Last-Event-ID` and
  `X-Data-*` request headers, and exposes `ETag`, `Link`, `Location`, `Repr-Digest`,
  `Content-Range` and `X-Data-*`.
- **Health.** `GET /v1/status` stays the health check. Once the server is operational it
  also reports `api_index.behind`, the server-wide count of record versions the index has
  yet to fold in.
