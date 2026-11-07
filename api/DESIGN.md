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
| CommunityRecord (§1.1) | resource: the record's state | `/communities/{community}/record` |
| Member (§1.4) | resource; exposes its name and nothing inside it | `/communities/{community}/members/{handle}` |
| Artifact (§1.5), every type | resource, read-only | `/communities/{community}/artifacts/{name}` |
| Artifact property | sub-resource | `/communities/{community}/artifacts/{name}/properties/{property}` |
| Object (§1.6), every type | sub-resource of its Artifact | `/communities/{community}/artifacts/{name}/objects/{object}` |
| Object property | sub-resource | `…/objects/{object}/properties/{property}` |
| Relationship (§1.7) | listed under its Artifact; it has no address, so it gets no URL of its own | `/communities/{community}/artifacts/{name}/relationships` |
| Address (§1.8), schema references included | resolved | `/communities/{community}/addresses?address=…` |
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
  header properties, read as they are. `published_by` is permanent. That is why §4.5 ties
  a publishing key to one user.
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
it, with the community's known handles as they stand when the index first folds that
Artifact in. On a server whose index is built over a record that already exists, those handles
are today's, so an older Artifact's `accepted` findings may differ from what its gate saw on a
member address added since.

A version purged on `/v1` leaves every read of the index: its Artifact answers 404, and its
citations leave `cited-by` and supersession.

### 1.4 Canonical URLs

Every resource body carries `url`: an absolute URL on the data server, under
`/v1/communities/{community}`. It is the same whichever host or application asks. This removes the
record browser's `localhost` link problem. An application links to the API URL, or to its
own page built from it.

An address maps to a URL by a fixed rule:

| Address | URL |
|---|---|
| `@<member>` | `/communities/{community}/members/<member>` |
| `@<artifact>` | `/communities/{community}/artifacts/<artifact>` |
| `@<artifact>.<object>` | `/communities/{community}/artifacts/<artifact>/objects/<object>` |
| `@<artifact>.<property>` | `/communities/{community}/artifacts/<artifact>/properties/<property>` |
| `@<artifact>.<object>.<property>` | `…/objects/<object>/properties/<property>` |
| anything with `#<schema reference>` | `/communities/{community}/addresses?address=<the address, URL-encoded>` |

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
| one security scheme, `apiKey`; keys are issued on the data server's `/v1` (§4.6) | one credential, checked one way |
| a member issued key acts as the user who issued it; `Me` answers `handle` and `label` | a submission is attributed to the user who made the key, never to one another caller named |
| `getArtifactContent` added; `links.content` names it | an Artifact's stored bytes are reachable with the same API key. It answers those bytes untouched, so it carries no `position`; `x-stored` marks it |
| one API: the record routes moved from `/api/v1` to `/v1`, beside the data server's own | two prefixes took two credentials and checked access two ways; one prefix takes one API key, and the collections decide access (§3, §7) |
| `x-grants` and `x-session` added; `x-anonymous` is `always` or `public`; `Me` adds `kind`, `kid`, `suspect_after`, `roles` and the resolved `context` | every operation states the grants that may call it, and a caller reads what it holds (§3) |

## 2. The skill's commands → endpoints

These skill commands have an equivalent in the API. Each row names the operation in
`openapi.yaml` that does the command's work for a REST client.

| Command | Method and path | Operations |
|---|---|---|
| `publish <artifact.json>` | `POST /communities/{community}/submissions` | `submitArtifact` |
| `validate <artifact.json>` | `POST /communities/{community}/submission-checks` | `checkSubmission` |
| `sync` | `GET /communities/{community}/artifacts?cursor=…`, `GET /communities/{community}/submissions?status=rejected` | `listArtifacts`, `listSubmissions` |
| `sync --watch` | `GET /communities/{community}/record/events`, `GET /communities/{community}/submissions/events` | `streamRecord`, `streamSubmissions` |
| `users list` | `GET /communities/{community}/users` | `listUsers` |

