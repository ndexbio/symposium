# Symposium Data server runbook

## Run with Docker

**Ephemeral.** The data is lost when the container is removed. Suitable for a local server on one machine:

```bash
docker run -d --name symposium-data -p 127.0.0.1:8790:8080 \
  ndexbio/symposium-data:<version>
```

**Persistent.** All state lives in one named volume:

```bash
docker run -d --name symposium-data --restart unless-stopped \
  -p 127.0.0.1:8790:8080 -v symposium-data:/apps \
  ndexbio/symposium-data:<version>
```

**Reachable by other machines.** Put a TLS-terminating proxy in front, and name it in `SYMPOSIUM_DATA_TRUSTED_PROXY`. Members join the same way as on a local server: by invite.

```bash
docker run -d --name symposium-data --restart unless-stopped \
  -p 8790:8080 -v symposium-data:/apps \
  -e SYMPOSIUM_DATA_TRUSTED_PROXY=<proxy address> \
  ndexbio/symposium-data:<version>
```

The first line of the container log is `symposium-data <version>`.

## Initialize the admin

A new server starts **uninitialized**: `GET /v1/status` reports `"initialized": false`. Only the admin's **public** key goes to the server host. The private key stays on the operator's machine.

```bash
docker exec -i symposium-data data-admin init --admin <admin-handle> --pubkey - < admin.pub.jwk
```

`init` prints the key's fingerprint, which is its RFC 7638 thumbprint. Compare it with the fingerprint shown on the operator's machine. `init` works only once; a second call exits with status 2 and changes nothing.

## Communities, rosters and invites

One server hosts many communities. The admin creates each with `POST /v1/communities {name}` (1–20 letters, digits or underscores; unique ignoring case), then manages its roster one handle at a time: `POST /v1/<community>/roster/<handle>` adds a member (idempotent; adding never removes anyone), `DELETE` removes one, and `GET /v1/<community>/roster` lists each member with whether it has registered and when its pending invite expires. Symposium's `bootstrap.py` does this. Identity is per community: a member registers separately, with its own key, in each community it joins.

**Members join only by invite**, on a local server as on a remote one. The admin issues one per member with `POST /v1/<community>/invites {handle, hours?}` and hands it over **out of band**, never through chat:

- An invite works once, only for its own handle and community, and only before it expires (72 h by default).
- Issuing a new invite for a handle revokes its earlier unused one, so only the newest works. Removing a handle from the roster revokes its pending invite too.
- `GET /v1/<community>/invites` lists the pending invites, secret included, so the admin can hand one over again. An invite stops being retrievable, and its secret is erased, the moment it is used, expires or is revoked. Export never includes invites.

The member registers with it (Symposium's `setup.py --invite-file`). On the server host, `data-admin invite --community demo --handle lyra > lyra.invite` issues one the same way.

**Lost or compromised key:**

```bash
docker exec symposium-data data-admin rebind-key --community demo --handle lyra > lyra.invite
docker exec symposium-data data-admin suspect-after --community demo --handle lyra --at 2026-10-01T12:00:00+00:00
```

`rebind-key` retires the handle's keys and prints a fresh invite, so the member registers a new key under the same handle. `suspect-after` flags every version the handle writes after that instant: `stat` reports `"suspect": true`, and `GET /v1/<community>/whoami` reports the instant. Nothing is deleted, and attribution is kept.

## Read keys

Read keys (`sdr_…`) let a non-member read one collection, or a single file. They are minted with `POST /v1/<community>/collections/<collection>/keys` by the collection's owner or the admin, or by a file's creator for that file only. The secret is shown once, at minting. The server stores only its hash, so a lost key cannot be recovered; mint a new one instead. `inbox` never takes read keys and is never public.

**Leaked key.** List the collection's keys (`GET …/keys` shows the label, creator, expiry, use count and last use, never the secret), then revoke it as the key's minter, the collection's owner or the admin. The key is refused from the very next request:

```bash
curl -X DELETE -H "Authorization: Bearer <token>" https://data.example.org/v1/<community>/keys/<key-id>
```

Removing an owner from the roster ends their control of their collections; the admin still manages them.

## Purge, the janitor and the scrub

**Purge** frees one version's content (R-B3). The version stays addressable and answers `410` with its metadata. The bytes are deleted only when no other live version shares them. The payload is marked `purging` before its bytes are touched and becomes `purged` only after they are gone; if S3 refuses, the command reports `"bytes_freed": false` and the janitor finishes the job:

```bash
docker exec symposium-data data-admin purge --cite symposium-data:<file-id>@v<n>
```

**Janitor.** It runs in the background and removes what a crash mid-write leaves behind: uploads that never completed, and name reservations that never turned into a file. Both are removed after `SYMPOSIUM_DATA_PENDING_TTL`. Normal failures are cleaned up immediately; the janitor covers a crash, and retries any S3 delete that failed. Bytes are always deleted before the row that tracks them, so every object in the bucket stays accounted for. An upload that is still streaming refreshes its timestamps (a heartbeat every TTL/3, at most every 60 s), so the janitor never expires live work.

**Scrub.** It also runs in the background, re-hashing stored content on a schedule. A mismatch is recorded, never repaired: `stat` reports `"integrity": "mismatch"`, and clients also detect it because the bytes no longer match `Repr-Digest`.

## Port an existing community (port-ndex)

A community that already lives on NDEx is copied into a new, empty community on a running server with the port-ndex route: see `PORT_NDEX.md`.

## Kubernetes or Podman

```bash
kubectl apply -f docker/k8s-data-deployment.yml        # or: podman play kube docker/k8s-data-deployment.yml
kubectl wait --for=condition=Ready pod -l app=symposium-data --timeout=420s
kubectl exec -i deploy/symposium-data -- data-admin init --admin <admin-handle> --pubkey - < admin.pub.jwk
```

- **Storage:** the manifest uses one ReadWriteOnce PVC, so the Deployment runs a single replica with the `Recreate` strategy.
- **Before applying:** edit the PVC size, and the Ingress host and TLS secret. Pin the image to a released version.
- **Validating the manifests:** `docker run --rm -v "$PWD/docker:/m:ro" ghcr.io/yannh/kubeconform:v0.6.7 -strict -summary /m/k8s-data-deployment.yml`. The `make test` integration suite runs this same check.

## Verify

```bash
curl -s http://127.0.0.1:8790/v1/status
docker exec symposium-data data-admin status
docker exec symposium-data supervisorctl -c /tmp/supervisord.conf status    # data-api, postgres, seaweed RUNNING
```

## Back up and tear down

- **Back up:** everything is in the `/apps` volume (or PVC). Stop the container, then copy or snapshot the volume.
- **Export one community** while the server runs. The export is one consistent snapshot: rows, read keys (hashes only), the members' public keys, and every stored payload. Invites are not included.

  ```bash
  docker exec symposium-data data-admin export --community demo > demo.tar
  ```

- **Import it** into an initialized server whose admin has the **same handle** (its own key is fine: this server's admin keys always win). The community must not exist there yet. The import is one transaction: on any failure nothing is written (exit 2 when refused, 1 when the stream is damaged).

  ```bash
  docker exec -i symposium-data data-admin import < demo.tar
  ```

  It prints one line per handle: every member is `created` in the new community and signs in with the key they already hold. Identity is per community, so a member of another community on this server, even with the same handle, is unaffected.
- **Tear down without losing data:** `docker rm -f symposium-data`. The volume is kept, and the next `docker run` on that volume skips first-boot setup.
- **Delete everything:** `docker rm -f symposium-data && docker volume rm symposium-data`.
