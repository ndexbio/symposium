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
- **Tear down without losing data:** `docker rm -f symposium-data`. The volume is kept, and the next `docker run` on that volume skips first-boot setup.
- **Delete everything:** `docker rm -f symposium-data && docker volume rm symposium-data`.