The three key commands, `gen-api-key`, `list-api-keys` and `revoke-api-key`, call the data
server's own `/v1/communities/{community}/api-keys` routes (§4.6), which take a session key.

## 3. Access

### 3.1 Principals, grants and roles

Every request carries one API key, or none. A key resolves to its **principal**, the identity
that holds roles:

| Principal | Its community |
|---|---|
| a user homed in a community (a member account) | its home community |
| a server-level user (root and the server admins) | none: it works in every community |
| a non-member issued key | the community it was issued in |

A session key, and a member issued key, act as their user.

**Grants** are fixed capabilities. `read`, `write` and `manage` are collection-scoped: each
holds a collection value, `["*"]` (every collection), `[]` (only the collections the caller
owns) or a list of names. The others hold no value: `publish` (submit to `inbox`), `gate`
(read every `inbox` item, reply, promote into `record`), `members` (invite, assign roles,
remove users and change any key of the community), `export`, `communities` (create, import
and port communities; no quota) and `delegate` (server-level users).

**Roles** are six fixed bundles of grants, defined in `symposium_data/access/rbac.py`:

| Role | Held by | Grants |
|---|---|---|
| `server-root` | root, bound from the key file | `read`, `write`, `manage` on `*`; `delegate`, `communities`, `gate`, `members`, `export` |
| `server-admin` | server-level users | `read`, `write`, `manage` on `*`; `communities`, `gate`, `members`, `export` |
| `community-admin` | homed users | `read`, `write`, `manage` on `*`; `gate`, `members`, `export` |
| `gate-keeper` | homed users | `read` on `*`; `gate` |
| `community-member` | homed users and API keys | `read`, `write` on the assignment's collection value, and for a user `read` on `record` as well; `manage` on `[]`; `publish` |
| `community-observer` | homed users and API keys | `read` on the assignment's collection value |

A role assignment names a principal, a role and, for `community-member` and
`community-observer` only, a required collection value. Assignments are sub-resources of their
principal: `…/users/{handle}/roles/{role}` and `…/api-keys/{key_id}/roles/{role}`. `PUT` sets a
role's whole value under `If-Match` with its `ETag`; `PUT` and `DELETE` on
`…/roles/{role}/collections/{collection}` add or withdraw one collection, with the authority
over that collection alone, which is how an owner shares its own.

**Users and Members are two resources.** `…/communities/{c}/users` are the community's
accounts, with their roles; `…/communities/{c}/members` are the specification's Members, the
record's publishers, read as the record is (anonymously while it is public). The community is never part of an
assignment: it is the principal's own.

### 3.2 The user context and its two check points

On every request, and at every stream beat, the server compiles the caller's live
assignments into a `UserContext`: its principal, its community, whether it signed in with a
session key, and a map from each grant it holds to its collection value. Values of the same
grant merge: lists union, and `*` absorbs everything.

Every check is `UserContext.allowsRequest(grant, community, collection=None)`, at two points:

1. **Route.** `x-grants` lists the grants that may call an operation, any one sufficing. The
   check asks only whether the grant is held in the request's community, with any value. An
   empty list admits any key of the community and leaves the decision to the handler.
2. **Handler.** Every read, write or manage of a collection, file or version asks again with
   the collection (a file resolves to its collection first). Listings and searches return
   only the collections that pass. The record's routes act on `record`.

A collection-scoped check allows when the caller signed in with a session key and owns the
collection (the **owner allowance**), when the caller is server-level, or when its value is
`*` or names the collection in the caller's community. Issued keys get no owner allowance: a
key reaches exactly the collections its own assignments list.

`inbox` sits outside the collection values. A put marked as a submission takes `publish`, a
put marked as a reply takes `gate`, and any other put is refused. `publish` holders see their
own submissions and the replies addressed to them; `gate` holders see every item. Promotion
is the only write into `record`, and it takes `gate`.

