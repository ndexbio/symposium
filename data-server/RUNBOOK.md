# Symposium Data server runbook

The Symposium Data server is one image, [`ndexbio/symposium-data` on Docker Hub](https://hub.docker.com/r/ndexbio/symposium-data). You run it with Docker, or on Kubernetes with its Helm chart, and nothing is built locally. Nobody needs a shell on it: every admin operation is a route, which Symposium's CLI calls for the admin, and the admin's key is a file you give the server.

## 1. Choose where it runs

| Where | Good for | How | The URL members use |
|---|---|---|---|
| **Your machine, Docker** | a personal community, or trying Symposium | `docker run` (§4) | `http://127.0.0.1:8790` |
| **Your machine, Kubernetes on Docker Desktop** | rehearsing a cluster deployment on your machine | the Helm chart (§5.1) | `http://localhost:8790` |
| **A remote Kubernetes cluster** | a shared community that peers anywhere can reach | the Helm chart, behind a Gateway or an Ingress (§5.2) | `https://<your host>` |

One server hosts many communities. If your community lives on NDEx today, deploy the server first, then move it with the port-ndex (§6).

## 2. Before you start

- **The version.** `/symposium --help` names the image the skill was built for (`data_server_image`): run that version. On Kubernetes, the chart's `appVersion` is the image it deploys, and the default.
- **The admin key.** `/symposium admin-config --handle <handle> --data-server-url <url>` makes the admin's key on your machine and writes its **public** key file, `admin_pub_<handle>.key`, under `~/.symposium/admin/`. It also prints the key's fingerprint. The private key never leaves your machine.
- **Every new server starts non-operational.** `GET /v1/status` answers `"mode": "non-operational"`, and every other route answers `501`, until the admin key file is in place. Placing it is the last step of every deployment below.

## 3. The image

- **State:** all of it lives under `/apps`: PostgreSQL, the file store, and the service's own secrets, which are generated on first boot. With Docker that is a directory you mount; with the chart it is a PersistentVolumeClaim.
- **Port:** the API listens on `8080` inside the container. PostgreSQL and the file store never leave it.
- **Settings:** `SYMPOSIUM_*` environment variables, every one listed in the data server's README under "Configuration".
- **Version check:** the first log line is `symposium-data <version>`, and `/v1/status` reports the same version.
- **Tags:** always pin a release tag, never `:latest`.

## 4. Run it with Docker

1. **Run the server,** with its state in a directory of your machine:

   ```bash
   mkdir -p $HOME/symposium-data
   docker run -d --name symposium-data --restart unless-stopped \
     -p 127.0.0.1:8790:8080 -v $HOME/symposium-data:/apps \
     ndexbio/symposium-data:<version>
   ```

   Without the `-v` mount, the data is lost when the container is removed.
2. **Give it the admin key.** Run `admin-config` against `http://127.0.0.1:8790`, then:

   ```bash
   cp ~/.symposium/admin/admin_pub_<handle>.key $HOME/symposium-data/
   docker restart symposium-data
   ```

   Without a mount, use `docker cp ~/.symposium/admin/admin_pub_<handle>.key symposium-data:/apps/` instead.
3. **Check it:** `curl -s http://127.0.0.1:8790/v1/status` reports `"mode": "operational"`, your handle, and the fingerprint `admin-config` showed.

**Reachable by other machines.** Publish the port (`-p 8790:8080`), put a TLS-terminating proxy in front of it, and name the proxy in `-e SYMPOSIUM_SERVER_TRUSTED_PROXY=<proxy address>`. Members still join only by invite.

## 5. Run it on Kubernetes with Helm

**What you need:**
- Helm 3.8 or later, or Helm 4;
- `kubectl`, pointed at the cluster;
- a default StorageClass, or set `storage.className`.

**Getting the chart.** It is published as an OCI artifact on Docker Hub, `oci://registry-1.docker.io/ndexbio/symposium-helm`. Helm installs it straight from there: there is no `helm repo add` and no login. Its versions are the tags of [`ndexbio/symposium-helm`](https://hub.docker.com/r/ndexbio/symposium-helm/tags), and every command names one.

```bash
helm show chart  oci://registry-1.docker.io/ndexbio/symposium-helm --version <chart version>   # its appVersion is the image
helm show values oci://registry-1.docker.io/ndexbio/symposium-helm --version <chart version>   # every setting
```

There are two other sources:
- **The GitHub release.** Each chart version is also `symposium-helm-<chart version>.tgz` on the GitHub release `symposium-helm-v<chart version>`. Helm installs it from its download URL or from the downloaded file.
- **The installed skill.** The chart's source is at `~/.claude/skills/symposium/toolchain/data-server/helm/symposium-helm`. [Its README](helm/symposium-helm/README.md) is the reference for every value.

**Every install starts the same way.**
- **One values file.** Keep a single `values.yaml` for the install, and pass it, with the same `--version`, to every `helm install` and `helm upgrade`.
- **No `--reuse-values`.** On a chart upgrade it silently drops the new chart's defaults.
- **One namespace.** The commands below use the namespace `symposium` and the release `symposium-data`.

```bash
CHART=oci://registry-1.docker.io/ndexbio/symposium-helm
helm install symposium-data $CHART --version <chart version> -n symposium --create-namespace -f values.yaml
kubectl -n symposium rollout status deploy/symposium-data --timeout=10m   # a first start takes minutes
```

### 5.1 On Docker Desktop

1. **Turn on Kubernetes** in Docker Desktop's settings, then point `kubectl` at it: `kubectl config use-context docker-desktop`.
2. **Write `values.yaml`.** Docker Desktop publishes a `LoadBalancer` service on `localhost`:

   ```yaml
   service: {type: LoadBalancer, port: 8790}
   ```

3. **Install it** with the commands above. The server is at `http://localhost:8790`.

If nothing answers on `localhost:8790`, your Docker Desktop cluster type doesn't publish LoadBalancer services. Reach the server through `kubectl -n symposium port-forward svc/symposium-data 8790:8790` instead, for as long as that command runs.

### 5.2 On a remote cluster

The chart publishes the server through the **Gateway API**, Kubernetes' standard way to expose an application. It succeeds Ingress: Ingress is frozen, and its best-known controller, ingress-nginx, was retired in March 2026. The Gateway API splits exposure by who owns what:

| Resource | Who owns it | What it is |
|---|---|---|
| **GatewayClass** | the cluster, or its vendor (Envoy Gateway, Istio, Cilium, NGINX Gateway Fabric, GKE, AKS, EKS…) | which implementation runs the cluster's gateways |
| **Gateway** | the cluster's operators | the shared entry point: its listeners (`https` on 443), its hostnames and their TLS certificates |
| **HTTPRoute** | this chart | the rule "send `https://data.example.org/` to the `symposium-data` Service", attached to a Gateway |

So you only ask your cluster's operators which Gateway to attach to. TLS and the public address stay with them, and the route's behaviour, such as its timeouts, is part of the standard instead of vendor annotations.

**Why it isn't on by default:** an HTTPRoute must name a Gateway that already exists, which the chart can't guess. A cluster without the Gateway API, Docker Desktop's included, would also reject the install. So `expose.mode` defaults to `none`, and on a remote cluster you set it to `gateway`:

```yaml
expose:
  mode: gateway
  gateway:
    parentRefs: [{name: <the Gateway>, namespace: <its namespace>}]   # ask the cluster's operators
    hostnames: [data.example.org]
publicUrl: https://data.example.org
trustedProxy: <the network the Gateway's pods run in, e.g. 10.244.0.0/16>
storage: {size: 20Gi}           # size it to the communities' data; className if there is no default
```

- **Streams.** The Symposium Data API's streams (Server-Sent Events) stay open for hours. The chart turns the route's timeouts off for them, and gateways stream responses unbuffered by default. The stream's 30-second heartbeat keeps it inside any idle timeout longer than that.
- **Trusted proxy.** The server trusts `X-Forwarded-*` headers only from `trustedProxy`. Keep it to the gateway's pod network, never a range anything else can send from.
- **Refusals.** The chart refuses `gateway` mode on a cluster without the Gateway API, and says so.

**Behind an Ingress controller instead.** If the cluster exposes services through an Ingress controller, use `expose.mode: ingress`. The controller's own settings go in `annotations`:

```yaml
expose:
  mode: ingress
  ingress:
    className: <the IngressClass>
    host: data.example.org
    tlsSecret: data-example-org-tls     # empty when TLS is terminated before the controller
    annotations: {}
publicUrl: https://data.example.org
trustedProxy: <the network the controller's pods run in>
```

The streams need the controller to stream responses unbuffered, with a read timeout well past 30 seconds:
- **NGINX Ingress Controller (F5):** `nginx.org/proxy-buffering: "false"` and `nginx.org/proxy-read-timeout: "3600s"`.
- **Traefik:** it streams by default.
- **Any other controller:** find its equivalents in its own documentation.

**Install it** with the commands at the start of §5. Without either mode, the server is reachable inside the cluster, or from your machine with `kubectl -n symposium port-forward svc/symposium-data 8790:8080`.

### 5.3 The admin key on Kubernetes

1. Run `/symposium admin-config --handle <handle> --data-server-url <the server's URL>`.
2. Add the handle to `values.yaml`:

   ```yaml
   adminKey: {handle: <handle>}
   ```

3. Give the chart the key file. Pass this same `--set-file` on every later upgrade too:

   ```bash
   helm upgrade symposium-data $CHART --version <chart version> -n symposium -f values.yaml \
     --set-file adminKey.publicKey=$HOME/.symposium/admin/admin_pub_<handle>.key
   ```

   The chart stores the key in a Secret, mounted at `/apps/admin-key/`, and **restarts the server itself**.
4. **Check it:** `GET <url>/v1/status` reports `"mode": "operational"` and the fingerprint `admin-config` showed.

To change the admin's key later, run `admin-config --new-key` and the same `helm upgrade`.

### 5.4 Upgrading

Run `helm upgrade symposium-data $CHART --version <new chart version> -n symposium -f values.yaml --set-file adminKey.publicKey=…`. The server's state is on one ReadWriteOnce volume, so it runs as one replica. Every upgrade replaces the pod rather than rolling it, which means a short outage.

### 5.5 Cluster requirements

- **Storage:** one ReadWriteOnce PersistentVolumeClaim, from the default StorageClass or `storage.className`.
- **Pod security:** the init container runs as root to give the volume's directories to their owners. A namespace that enforces the `restricted` Pod Security Standard can't run the server; `baseline` can.
- **Resources:** PostgreSQL, the file store and the API share the pod. It requests 250m CPU and 1Gi memory by default (`resources`).

## 6. Moving a community off NDEx (port-ndex)

Deploy the server and place the admin key first. Then the port-ndex copies the community's record from NDEx into a new, empty community: with the skill, `/symposium port <ndex_credentials_file> <ndex_url>`.
- **What it needs:** the data server itself connects to NDEx during a port-ndex, so it needs outbound access to it.
- **The details:** [PORT_NDEX.md](PORT_NDEX.md) describes what the port-ndex copies, how to run it and what it guarantees.

## 7. The admin key file and the modes

The server reads `admin_pub_<handle>.key` at every start-up, from `/apps/` or `/apps/admin-key/`. The data server's README, under "The admin key file", lists every case.

- **First start with the file:** the server binds that handle and key, and saves a backup of them under `/apps/data/config`.
- **Operational:** `/v1/status` reports `"mode": "operational"`, the admin's handle and the key's `fingerprint`, its RFC 7638 thumbprint.
- **Non-operational:** `/v1/status` reports `"mode": "non-operational"` with a `reason`, every other route answers `501`, and the log says why. The reasons are:
  - `admin key not provided`: no key file;
  - `ambiguous admin key files`: several;
  - `admin key invalid`: a file that isn't a usable public key;
  - `admin key missing`: on a server already bound, neither the file nor its backup.

  Put the right file in place and restart; the data is untouched.
- **Changing the admin's key:** place the new file and restart. With Docker that is §4 step 2; on Kubernetes, §5.3. The server rebinds, and refuses the old key from then on. The admin's handle never changes: the server ignores a file naming another handle and logs an error.
- **A missing key file** on a server already bound is not an outage: the server runs from the backup and logs a warning.

## 8. Running communities

- **Communities.**
  - **Create:** `POST /v1/communities {name}` (admin) creates one; it is idempotent. `GET /v1/communities` lists them.
  - **Names:** 1–20 letters, digits or underscores, unique ignoring case. `status`, `communities` and `admin` are reserved.
  - **Isolation:** each community's routes are under `/v1/<community>/…`, and its tokens, read keys and file ids are refused in any other. The same handle in two communities is two identities. Content is deduplicated only within a community, and quota is per member per community.
  - **The admin** is server-wide, and its handle can never be a member's.
- **Rosters.**
  - **Add or remove:** `POST /v1/<community>/roster/<handle>` adds a member (idempotent), and `DELETE` removes one.
  - **List:** `GET /v1/<community>/roster` shows who has registered and when each pending invite expires.

  Symposium's `bootstrap` does this for you.
- **Invites.** Members join only by invite, which the admin hands over **out of band**, never through chat.
  - **Issue:** `POST /v1/<community>/invites {handle, hours?}`.
  - **Rules:** an invite works once, only for its own handle and community, until it expires (72 h by default). A new invite for a handle revokes the earlier unused one, and removing the handle from the roster revokes its pending invite.
  - **List:** `GET /v1/<community>/invites` lists the pending ones, so you can hand one over again.
  - **Register:** the member registers with Symposium's `setup`.
- **A member's lost or compromised key.** Both of these are admin only:
  - `POST /v1/<community>/owners/<handle>/rebind` retires the handle's keys and returns a fresh invite.
  - `PUT /v1/<community>/owners/<handle>/suspect-after {"at": "2026-10-01T12:00:00+00:00"}` flags every version the handle wrote after that instant (`"suspect": true` in `stat`). Nothing is deleted.
- **Read keys.** A read key (`sdr_…`) lets a non-member read one collection, or one file.
  - **Minting:** `POST /v1/<community>/collections/<collection>/keys`, by the collection's owner or the admin, or by a file's creator for that file alone.
  - **The secret:** it is shown once, and the server keeps only its hash.
  - **`inbox`:** it never takes read keys.
  - **A leaked key:** list the collection's keys (`GET …/keys`), then revoke it. The revocation takes effect from the next request:

    ```bash
    curl -X DELETE -H "Authorization: Bearer <token>" https://data.example.org/v1/<community>/keys/<key-id>
    ```

## 9. Maintenance

- **Purge** frees one version's content (R-B3), admin only.
  - **What stays:** the version stays addressable and answers `410` with its metadata.
  - **What goes:** its bytes are deleted only when no other live version shares them. If the file store refuses, the route reports `"bytes_freed": false` and the janitor finishes the job.

  ```bash
  curl -X POST -H "Authorization: Bearer <admin token>" https://data.example.org/v1/<community>/files/<file-id>/v/<n>/purge
  ```

- **The janitor** runs in the background. It removes what a crash mid-write leaves behind (uploads that never completed, names reserved but never used) once they are older than `SYMPOSIUM_SERVER_PENDING_TTL`, and retries failed deletes. Work in progress keeps refreshing its timestamps, so the janitor never removes it.
- **The scrub** re-hashes stored content on a schedule. It records a mismatch and never repairs one: `stat` reports `"integrity": "mismatch"`.
- **Back up** with export, which works however the server runs. It exports one community, admin only, while the server runs: one consistent snapshot of its rows, its read keys (hashes only), its members' public keys and its payloads, without invites.

  ```bash
  curl -fsS -H "Authorization: Bearer <admin token>" -o demo.tar https://data.example.org/v1/demo/export
  ```

  To back up the whole server, stop it and copy its `/apps` directory. On Kubernetes, that means snapshotting its PVC, where the cluster supports CSI volume snapshots.
- **Import** an export into an operational server, admin only. Each member is created in the new community and signs in with the key they already hold.
  - **What it needs:** the community must not exist there yet, and no member may have that server's admin's handle.
  - **What it does:** everything the exported admin owned becomes this server's admin's.
  - **On failure:** the import is one transaction, so nothing is written. It answers `409` when refused, and `400` when the stream is damaged or the name isn't valid.

  ```bash
  curl -fsS -X POST -H "Authorization: Bearer <admin token>" --data-binary @demo.tar \
    https://data.example.org/v1/communities/import
  ```

## 10. Verify

```bash
curl -s <url>/v1/status
```

- **Healthy:** it answers `200` with the version, `server_id`, the `mode`, and `"postgres": "ok"` and `"s3": "ok"`. Once operational, it also reports the admin's handle and `fingerprint`.
- **Unhealthy:** it answers `503` while PostgreSQL or the file store is down. That is what the chart's readiness probe checks.
- **The contract:** the Symposium Data API serves its OpenAPI contract with no credential, once operational (`501` before then):

  ```bash
  curl -s <url>/api/v1/openapi.yaml
  ```

## 11. Tear down

- **Docker, keeping the data:** `docker rm -f symposium-data`. The directory, and the key file in it, stay, so the next `docker run` on it starts operational.
- **Docker, deleting everything:** remove the container, then the directory it mounted.
- **Kubernetes, keeping the data:** `helm uninstall symposium-data -n symposium`. It keeps the volume, so a later `helm install` with the same release name and namespace is the same server, already bound to its admin.
- **Kubernetes, deleting the data:** after the uninstall, run `kubectl -n symposium delete pvc symposium-data`.
