# Symposium Data server runbook

Nobody needs a shell on the server: every admin operation is a route, and the admin's key is a file placed on the server's volume. Admin routes need the admin's token, from `POST /v1/admin/challenge` and `POST /v1/admin/token` signed with the admin's private key; Symposium's CLI does this for the operator. The README lists every route.

## Deploy locally (Docker)

Every server needs the admin's **public** key file, `admin_pub_<handle>.key`, which Symposium's `admin-config` writes on the operator's machine (mode 0644). The private key never leaves that machine.

1. **Run the server.** It starts **non-operational**: `GET /v1/status` answers with `"mode": "non-operational"` and the `reason`, and every other route answers `501` until the key is in place.

   **Persistent.** All state lives in one directory of your machine, mounted on `/apps`:

   ```bash
   docker run -d --name symposium-data --restart unless-stopped \
     -p 127.0.0.1:8790:8080 -v /path/to/your/machine/symposium-storage:/apps \
     ndexbio/symposium-data:<version>
   ```

   **Ephemeral.** Without the mount, the data is lost when the container is removed. Suitable for trying it on one machine:

   ```bash
   docker run -d --name symposium-data -p 127.0.0.1:8790:8080 \
     ndexbio/symposium-data:<version>
   ```

   **Reachable by other machines.** Put a TLS-terminating proxy in front, and name it in `SYMPOSIUM_DATA_TRUSTED_PROXY`. Members join the same way as on a local server: by invite.

   ```bash
   docker run -d --name symposium-data --restart unless-stopped \
     -p 8790:8080 -v /path/to/your/machine/symposium-storage:/apps \
     -e SYMPOSIUM_DATA_TRUSTED_PROXY=<proxy address> \
     ndexbio/symposium-data:<version>
   ```

2. **Place the admin key file and restart:**

   ```bash
   cp ~/.symposium/admin/admin_pub_<handle>.key /path/to/your/machine/symposium-storage/
   docker restart symposium-data
   ```

3. **Check it:** `GET /v1/status` reports `"mode": "operational"`, the admin's handle and its key `fingerprint`. Compare the fingerprint with the one `admin-config` showed.

The first line of the container log is `symposium-data <version>`. The key file stays in the mounted directory, so later restarts, and a new container on the same directory, need nothing more. (For an ephemeral server, `docker cp ~/.symposium/admin/admin_pub_<handle>.key symposium-data:/apps/` places it.)

## Deploy remotely (Kubernetes)

`docker/k8s-data-deployment.yml` holds the PVC, the Deployment, a Service and an example TLS Ingress, commented out: uncomment it when the server needs a public HTTPS URL. The admin's key comes from the Secret `symposium-data-admin-key`, mounted as the directory `/apps/admin-key/`. The Secret is optional, so the server starts **non-operational** until it exists, as a `docker run` server does until its key file is placed.

1. **Run the server:**

   ```bash
   kubectl apply -f docker/k8s-data-deployment.yml
   kubectl wait --for=condition=Ready pod -l app=symposium-data --timeout=420s
   ```

2. **Make the admin key** against it: `/symposium admin-config --handle <handle> --data-server-url <url>`, which writes `admin_pub_<handle>.key`.
3. **Place it and restart:**

   ```bash
   kubectl create secret generic symposium-data-admin-key --from-file=admin_pub_<handle>.key
   kubectl rollout restart deploy/symposium-data
   ```

4. **Check it:** `GET /v1/status` reports `"mode": "operational"`, the admin's handle and the `fingerprint` `admin-config` showed.

- **Before applying:** edit the PVC size, pin the image to a released version, and, for a public URL, uncomment the Ingress and set its host and TLS secret. Without it, `kubectl port-forward svc/symposium-data 8790:8080` reaches the server from your machine.
- **Storage:** one ReadWriteOnce PVC, so the Deployment runs a single replica with the `Recreate` strategy.
- **Changing the admin's key:** replace the Secret, then `kubectl rollout restart deploy/symposium-data`. The key is read at start-up.
- **Validating the manifest:** `docker run --rm -v "$PWD/docker:/m:ro" ghcr.io/yannh/kubeconform:v0.6.7 -strict -summary /m/k8s-data-deployment.yml`. The `make test` integration suite runs this same check.