Anonymous access needs no key: an operation that answers without one says so in
`x-anonymous`, and its `security` includes `{}`. `always` marks the contract, status and
sign-in routes. `public` marks reads that answer anonymously while the collection they touch
is public.

An unknown community, collection or file answers 404; a refused check answers 403; a
missing, unknown or expired key answers 401.

### 3.3 Endpoint × grants

Each operation's description ends with a `Grants:` line and an `Authentication:` line, the
credentials it takes in the words of the data server README's Authentication column. Both
follow from `x-grants`, `x-session` and `x-anonymous`. Routes marked `x-session` take a
signed-in user's session key, so only a signed-in user invites, assigns, issues or revokes.

| Operation | Method and path | Grants | Session | Anonymous |
|---|---|---|---|---|
| getOpenApiYaml | GET /openapi.yaml | no key |  | always |
| getOpenApiJson | GET /openapi.json | no key |  | always |
| getStatus | GET /status | no key |  | always |
| createChallenge | POST /challenges | no key |  | always |
| createSession | POST /sessions | no key |  | always |
| getMe | GET /me | any key; the handler decides |  |  |
| rotateKey | POST /me/keys | any key; the handler decides | ✓ |  |
| register | POST /registrations | no key |  | always |
| listRoles | GET /roles | any key; the handler decides |  |  |
| getRole | GET /roles/{role} | any key; the handler decides |  |  |
| listServerUsers | GET /users | `delegate` | ✓ |  |
| getServerUser | GET /users/{handle} | `delegate` | ✓ |  |
| updateServerUser | PATCH /users/{handle} | `delegate` | ✓ |  |
| removeServerUser | DELETE /users/{handle} | `delegate` | ✓ |  |
| rebindServerUser | POST /users/{handle}/invites | `delegate` | ✓ |  |
| listServerUserRoles | GET /users/{handle}/roles | any key; the handler decides | ✓ |  |
| getServerUserRole | GET /users/{handle}/roles/{role} | any key; the handler decides | ✓ |  |
| setServerUserRole | PUT /users/{handle}/roles/{role} | any key; the handler decides | ✓ |  |
| unsetServerUserRole | DELETE /users/{handle}/roles/{role} | any key; the handler decides | ✓ |  |
| listServerInvites | GET /invites | `delegate` | ✓ |  |
| createServerInvite | POST /invites | `delegate` | ✓ |  |
| getServerInvite | GET /invites/{invite_id} | `delegate` | ✓ |  |
| revokeServerInvite | DELETE /invites/{invite_id} | `delegate` | ✓ |  |
| listCommunities | GET /communities | `communities` | ✓ |  |
| createCommunity | POST /communities | `communities` | ✓ |  |
| getCommunity | GET /communities/{community} | any key; the handler decides |  |  |
| exportCommunity | GET /communities/{community}/archive | `export` | ✓ |  |
| listUsers | GET /communities/{community}/users | any key; the handler decides |  |  |
| getUser | GET /communities/{community}/users/{handle} | any key; the handler decides |  |  |
| updateUser | PATCH /communities/{community}/users/{handle} | `members` | ✓ |  |
| removeUser | DELETE /communities/{community}/users/{handle} | `members` | ✓ |  |
| rebindUser | POST /communities/{community}/users/{handle}/invites | `members` | ✓ |  |
| listUserRoles | GET /communities/{community}/users/{handle}/roles | any key; the handler decides | ✓ |  |
| getUserRole | GET /communities/{community}/users/{handle}/roles/{role} | any key; the handler decides | ✓ |  |
| setUserRole | PUT /communities/{community}/users/{handle}/roles/{role} | any key; the handler decides | ✓ |  |
| unsetUserRole | DELETE /communities/{community}/users/{handle}/roles/{role} | any key; the handler decides | ✓ |  |
| addUserRoleCollection | PUT /communities/{community}/users/{handle}/roles/{role}/collections/{role_collection} | any key; the handler decides | ✓ |  |
| removeUserRoleCollection | DELETE /communities/{community}/users/{handle}/roles/{role}/collections/{role_collection} | any key; the handler decides | ✓ |  |
| listInvites | GET /communities/{community}/invites | `members` | ✓ |  |
| createInvite | POST /communities/{community}/invites | `members` | ✓ |  |
| getInvite | GET /communities/{community}/invites/{invite_id} | `members` | ✓ |  |
| revokeInvite | DELETE /communities/{community}/invites/{invite_id} | `members` | ✓ |  |
| listApiKeyRoles | GET /communities/{community}/api-keys/{key_id}/roles | any key; the handler decides | ✓ |  |
| getApiKeyRole | GET /communities/{community}/api-keys/{key_id}/roles/{role} | any key; the handler decides | ✓ |  |
| setApiKeyRole | PUT /communities/{community}/api-keys/{key_id}/roles/{role} | any key; the handler decides | ✓ |  |
| unsetApiKeyRole | DELETE /communities/{community}/api-keys/{key_id}/roles/{role} | any key; the handler decides | ✓ |  |
| addApiKeyRoleCollection | PUT /communities/{community}/api-keys/{key_id}/roles/{role}/collections/{role_collection} | any key; the handler decides | ✓ |  |
| removeApiKeyRoleCollection | DELETE /communities/{community}/api-keys/{key_id}/roles/{role}/collections/{role_collection} | any key; the handler decides | ✓ |  |
| listApiKeys | GET /communities/{community}/api-keys | any key; the handler decides | ✓ |  |
| createApiKey | POST /communities/{community}/api-keys | any key; the handler decides | ✓ |  |
| getApiKey | GET /communities/{community}/api-keys/{key_id} | any key; the handler decides | ✓ |  |
| revokeApiKey | DELETE /communities/{community}/api-keys/{key_id} | any key; the handler decides | ✓ |  |
| startNdexImport | POST /communities/{community}/ndex-imports | `communities` | ✓ |  |
| getNdexImport | GET /communities/{community}/ndex-imports/{import_id} | `communities` | ✓ |  |
| getRecord | GET /communities/{community}/record | `read` |  | public |
| streamRecord | GET /communities/{community}/record/events | `read` |  | public |
| listArtifacts | GET /communities/{community}/artifacts | `read` |  | public |
| getArtifact | GET /communities/{community}/artifacts/{name} | `read` |  | public |
| getArtifactContent | GET /communities/{community}/artifacts/{name}/content | `read` |  | public |
| getArtifactProperty | GET /communities/{community}/artifacts/{name}/properties/{property} | `read` |  | public |
| listObjects | GET /communities/{community}/artifacts/{name}/objects | `read` |  | public |
| getObject | GET /communities/{community}/artifacts/{name}/objects/{object} | `read` |  | public |
| getObjectProperty | GET /communities/{community}/artifacts/{name}/objects/{object}/properties/{property} | `read` |  | public |
| listRelationships | GET /communities/{community}/artifacts/{name}/relationships | `read` |  | public |
| listCitedBy | GET /communities/{community}/artifacts/{name}/cited-by | `read` |  | public |
| listSupersession | GET /communities/{community}/artifacts/{name}/supersession | `read` |  | public |
| listFindings | GET /communities/{community}/artifacts/{name}/findings | `read` |  | public |
| listMembers | GET /communities/{community}/members | `read` |  | public |
| getMember | GET /communities/{community}/members/{handle} | `read` |  | public |
| listMemberArtifacts | GET /communities/{community}/members/{handle}/artifacts | `read` |  | public |
| listMemberMessages | GET /communities/{community}/members/{handle}/messages | `read` |  | public |
| resolveAddress | GET /communities/{community}/addresses | `read` |  | public |
| listSubmissions | GET /communities/{community}/submissions | `publish` |  |  |
| submitArtifact | POST /communities/{community}/submissions | `publish` |  |  |
| getSubmission | GET /communities/{community}/submissions/{submission} | `publish` |  |  |
| streamSubmissions | GET /communities/{community}/submissions/events | `publish` |  |  |
| checkSubmission | POST /communities/{community}/submission-checks | `publish` |  |  |
| listCollections | GET /communities/{community}/collections | any key; the handler decides |  | public |
| createCollection | POST /communities/{community}/collections | `write` |  |  |
| getCollection | GET /communities/{community}/collections/{collection} | any key; the handler decides |  | public |
| updateCollection | PATCH /communities/{community}/collections/{collection} | `manage` | ✓ |  |
| listFiles | GET /communities/{community}/collections/{collection}/files | any key; the handler decides |  | public |
| promoteVersion | POST /communities/{community}/collections/{collection}/files | `gate` or `manage` | ✓ |  |
| queryCollection | POST /communities/{community}/collections/{collection}/files/search | any key; the handler decides |  | public |
| putFile | PUT /communities/{community}/collections/{collection}/files/{name} | `write` or `publish` or `gate` |  |  |
| listChanges | GET /communities/{community}/collections/{collection}/changes | any key; the handler decides |  | public |
| getFile | GET /communities/{community}/files/{file_id} | any key; the handler decides |  | public |
| deleteFile | DELETE /communities/{community}/files/{file_id} | `write` or `manage` |  |  |
| listFileVersions | GET /communities/{community}/files/{file_id}/versions | any key; the handler decides |  | public |
| addFileVersion | POST /communities/{community}/files/{file_id}/versions | `write` or `manage` |  |  |
| getFileContent | GET /communities/{community}/files/{file_id}/versions/{ref} | any key; the handler decides |  | public |
| purgeVersion | DELETE /communities/{community}/files/{file_id}/versions/{ref} | `manage` | ✓ |  |
| statFileVersion | GET /communities/{community}/files/{file_id}/versions/{ref}/metadata | any key; the handler decides |  | public |
| verifyCitation | GET /communities/{community}/files/{file_id}/versions/{ref}/verification | any key; the handler decides |  | public |
| findByHash | GET /communities/{community}/versions | any key; the handler decides |  | public |

