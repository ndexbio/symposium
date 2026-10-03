# Bootstrapping from an NDEx community

`data-admin port-ndex` copies a Symposium community's record from an NDEx server into a
**fresh** Symposium Data server. It is a strictly one-time bootstrap: it runs once, before the
server's first boot, and never again. It is not a sync, and nothing ports incrementally.

## What it copies

From the community admin's NDEx account, every network the admin owns:
- networks marked `symposium_record` become files in `record`;
- networks marked `symposium_reply` (the gate's rejection replies) become files in `inbox`.

For each one it keeps:
- the **exact canonical bytes** of the artifact's JSON, so every sha256 is unchanged;
- the artifact's **name**, as the file name;
- its original **`created`**, as the version's `created`. Within each collection these instants
  must be strictly increasing, or the port refuses. Later writes continue after the last one;
- its **author**: the version's `created_by` is the artifact's `published_by`. The NDEx admin
  account becomes `PORT_ADMIN_HANDLE`.

Metadata is Symposium's marks only. A record carries `{"symposium_record": true}`; a reply
carries `{"symposium_reply": true, "symposium_in_reply_to": <name>, "recipients": [...]}`.
The recipients are the NDEx users the reply was shared with. Only they can read it.

Every author and every reply recipient is put on the community's roster as a **reserved**
handle; the admin is not on the roster. Members claim their handles by registering, as on any
server.

**Not copied:**
- a member's submission the gate has not yet decided, because the admin does not own it.
  **Drain the gate before porting**: run it until nothing is waiting;
- external `download` files: their artifacts keep the original `location`;
- NDEx accounts and passwords.

## Guarantees

- **All or nothing.** Every payload stays pending until one transaction writes the community,
  roster, files and versions. Before committing, the port checks every sha256 and the file
  counts. On any failure nothing is written, and the uploaded bytes are removed.
- **Fresh servers only.** The port is refused on a server that is initialized, already holds a
  community, or was ported before.
- **Once.** After a successful port, a sentinel refuses every further port. Rerunning the
  identical source only reports `already-ported` and writes nothing, so a retried Job is
  harmless.
- **The admin handle is fixed.** The port owns the default collections under
  `PORT_ADMIN_HANDLE`. `data-admin init` with any other handle is refused (exit 2) and changes
  nothing; rerun it with the ported handle.

Exit status is 0 (ported, or already ported from this source) or 1 (refused or failed). The
last line of output is a JSON event:

```json
{"event": "port-ndex", "status": "ok", "community": "demo", "admin": "demo-admin", "pages": 3, "networks": 10, "skipped": 0, "record": 9, "replies": 1, "reserved_roster": ["lyra", "vega"]}
```

## Configuration

| Variable | Meaning |
|---|---|
| `PORT_NDEX_URL` | Base URL of the NDEx server. Setting it makes the container run the port and exit. |
| `PORT_NDEX_CREDENTIALS_FILE` | A mounted JSON file `{"username": ..., "password": ...}` for the community admin's NDEx account. The pair is read only from this file, never from the environment or the command line. The container copies it into a 0600 file owned by the service user, and removes the copy afterwards. |
| `PORT_COMMUNITY` | The community to create, e.g. `demo`. |
| `PORT_ADMIN_HANDLE` | The admin handle, e.g. `demo-admin`. `data-admin init` must use the same one. |
| `PORT_NDEX_PAGE_SIZE` | Listing page size, default 100. NDEx truncates listings silently, so the port reads every page. |

## Run it with Docker

On a new, empty volume, before the server's first boot:

```bash
chmod 600 ndex-credentials.json
docker run --rm --name symposium-data-port-ndex \
  -v symposium-data:/apps \
  -v "$PWD/ndex-credentials.json:/run/secrets/ndex.json:ro" \
  -e PORT_NDEX_URL=https://ndex.example.org \
  -e PORT_NDEX_CREDENTIALS_FILE=/run/secrets/ndex.json \
  -e PORT_COMMUNITY=demo \
  -e PORT_ADMIN_HANDLE=demo-admin \
  ndexbio/symposium-data:<version>
```

Then start the server on the same volume as usual (`RUNBOOK.md`), and initialize it with the
ported admin handle:

```bash
docker exec -i symposium-data data-admin init --admin demo-admin --pubkey - < admin.pub.jwk
```

Members then register their reserved handles, each with an invite from the admin (`POST /v1/<community>/invites`).

## Run it on Kubernetes

`docker/k8s-data-port-job.yml` is the same port as a Job on the server's PVC. Its header lists
the steps: create the PVC, create the credentials Secret, run the Job to completion, delete
the Job and the Secret, then apply the Deployment and run `data-admin init`. The PVC is
ReadWriteOnce, so the Deployment must not run while the Job does.

## After the port

- Check the record: `GET /v1/c/<community>/record/changes` lists every artifact, in `created`
  order, with its original sha256.
- Delete the credentials file: the port never needs it again.
