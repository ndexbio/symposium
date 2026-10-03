# Porting a community from NDEx

The port-ndex copies a Symposium community's record from an NDEx server into an **empty**
community on a running Symposium Data server. The admin starts it with a route. It runs in the
background, inside the service. It is not a sync: a community that already holds files is
refused, so each community is ported once.

## What it copies

From the NDEx community admin's account, every network that account owns:
- networks marked `symposium_record` become files in `record`;
- networks marked `symposium_reply` (the gate's rejection replies) become files in `inbox`.

For each one it keeps:
- the **exact canonical bytes** of the artifact's JSON, so every sha256 is unchanged;
- the artifact's **name**, as the file name;
- its original **`created`**, as the version's `created`. Within each collection these instants
  must be strictly increasing, or the port refuses. Later writes continue after the last one;
- its **author**: the version's `created_by` is the artifact's `published_by`. The NDEx admin
  account becomes this server's admin. Any other NDEx account with the admin's handle is a
  collision, and the port refuses.

Metadata is Symposium's marks only. A record carries `{"symposium_record": true}`; a reply
carries `{"symposium_reply": true, "symposium_in_reply_to": <name>, "recipients": [...]}`.
The recipients are the NDEx users the reply was shared with. Only they can read it.

Every author and every reply recipient is added to the community's roster as a **reserved**
handle; the admin is never on a roster. Members claim their handles by registering with an
invite from the admin, as in any community.

**Not copied:**
- a member's submission the gate has not yet decided, because the admin does not own it.
  **Drain the gate before porting**: run it until nothing is waiting;
- external `download` files: their artifacts keep the original `location`;
- NDEx accounts and passwords.

## Run it

1. Create the community, empty: `POST /v1/communities {name}`.
2. Start the port-ndex, signed in as the admin:

   `POST /v1/<community>/port-ndex {"url": ..., "username": ..., "password": ...}`

   `url` is the NDEx server's base URL; `username` and `password` are the NDEx community admin's
   account, a bound pair. The password is held in memory only, for the length of the port, and
   is never stored or logged. It answers `202` with the port-ndex's `id` and `"state": "running"`.
3. Poll `GET /v1/<community>/port-ndex/<id>` until `state` is no longer `running`:

   ```json
   {"id": "…", "community": "demo", "source": "https://ndex.example.org", "state": "ok",
    "result": {"source": "https://ndex.example.org", "community": "demo", "admin": "demo-admin",
               "pages": 1, "networks": 10, "skipped": 0, "record": 9, "replies": 1,
               "reserved_roster": ["lyra", "vega"]},
    "started": "…", "finished": "…"}
   ```

   `state` is `ok`, `refused` (the source or the community does not qualify; `result.reason`
   says why) or `failed` (an error; `result.reason` names it).

The start is refused at once, before NDEx is contacted, when:
- the community does not exist (`404`);
- the caller is not the admin (`403`);
- the community holds files (`400`);
- another port-ndex is running anywhere on the server (`409`).

## Guarantees

- **All or nothing.** Every payload stays pending until one transaction writes the roster,
  files and versions. Before committing, the port checks every sha256 and the file counts. On
  any failure nothing is written, the uploaded bytes are removed, and the community can be
  ported again.
- **Once per community.** A community that holds files is refused, so a ported community is
  never ported over.
- **One at a time.** At most one port-ndex runs on a server.
- **A restart ends it.** A port-ndex cut off by a service restart reads back as `failed`; it
  wrote nothing, and can be started again.
- **Every page is read.** NDEx truncates listings silently, so the port reads the admin's
  networks page by page (100 at a time) until a short page.

## After the port

- Check the record: `GET /v1/<community>/collections/record/changes` lists every artifact, in
  `created` order, with its original sha256.
- Add the members' invites (`POST /v1/<community>/invites`) so they can claim their handles.