## 4. API keys

### 4.1 Format and presentation

A key is `sak_` followed by the base64url of 32 random bytes (43 characters): an opaque bearer
secret, sent as `Authorization: Bearer sak_…`. The contract declares it as the `apiKey`
security scheme, the API's only one; any other bearer credential answers 401.

### 4.2 Kinds of key

- **A session key** proves a user signed in: `POST /v1/challenges` then
  `POST /v1/sessions` with `{handle, community}` (`community` is null for a server-level
  user), signed with the user's private key file. It lasts `SYMPOSIUM_SERVER_SESSION_TTL`
  seconds (default 900); the skill's CLI obtains one per command.
- **A member issued key** acts as the user who issued it, for an application or script. It
  carries `community-member` or `community-observer` assignments of its own, which never
  exceed its user's grants.
- **A non-member issued key** is its own principal, for an outside application. It carries
  `community-observer` alone, so it only reads.

### 4.3 The table

```sql
CREATE TABLE api_keys (
    id          uuid PRIMARY KEY,
    hash        text NOT NULL UNIQUE,      -- hex SHA-256 of the whole key; the lookup
    kind        text NOT NULL CHECK (kind IN ('session', 'issued')),
    user_id     uuid REFERENCES users (id),-- the user it acts as; NULL for a non-member key
    community   text,                      -- issued keys: the key's community
    handle      text,                      -- the user's handle, for attribution
    label       text,                      -- issued keys: its issuer's name for it
    ed25519_kid text,                      -- sessions: the key whose private key file obtained it
    ciphertext  bytea,                     -- issued keys: AES-256-GCM of the key
    nonce       bytea,                     -- the 12-byte GCM nonce
    enc_kid     text,                      -- which encryption key sealed it
    created_by  text NOT NULL,             -- the issuer
    created     timestamptz NOT NULL DEFAULT now(),
    expires     timestamptz,               -- NULL: an issued key lasts until revoked
    last_used   timestamptz                -- refreshed at most once a minute
);
```

