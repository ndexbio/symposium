# Symposium Data server runbook

## Run with Docker

**Ephemeral.** The data is lost when the container is removed. Suitable for a local server on one machine:

```bash
docker run -d --name symposium-data -p 127.0.0.1:8790:8080 \
  -e SYMPOSIUM_DATA_REGISTRATION=open \
  ndexbio/symposium-data:<version>
```

**Persistent.** All state lives in one named volume:

```bash
docker run -d --name symposium-data --restart unless-stopped \
  -p 127.0.0.1:8790:8080 -v symposium-data:/apps \
  -e SYMPOSIUM_DATA_REGISTRATION=open \
  ndexbio/symposium-data:<version>
```

**Reachable by other machines.** Use invite mode and give the public URL. Put a TLS-terminating proxy in front, and name it in `SYMPOSIUM_DATA_TRUSTED_PROXY`:

```bash
docker run -d --name symposium-data --restart unless-stopped \
  -p 8790:8080 -v symposium-data:/apps \
  -e SYMPOSIUM_DATA_REGISTRATION=invite \
  -e SYMPOSIUM_DATA_PUBLIC_BASE_URL=https://data.example.org \
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

## Rosters and invites

The admin sets each community's roster with `PUT /v1/c/<community>/roster`; Symposium's `bootstrap.py` does this. On an `invite` server, the operator then mints one invite per member and hands it over **out of band**, never through chat:

```bash
docker exec symposium-data data-admin invite --community demo --handle lyra > lyra.invite   # single-use, 72 h
```

The member registers with that file (Symposium's `setup.py --invite-file lyra.invite`). An invite works once, only for its own handle and community, and only before it expires (`--hours N` changes the lifetime).

**Lost or compromised key:**

```bash
docker exec symposium-data data-admin rebind-key --community demo --handle lyra > lyra.invite
docker exec symposium-data data-admin suspect-after --handle lyra --at 2026-10-01T12:00:00+00:00
```

`rebind-key` retires the handle's keys and prints a fresh invite, so the member registers a new key under the same handle. `suspect-after` flags every version the handle writes after that instant: `stat` reports `"suspect": true`, and `GET /v1/whoami` reports the instant. Nothing is deleted, and attribution is kept.

## Read keys

Read keys (`sdr_…`) let a non-member read one collection, or a single file. They are minted with `POST /v1/c/<community>/<collection>/keys` by the collection's owner or the admin, or by a file's creator for that file only. The secret is shown once, at minting. The server stores only its hash, so a lost key cannot be recovered; mint a new one instead. `inbox` never takes read keys and is never public.

**Leaked key.** List the collection's keys (`GET …/keys` shows the label, creator, expiry, use count and last use, never the secret), then revoke it as the key's minter, the collection's owner or the admin. The key is refused from the very next request:

```bash
curl -X DELETE -H "Authorization: Bearer <token>" https://data.example.org/v1/keys/<key-id>
```

Removing an owner from the roster ends their control of their collections; the admin still manages them.

## Purge, the janitor and the scrub

**Purge** frees one version's content (R-B3). The version stays addressable and answers `410` with its metadata. The bytes are deleted only when no other live version shares them. The payload is marked `purging` before its bytes are touched and becomes `purged` only after they are gone; if S3 refuses, the command reports `"bytes_freed": false` and the janitor finishes the job:

```bash
docker exec symposium-data data-admin purge --cite symposium-data:<file-id>@v<n>
```

**Janitor.** It runs in the background and removes what a crash mid-write leaves behind: uploads that never completed, and name reservations that never turned into a file. Both are removed after `SYMPOSIUM_DATA_PENDING_TTL`. Normal failures are cleaned up immediately; the janitor covers a crash, and retries any S3 delete that failed. Bytes are always deleted before the row that tracks them, so every object in the bucket stays accounted for. An upload that is still streaming refreshes its timestamps (a heartbeat every TTL/3, at most every 60 s), so the janitor never expires live work.

**Scrub.** It also runs in the background, re-hashing stored content on a schedule. A mismatch is recorded, never repaired: `stat` reports `"integrity": "mismatch"`, and clients also detect it because the bytes no longer match `Repr-Digest`.

## Kubernetes or Podman

```bash
kubectl apply -f docker/k8s-data-deployment.yml        # or: podman play kube docker/k8s-data-deployment.yml
kubectl wait --for=condition=Ready pod -l app=symposium-data --timeout=420s
kubectl exec -i deploy/symposium-data -- data-admin init --admin <admin-handle> --pubkey - < admin.pub.jwk
```

- **Storage:** the manifest uses one ReadWriteOnce PVC, so the Deployment runs a single replica with the `Recreate` strategy.
- **Before applying:** edit the PVC size, the Ingress host and TLS secret, and `SYMPOSIUM_DATA_PUBLIC_BASE_URL`. Pin the image to a released version.
- **Validating the manifest:** `docker run --rm -v "$PWD/docker:/m:ro" ghcr.io/yannh/kubeconform:v0.6.7 -strict -summary /m/k8s-data-deployment.yml`. The `make test` integration suite runs this same check.

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

  It prints one line per handle. `created` means the member signs in with the key they already hold. `unchanged` means this server already had that key. `keys merged` means this server already had the handle with a different key: that key stays active, and the exported keys are added as retired, so attribution still resolves. Use `rebind-key` if a merge was not expected. A key that belongs to a different handle on this server refuses the import.
- **Tear down without losing data:** `docker rm -f symposium-data`. The volume is kept, and the next `docker run` on that volume skips first-boot setup.
- **Delete everything:** `docker rm -f symposium-data && docker volume rm symposium-data`.