## The admin key file and the modes

The server reads `admin_pub_<handle>.key`, in `/apps/` or `/apps/admin-key/`, at every start-up (the README's "The admin key file" lists every case):

- **First start with the file:** it binds that handle and key, and saves a backup of them under `/apps/data/config`.
- **Operational:** `/v1/status` reports `"mode": "operational"`, the admin's handle and key `fingerprint` (its RFC 7638 thumbprint).
- **Non-operational** (`"mode": "non-operational"`, with a `reason`): every route but `/v1/status` answers `501`, and the console says why. The reasons are no key file (`admin key not provided`), several (`ambiguous admin key files`), a file that is not a usable public key (`admin key invalid`), or, on a server already bound, neither the file nor its backup (`admin key missing`). Put the right file in place and restart; the data is untouched.
- **Changing the admin's key:** replace the file (with Docker, copy the new one over it in the mounted directory; on Kubernetes, replace the Secret) and restart. The server rebinds, and the old key is refused from then on. The admin's handle never changes: a file naming another handle is ignored, with an error.
- **A missing key file** on a server already bound is not an outage: it runs from the backup and logs a warning.

## Many communities on one server

One server hosts many communities, each with its own members, identities and data.

- **Creating one:** `POST /v1/communities {name}` (admin), idempotent. A name is 1–20 letters, digits or underscores, unique ignoring case and matched ignoring case in paths; `status`, `communities` and `admin` are reserved. `GET /v1/communities` lists them.
- **Isolation:** every community's routes are under `/v1/<community>/…`. A member's token, a read key or a file id from one community is refused in another, and the same handle in two communities is two separate identities, each with its own key. Content is deduplicated within a community, never across, and quota is per member in each community. The admin is server-wide: its token works in every community, and its handle can never be a member's.
- **Rosters:** the admin manages each community's roster one handle at a time. `POST /v1/<community>/roster/<handle>` adds a member (idempotent; adding never removes anyone), `DELETE` removes one, and `GET /v1/<community>/roster` lists each member with whether it has registered and when its pending invite expires. Symposium's `bootstrap` does this.

**Members join only by invite**, on a local server as on a remote one. The admin issues one per member with `POST /v1/<community>/invites {handle, hours?}` and hands it over **out of band**, never through chat:

- An invite works once, only for its own handle and community, and only before it expires (72 h by default).
- Issuing a new invite for a handle revokes its earlier unused one, so only the newest works. Removing a handle from the roster revokes its pending invite too.
- `GET /v1/<community>/invites` lists the pending invites, secret included, so the admin can hand one over again. An invite stops being retrievable, and its secret is erased, the moment it is used, expires or is revoked. Export never includes invites.

The member registers with it (Symposium's `setup`).

**A member's lost or compromised key:** `POST /v1/<community>/owners/<handle>/rebind` retires the handle's keys and returns a fresh invite, so the member registers a new key under the same handle. `PUT /v1/<community>/owners/<handle>/suspect-after {"at": "2026-10-01T12:00:00+00:00"}` flags every version the handle writes after that instant: `stat` reports `"suspect": true`, and `GET /v1/<community>/whoami` reports the instant. Nothing is deleted, and attribution is kept. Both are admin only.

## Read keys

Read keys (`sdr_…`) let a non-member read one collection, or a single file. They are minted with `POST /v1/<community>/collections/<collection>/keys` by the collection's owner or the admin, or by a file's creator for that file only. The secret is shown once, at minting. The server stores only its hash, so a lost key cannot be recovered; mint a new one instead. `inbox` never takes read keys and is never public.

**Leaked key.** List the collection's keys (`GET …/keys` shows the label, creator, expiry, use count and last use, never the secret), then revoke it as the key's minter, the collection's owner or the admin. The key is refused from the very next request:

```bash
curl -X DELETE -H "Authorization: Bearer <token>" https://data.example.org/v1/<community>/keys/<key-id>
```

Removing an owner from the roster ends their control of their collections; the admin still manages them.

## Purge, the janitor and the scrub

**Purge** frees one version's content (R-B3). The version stays addressable and answers `410` with its metadata. The bytes are deleted only when no other live version shares them. The payload is marked `purging` before its bytes are touched and becomes `purged` only after they are gone; if S3 refuses, the route reports `"bytes_freed": false` and the janitor finishes the job. It is admin only:

```bash
curl -X POST -H "Authorization: Bearer <admin token>" https://data.example.org/v1/<community>/files/<file-id>/v/<n>/purge
```

**Janitor.** It runs in the background and removes what a crash mid-write leaves behind: uploads that never completed, and name reservations that never turned into a file. Both are removed after `SYMPOSIUM_DATA_PENDING_TTL`. Normal failures are cleaned up immediately; the janitor covers a crash, and retries any S3 delete that failed. Bytes are always deleted before the row that tracks them, so every object in the bucket stays accounted for. Work still in progress (a streaming upload, an import, a port) refreshes its timestamps (a heartbeat every TTL/3, at most every 60 s), so the janitor never expires live work.

**Scrub.** It also runs in the background, re-hashing stored content on a schedule. A mismatch is recorded, never repaired: `stat` reports `"integrity": "mismatch"`, and clients also detect it because the bytes no longer match `Repr-Digest`.

## The NDEx port (port-ndex)

A community that already lives on NDEx is copied into a new, empty community on a running server with the port-ndex route: create the community, start the port-ndex, and poll it until it finishes. `PORT_NDEX.md` describes what it copies, how to run it and what it guarantees.

## Back up, export and import

- **Back up:** everything is in the directory mounted on `/apps` (or the PVC). Stop the server, then copy or snapshot it.
- **Export one community** while the server runs (admin only). The export is one consistent snapshot: rows, read keys (hashes only), the members' public keys, and every stored payload. Invites are not included.

  ```bash
  curl -fsS -H "Authorization: Bearer <admin token>" -o demo.tar https://data.example.org/v1/demo/export
  ```

- **Import it** into an operational server (admin only). The community must not exist there yet, its name must be a valid community name, and no member may have this server's admin's handle. What the exported admin owned becomes this server's admin's; versions keep their recorded `created_by`. The import is one transaction: on any failure nothing is written (`409` when refused, `400` when the stream is damaged or the name is not valid).

  ```bash
  curl -fsS -X POST -H "Authorization: Bearer <admin token>" --data-binary @demo.tar \
    https://data.example.org/v1/communities/import
  ```

  It answers with one entry per handle: every member is `created` in the new community and signs in with the key they already hold. Identity is per community, so a member of another community on this server, even with the same handle, is unaffected.

## Verify

```bash
curl -s http://127.0.0.1:8790/v1/status
```

It answers `200` with the version, `server_id`, the `mode`, and `"postgres": "ok"` and `"s3": "ok"`; once operational, also the admin's handle and `fingerprint`. It answers `503` while PostgreSQL or the file store is down, which is what the Kubernetes readiness probe checks.

## Tear down

- **Docker, keeping the data:** `docker rm -f symposium-data`. The volume, and the key file on it, are kept; the next `docker run` on that volume skips first-boot setup and starts operational.
- **Docker, deleting everything:** `docker rm -f symposium-data && docker volume rm symposium-data`.
- **Kubernetes:** `kubectl delete -f docker/k8s-data-deployment.yml` removes everything the manifest created, the PVC and its data included (delete only the Deployment to keep the data), and `kubectl delete secret symposium-data-admin-key` removes the key.