An issued key's roles are rows of `role_assignments` naming it, deleted with the key.
`export` leaves keys out: a key is a credential for one server.

### 4.4 Encryption at rest

An issued key's owner must be able to read it back, so it is stored **retrievably**, and
**never in plain text**:

- **Authentication** computes SHA-256 of the presented key and looks up `hash`. It decrypts
  nothing. A 256-bit random secret needs no slow hash.
- **The owner's listing** decrypts `ciphertext` with AES-256-GCM. The associated data is
  `id ‖ handle ‖ label ‖ community`, so a ciphertext copied onto another row fails to
  decrypt.
- **The secret** is 32 random bytes in `API_KEY_ENC_KEY_FILE`, by default
  `/apps/data/config/api_key_enc.key`, mode 0600. `docker/scripts/start.sh` generates it on
  first boot. A database dump alone reveals no key.
- **Rotation**: `enc_kid` names the key that sealed each row. A new file becomes the key for
  new rows, and a one-off re-seal moves old rows over.
- **A session key** is shown once, so it is stored as its hash alone.

### 4.5 Who a key acts as

A key's user, community and roles come from the server's rows, set when it is made and
changed only through the assignment routes; a request body never names them. The user
context is compiled on every request, so a change applies on the next one:

- **An assignment changes:** the next request, and the next beat of an open stream, uses the
  new grants.
- **A user is removed:** its assignments end, its sign-in keys retire, its sessions end, and
  every key it issued is deleted, in one transaction. Its handle stays bound to it.
- **A user's key file is rotated or rebound:** the sessions obtained with the old key end.

A key that publishes must publish as a user, because `published_by` is permanent attribution.
`submitArtifact` refuses a body whose `published_by` is anything other than `@<handle>`, or
whose `name` does not carry the `<handle>_` prefix.

### 4.6 Life cycle

Keys are issued, listed and revoked on `/v1/communities/{community}/api-keys` with a session key.

| Route | Who | What |
|---|---|---|
| `POST /v1/communities/{community}/api-keys` `{label, non_member?, roles, expires_days?}` | a signed-in user of the community | an issued key carrying `roles`, each within the issuer's grants; a non-member key also takes the authority to assign each role |
| `GET /v1/communities/{community}/api-keys` | the issuer: its own keys; a `members` holder: every key of the community | the keys with their roles, and their values for the issuer |
| `GET /v1/communities/{community}/api-keys/{key_id}` | the issuer, or a `members` holder | one key |
| `DELETE /v1/communities/{community}/api-keys/{key_id}` | the issuer, or a `members` holder | deletes the key and its assignments; its next request answers 401 |

A key's roles change through `…/api-keys/{key_id}/roles/{role}` (`PUT`, `DELETE`) and
`…/roles/{role}/collections/{collection}` (one collection at a time), by the
same two callers. Every route answers `Cache-Control: no-store` wherever it carries a key's
value. A label already on one of the issuer's keys answers 409.

Keys move as files, never through a terminal or a chat, because the repository's rule is
that a credential pasted into a transcript has been disclosed (`AGENTS.md`). The skill's
`gen-api-key` and `list-api-keys` write key values to 0600 files in the session's
`api-keys/` and print only where they are.

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
  checks a request runs (§3.2, §4.5). A stream whose key is deleted or expires, whose user is
  removed, or whose caller loses read access to the collection it follows (an unassigned
  role, a record made private), closes within 30 seconds. Revocation reaches an open stream
  as surely as a new request.
- The client's cursor holds the stream's position, and the server's one row per open
  stream (§10.5) lives in PostgreSQL, so no worker keeps a client's state in memory. Any
  worker can serve a reconnect. PostgreSQL `LISTEN/NOTIFY` on promote and inbox writes wakes the waiting
  streams.

## 6. Publishing keeps the gate's guarantees

| Guarantee | How the API keeps it |
|---|---|
| Nothing enters the record without the gate | `submitArtifact` writes only to `inbox`, as `publish.py` does: the file `{name}@{when}`, metadata `{"symposium_submission": true}`, `created_by` the key's Member. The API never writes to `record`. Only the gate, run by a holder of `gate` (a community admin or a gate-keeper), promotes. |
| The gate's checks, before submitting | `checkSubmission` and `submitArtifact` run, in order: the naming rule (`<handle>_` prefix, the key's Member); the 250 KB limit on embedded payload (`EMBED_REFUSE`); then `tools/validate.py`, the validator the gate runs, against the record as it stands. Any refusal answers 422 with every finding. Nothing is stored. The skill's publishing roles (`--role`) are limits an agent session sets on itself, and stay in the skill. |
| Serial `created` order | One Artifact per call. `created` must be null, and the gate stamps it at promote. The gate orders the submissions it decides, as it does today. |
| Attribution | `published_by` must be `@<handle>`, the key's user, and `name` must carry its prefix, so the gate's own check (the inbox name prefix is the submitter's handle, and the submitter is an active member) passes for the same reason. |
| One decision per submission | The gate decides, as today. The storage also enforces it: a promote writes `record/<name>` and a reply writes `inbox/<gate>_REPLY_<item>`, and the data server refuses a second file of either name with 409. |
| Replies to rejections | The gate's reply is the same `NonGroundable` in `inbox`, readable by its recipient. The API carries it in the rejected submission's `reply` field, in `getSubmission`, `listSubmissions` and the `submission.rejected` event. A Member answers a rejection by submitting a corrected Artifact, which is the same path as today. |

**Where each submission state comes from.** The server learns every state from what it
stores or computes.

| State | Learned from |
|---|---|
| `pending` | an `inbox` item marked `symposium_submission`, with no record version or reply naming it |
| `skipped` | the gate's own rule, applied by the server when it reads the item: the inbox name before `@` is the artifact's name prefixed with its submitter's handle, and the submitter is an active member. An item failing either is `skipped`, as the gate would set it aside |
| `accepted` | a `record` version whose `symposium_submission_citation` names it |
| `rejected` | an `inbox` reply whose `symposium_submission_citation` names it |

## 7. One API, one key

The record routes and the data server's own routes for communities, members, keys,
collections and files share `/v1`, one process and one access model.

| Credential | How a caller gets it | Where it works |
|---|---|---|
| private key file | made on the user's own machine (an Ed25519 key); the server holds its public key | signs the session management challenge |
| session key `sak_…` | the session management routes, with a private key file | every route of `/v1`, in its community (a server-level user's: every community) |
| issued key `sak_…` | issued with a session key, for an application | every route of `/v1` but those that change access, keys or the server, in its community |
| no key | — | the contract, `/v1/status`, session management and registration, and reads of a public collection |

What a key may read and write is its collection's to decide: the owner's grants, and whether
the collection is public. A member issued key reads what the Member may, a non-member issued key what it
is granted, and nobody reads another Member's `inbox` files, because the `inbox` visibility
rule (the first writer, holders of `gate`, and `metadata.recipients`) applies to every key.

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

- **The API reads PostgreSQL directly.** The index, the `api_keys` table, the users and
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
  origins a browser app may call the API from. For those origins the server allows the
  `Authorization`, `Content-Type`, `Repr-Digest`, `If-Match`, `Range`, `Last-Event-ID` and
  `X-Data-*` request headers, and exposes `ETag`, `Link`, `Location`, `Repr-Digest`,
  `Content-Range` and `X-Data-*`. Unset, the default, the API answers every request as
  usual and sends no CORS headers, so a browser lets only pages served from the API's own
  origin read its answers.
- **Health.** `GET /v1/status` stays the health check. Once the server is operational it
  also reports `api_index.behind`, the server-wide count of record versions the index has
  yet to fold in.
