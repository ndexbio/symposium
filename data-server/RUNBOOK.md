# Symposium Data server runbook

The Symposium Data server is one image, [`ndexbio/symposium-data` on Docker Hub](https://hub.docker.com/r/ndexbio/symposium-data). You run it with Docker, or on Kubernetes with its Helm chart, and nothing is built locally. Nobody needs a shell on it: every administrative operation is a route, which Symposium's CLI calls for whoever holds the access role it takes, and the server's root user is bound from a key file you give the server.

## 1. Choose where it runs

| Where | Good for | How | The URL members use |
|---|---|---|---|
| **Your machine, Docker** | a personal community, or trying Symposium | `docker run` (§4) | `http://127.0.0.1:8790` |
| **Your machine, Kubernetes on Docker Desktop** | rehearsing a cluster deployment on your machine | the Helm chart (§5.1) | `http://localhost:8790` |
| **A remote Kubernetes cluster** | a shared community that peers anywhere can reach | the Helm chart, behind a Gateway or an Ingress (§5.2) | `https://<your host>` |

One server hosts many communities. If your community lives on NDEx today, deploy the server first, then move it with the port-ndex (§6).

## 2. Before you start

- **The version.** `/symposium --help` names the image the skill was built for (`data_server_image`): run that version. On Kubernetes, the chart's `appVersion` is the image it deploys, and the default.
- **The root key.** `/symposium admin-config --handle <handle> --data-server-url <url>` makes root's key on your machine and writes its **public** key file, `admin_pub_<handle>.key`, under `~/.symposium/admin/`. It also prints the key's fingerprint and sets up root's server-wide session. The private key stays on your machine.
- **Every new server starts non-operational.** `GET /v1/status` answers `"mode": "non-operational"`, and every other route answers `501`, until the root key file is in place. Placing it is the last step of every deployment below.
- **After that,** root delegates: it invites server admins, who create communities, each run by its own community admin (§8).

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
2. **Give it the root key.** Run `admin-config` against `http://127.0.0.1:8790`, then:

   ```bash
   cp ~/.symposium/admin/admin_pub_<handle>.key $HOME/symposium-data/
   docker restart symposium-data
   ```

   Without a mount, use `docker cp ~/.symposium/admin/admin_pub_<handle>.key symposium-data:/apps/` instead.
3. **Check it:** `curl -s http://127.0.0.1:8790/v1/status` reports `"mode": "operational"`, `"root"` with your handle, and the fingerprint `admin-config` showed.

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

- **Streams.** The API's streams (Server-Sent Events) stay open for hours. The chart turns the route's timeouts off for them, and gateways stream responses unbuffered by default. The stream's heartbeat (`SYMPOSIUM_SERVER_STREAM_HEARTBEAT`, 30 seconds by default) keeps it inside any idle timeout longer than that.
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

The controller must stream responses unbuffered, with a read timeout well past the streams' heartbeat, and accept request bodies as large as the files members upload:
- **NGINX Ingress Controller (F5):** `nginx.org/proxy-buffering: "false"`, `nginx.org/proxy-read-timeout: "3600s"` and `nginx.org/client-max-body-size: "0"` (its default limit is 1 MB; `"0"` lifts it, and the community's quota bounds uploads).
- **Traefik:** it streams and accepts any body size by default.
- **Any other controller:** find its equivalents in its own documentation.

**Install it** with the commands at the start of §5. Without either mode, the server is reachable inside the cluster, or from your machine with `kubectl -n symposium port-forward svc/symposium-data 8790:8080`.

### 5.3 The root key on Kubernetes

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
4. **Check it:** `GET <url>/v1/status` reports `"mode": "operational"`, `"root"` with your handle, and the fingerprint `admin-config` showed.

To change root's key later, run `admin-config --new-key` and the same `helm upgrade`.

**With `kubectl` instead of `--set-file`.** Put the key in a Secret, and name it once in the values file as `adminKey: {existingSecret: symposium-data-root-key}`; the chart then leaves the key to you:

```bash
kubectl -n symposium create secret generic symposium-data-root-key \
  --from-file=$HOME/.symposium/admin/admin_pub_<handle>.key
kubectl -n symposium rollout restart deploy/symposium-data
```

To change the key, replace the Secret (`kubectl create secret … --dry-run=client -o yaml | kubectl apply -f -`) and restart. For an install the chart does not manage, copy the file onto the volume (`kubectl -n symposium cp $HOME/.symposium/admin/admin_pub_<handle>.key <pod>:/apps/`) and restart. Use one of the three ways: two copies of the key file make the server refuse to start (`ambiguous admin key files`).

### 5.4 Upgrading

Run `helm upgrade symposium-data $CHART --version <new chart version> -n symposium -f values.yaml --set-file adminKey.publicKey=…`. The server's state is on one ReadWriteOnce volume, so it runs as one replica. Every upgrade replaces the pod rather than rolling it, which means a short outage.

### 5.5 Cluster requirements

- **Storage:** one ReadWriteOnce PersistentVolumeClaim, from the default StorageClass or `storage.className`.
- **Pod security:** the init container runs as root to give the volume's directories to their owners. A namespace that enforces the `restricted` Pod Security Standard can't run the server; `baseline` can.
- **Resources:** PostgreSQL, the file store and the API share the pod. It requests 250m CPU and 1Gi memory by default (`resources`).

## 6. Moving a community off NDEx (port-ndex)

Deploy the server and place the root key first. Then a server admin's port-ndex copies the community's record from NDEx into a new, empty community: with the skill, `/symposium port <ndex_credentials_file> <ndex_url>`.
- **What it needs:** the data server itself connects to NDEx during a port-ndex, so it needs outbound access to it.
- **The details:** [PORT_NDEX.md](PORT_NDEX.md) describes what the port-ndex copies, how to run it and what it guarantees.

## 7. The root key file and the modes

The server reads `admin_pub_<handle>.key` at every start-up, from `/apps/` or `/apps/admin-key/`. The data server's README, under "Root key", lists every case.

- **First start with the file:** the server binds that handle as its root user, holding `server-root`, with that key, and saves a backup of them under `/apps/data/config`.
- **Operational:** `/v1/status` reports `"mode": "operational"`, `"root"` with root's handle, and the key's `fingerprint`, its RFC 7638 thumbprint.
- **Non-operational:** `/v1/status` reports `"mode": "non-operational"` with a `reason`, every other route answers `501`, and the log says why. The reasons are:
  - `admin key not provided`: no key file;
  - `ambiguous admin key files`: several;
  - `admin key invalid`: a file that isn't a usable public key;
  - `admin key missing`: on a server already bound, neither the file nor its backup.

  Put the right file in place and restart; the data is untouched.
- **Changing root's key:** place the new file and restart. With Docker that is §4 step 2; on Kubernetes, §5.3. The server rebinds root, refuses the old key from then on, and leaves every other user's keys as they are. Root's handle stays the same for the life of the server: the server ignores a file naming another handle and logs an error.
- **A missing key file** on a server already bound keeps the server running: it runs from the backup and logs a warning.

## 8. Roles and access

### 8.1 The model

Every user and every API key holds **access roles**. A role is a fixed set of **grants**, and every request is checked against the grants its caller holds. The community is the caller's own: a user belongs to one community (or, as root and the server admins, to the whole server), and an API key to the community it was issued in.

| Role | Held by | What it allows |
|---|---|---|
| `server-root` | root, bound from the key file | everything, in every community, and creating server admins (`delegate`) |
| `server-admin` | server-level users root invites | everything in every community: create, import, export and port communities, run any community |
| `community-admin` | a community's users | run its community: read, write and manage every collection, invite users, assign roles, remove users, export, run the gate |
| `gate-keeper` | a community's users | read every collection, and run the gate |
| `community-member` | a community's users, and API keys | read and write its collections, manage the collections it owns, and publish; a user also reads `record`, which publishing validates against |
| `community-observer` | a community's users, and API keys | read its collections |

`community-member` and `community-observer` take a **collection value**, always given:

| Value | Written | Meaning |
|---|---|---|
| every collection | `:*` | every collection of the community |
| none by name | `:` | only the collections the user owns |
| some | `:c1,c2` | the collections named, plus the ones the user owns |

When signed in, a user always keeps access to the collections it owns. An API key reaches exactly the collections its own roles name.

| Need | Assignment |
|---|---|
| run a community | `community-admin` |
| a member who publishes and works across the community | `community-member:*` |
| a member who publishes, reads the record, and works only in collections it creates | `community-member:` |
| a read-only member | `community-observer:*` |
| a reader of some collections, a person or an application key | `community-observer:c1,c2` |
| run the gate | `gate-keeper` |

`/symposium access` shows the six roles and the caller's own roles and grants.

### 8.2 From an empty cluster to communities run by their own community admins

Each step says where it runs, who runs it, the commands, and the check that proves it worked. Root takes part in steps 1–3 only.

1. **Operator, cluster: deploy.** Install the chart as in §5, with a values file that publishes the server at its public HTTPS URL (§5.2: a Gateway or an Ingress, `publicUrl`, `trustedProxy`). Wait with `kubectl -n symposium rollout status deploy/symposium-data`.
   - Check: `curl https://<host>/v1/status` answers `"mode": "non-operational"`, reason `admin key not provided`.
2. **Root, workstation: create the root key and bind it.**
   - Run `/symposium admin-config --handle <root> --data-server-url https://<host>`. It makes root's key on the workstation, writes `admin_pub_<root>.key`, and sets up root's server-wide session.
   - Place the key file on the server one of the three ways in §5.3, then watch the start with `kubectl -n symposium rollout status deploy/symposium-data` and `kubectl -n symposium logs deploy/symposium-data | grep -i "admin key\|operational"`.
   - Check: `/v1/status` answers `"mode": "operational"`, `"root": "<root>"`, and the fingerprint `admin-config` printed.
3. **Root, workstation: delegate a server admin.**
   - Run `/symposium invite --handle <h> --access server-admin --out <h>.invite`, and hand the file over out of band.
   - Check: `/symposium invite list --out-dir <dir> --server` lists the pending invite for `<h>`.
4. **Server admin, own workstation: join.**
   - Run `/symposium setup --invite-file <h>.invite`. The key is generated there, and the server-wide session is set up.
   - Check: `/symposium access` shows `server-admin`, with every collection of every community and no `delegate`; root's `/symposium users list --server` shows `<h>` registered.
   - Root's part ends here. Only root removes this server admin later, with `/symposium users remove --handle <h> --server`.
5. **Server admin: create each community.**
   - Write `community.json` with `community`, `admin` (the community admin's handle) and `data-server-url: https://<host>` (see `server/community.example.json`), and run `/symposium bootstrap --community-file community.json`. It writes the community admin's invite file under `~/.symposium/admin/<community>/`, to hand over out of band.
   - Repeat for each further community, each with its own community admin.
   - Check: `/symposium data communities list` shows each community, and `/symposium invite list --out-dir <dir>` shows each community admin's pending invite.

Everyone from here on works from their own workstation, with the skill installed (`make deploy-local` from a clone, or the release's `Symposium_skill.zip`). Each receives an invite file out of band, as a file, and keeps it out of any chat.

6. **Community admin: join.**
   - Run `/symposium setup --invite-file <community>-<handle>.invite`. It generates the community admin's key on this machine (encrypted, in the OS keychain, or under `SYMPOSIUM_KEY_PASSPHRASE` on a headless machine), registers it with the server, which assigns `community-admin` from the stored invite, creates the session `~/.symposium/member/<community>/<handle>/` and syncs `record/`.
   - Check: `/symposium access` shows `community-admin` in `<community>`, with `read`, `write` and `manage` on every collection, and `gate`, `members` and `export`; `/symposium users list` shows the community admin registered.
7. **Community admin: invite members.**
   - Run `/symposium invite --handle <h> --access community-member:* --out <h>.invite` for each member. Use `--access community-observer:*` for a read-only member, or `--access community-member:` for a member limited to the collections it creates.
   - Hand each file over out of band.
   - Check: `/symposium invite list --out-dir <dir>` lists each pending invite and writes its file again if one is lost.
8. **Each member: join and publish.**
   - Run `/symposium setup --invite-file <h>.invite`. The key is generated on the member's machine, the server assigns the roles stored on the invite, and the session is created and synced.
   - Check: `/symposium access` shows the roles invited; the community admin's `/symposium users list` shows `<h>` registered.
   - Work: `/symposium sync` brings the record copy up to date; `/symposium validate --role <publishing role> <artifact.json>` runs the gate's own checks; `/symposium publish --role <publishing role> <artifact.json>` submits one artifact to the community's `inbox`. A member holding several sessions picks one with `/symposium use <community> <h>`.
9. **Community admin: run the gate.**
   - In the community admin's session, start `/symposium gate --watch` as a long-running background process. It polls the community's `inbox` every `SYMPOSIUM_POLL` seconds (default 30), validates each submission against the record, then accepts it (promotes it into `record`) or rejects it (a reply only the submitter reads), printing one line per decision.
   - It runs while the community admin's agent session is open. Started again, it resumes where it left off, and decides each submission once.
   - Use `/symposium gate` for a single pass, and `/symposium gate --verify` to compare the local `record/` with the server.
   - Check: the member's next `/symposium sync` shows the decision.
10. **Community admin (optional): hand the gate on.**
    - Run `/symposium assign --handle <h> --access gate-keeper`. That user runs step 9 from its own session, holding `read` and `gate`.
    - `/symposium unassign --handle <h> --access gate-keeper` stops its next gate pass.

One shared server now hosts several communities, each run by its own community admin, with no further part for root or the server admins.

### 8.3 API keys

Every key is issued from a signed-in session with `/symposium gen-api-key`, and carries access roles. A **member key** acts as the member, within the member's own grants. A **non-member key** (`--non-member`) is an identity of its own, for an outside application, and carries `community-observer` alone. Key values go to 0600 files in the session's `api-keys/`.

1. **An application reads some of a member's collections.**
   - Create the collections if needed: `/symposium data collection create --name <c1>`. The member owns what it creates.
   - Run `/symposium gen-api-key <app> --non-member --access community-observer:<c1>,<c2>`. Naming a collection the member does not own answers 403.
   - Add a collection with `/symposium assign --api-key <id> --access community-observer:<c3>`, and remove one with `/symposium unassign --api-key <id> --access community-observer:<c1>`.
   - Check: `/symposium list-api-keys` shows `community-observer: [c2, c3]`.
   - The application reads with `Authorization: Bearer $KEY`: `curl -s -H "Authorization: Bearer $KEY" https://<host>/v1/communities/<community>/collections/<c2>/changes | jq .` lists the collection's files, and `GET /v1/communities/<community>/files/<file id>/versions/latest` retrieves one. The same calls on any other collection answer 403.
2. **A script reads the whole community, as the member.**
   - Run `/symposium gen-api-key <script> --access community-observer:*`. This member key reads everything the member reads, and neither writes nor publishes.
   - A **non-member** key on `*` takes the `members` grant: a community admin issues it with `/symposium gen-api-key <app> --non-member --access community-observer:*`.
   - The script lists the record with `curl -s -H "Authorization: Bearer $KEY" https://<host>/v1/communities/<community>/artifacts | jq '.items[] | {name, type}'`, and reads one with `…/artifacts/<name>`.
3. **A member's upload script:** `/symposium gen-api-key <uploader> --access community-member:files` reads and writes `files` only; a key reaches only the collections its roles name, whatever the member owns.
4. **Refusals:** a read-only key gets 403 on a submission and on an upload. An issued key gets 403 on `gen-api-key`, `assign` and `invite`: changing access takes a signed-in user.
5. **Revoke a key.**
   - `/symposium revoke-api-key <id>`, by the key's issuer, or by a community admin for any key of the community, deletes it. Its next request answers 401, and `list-api-keys` lists it no more.
   - A new key is issued when one is needed again.
   - Another member's `revoke-api-key` on it answers 403.

### 8.4 More delegation

1. **Root creates two server admins.**
   - In root's server-wide session: `/symposium invite --handle ana --access server-admin --out ana.invite`, and the same for `ben`.
   - Ana and Ben each run `/symposium setup --invite-file` on their own workstation.
   - Check: root's `/symposium users list --server` shows both as `server-admin`; Ben's `/symposium invite --handle eve --access server-admin --out eve.invite` answers 403 (no `delegate`).
   - Each creates communities with `/symposium bootstrap`, and works in an existing one after `/symposium use-community <community>`.
   - Root removes one with `/symposium users remove --handle ana --server`. Ana's next command reports the removal; Ben and every community carry on.
2. **A community admin adds a read-only member.**
   - `/symposium invite --handle olive --access community-observer:* --out olive.invite`; Olive runs `setup`.
   - Check: Olive's `access` shows `community-observer` with `read` on every collection; `sync` and `serve` work; `publish` and `validate` are refused, naming `publish`; `/symposium data collection create` is refused, naming `write`.
   - To make Olive a full member: `/symposium assign --handle olive --access community-member:*`, then `/symposium unassign --handle olive --access community-observer`.
3. **A member changes the collections on its own key.** Lyra's member key holds `community-member:files`.
   - Add `c4`: `/symposium assign --api-key <id> --access community-member:c4`. Remove `files`: `/symposium unassign --api-key <id> --access community-member:files`.
   - Check: `list-api-keys` shows `community-member: [c4]`; the key's next upload to `c4` succeeds, and to `files` answers 403.
   - Only the key's issuer, or a community admin, changes a key; anyone else gets 403.
4. **An owner shares, then withdraws, read access to its collection.**
   - Lyra owns `c2`: `/symposium assign --handle olive --access community-observer:c2`. Olive's next read of `c2` answers 200.
   - Withdraw: `/symposium unassign --handle olive --access community-observer:c2`. Olive's next read of `c2` answers 403.
   - Lyra changes only the names she manages: unassigning a collection Mia owns, or the whole role, answers 403.
5. **A community admin removes a member.**
   - `/symposium users remove --handle lyra`.
   - Check: `users list` still shows `lyra`, marked removed with the date; her next command reports the removal; every API key she issued is deleted and answers 401; the gate's next pass skips her pending submissions as "not an active member"; her collections keep her as owner, and the community admin manages them.
   - The record keeps her authorship: her artifacts stay listed with `published_by: @lyra`, `/v1/communities/<community>/members/lyra` shows `removed: true`, and artifacts citing `@lyra` still validate.
   - Her handle stays hers: `invite --handle lyra` answers 409. A returning person joins under a new handle.
   - Removing the community's last community admin answers 409: appoint another first.

### 8.5 Changing someone's access

People's access changes over time: a student starts as a reader and later publishes, a colleague takes over running the gate, a community admin hands the community on. Each change below is one or two commands, run by the community admin in their own session. The person affected needs no step of their own: the change applies from their next command, and `/symposium access` shows them what they now hold. `/symposium users list` shows everyone's current roles.

**Let a reader start publishing.** Olive reads everything and now publishes too:

```text
/symposium assign --handle olive --access community-member:*
/symposium unassign --handle olive --access community-observer
```

**Make a member a reader only.** Lyra keeps reading everything and stops publishing and writing:

```text
/symposium assign --handle lyra --access community-observer:*
/symposium unassign --handle lyra --access community-member
```

**Limit a member to certain collections.** Lyra works across the whole community and should now work only in `c1` and the collections she creates. Adding a collection to "every collection" leaves it at every collection, so first set her to her own collections only, then add `c1`:

```text
/symposium assign --handle lyra --access community-member:
/symposium assign --handle lyra --access community-member:c1
```

`c1` must already exist. She still reads the community's record, which every member needs in order to publish.

**Open a member up to the whole community.** Lyra works in `c1` only and should now work everywhere:

```text
/symposium assign --handle lyra --access community-member:*
```

**Hand the gate to someone else.** Mia runs the gate from now on, from her own session:

```text
/symposium assign --handle mia --access gate-keeper
```

Mia keeps any other role she holds, so she can still publish as a member. To stop her running the gate, `/symposium unassign --handle mia --access gate-keeper`; her gate stops at its next pass and says so.

**Add a second community admin.** Two people can run a community together:

```text
/symposium assign --handle mia --access community-admin
```

Publishing comes with the member role, so if Mia also publishes her own work, she keeps her `community-member` role alongside.

**Step down as community admin.** Appoint the next community admin first, as above, then remove your own role:

```text
/symposium unassign --handle steward --access community-admin
```

Every community always has at least one community admin: removing the last one is refused, with a message saying to appoint another first.

**Change a server admin (root only).** Root removes a server admin's role with `/symposium unassign --handle ana --server --access server-admin`, or removes the person entirely with `/symposium users remove --handle ana --server`. A new server admin always joins by invite, as in §8.2.

**Members share their own collections.** A member who created a collection can let a colleague read it, and take that back, without the community admin: `/symposium assign --handle olive --access community-observer:c2`, then `/symposium unassign --handle olive --access community-observer:c2`. This is the only change a member makes to someone else's access.

### 8.6 Commands

| Command | Does | Takes |
|---|---|---|
| `access` | the six roles, and your own roles and grants | any user |
| `invite --handle <h> --access <role>[:<collections>] … --out <file>` | an invite file; the server applies its roles when `<h>` joins | `members` in the community, or `delegate` for `server-admin` |
| `invite list --out-dir <dir>` | every pending invite, written again as files | `members` |
| `assign`, `unassign` `(--handle <h> \| --api-key <id>) --access …` | add or remove roles, or some collections of one | per role: `members`; `manage` on each named collection for `community-observer:<names>`; `delegate` for `server-admin` |
| `users list` | every user of the community, removed ones marked, with roles, and the server-level users | any user of the community (`delegate` with `--server`) |
| `users remove --handle <h>` | remove a user: a tombstone | `members` (`delegate` with `--server`) |
| `gen-api-key`, `list-api-keys`, `revoke-api-key` | issued keys, with their roles | a signed-in user |
| `rebind-key --handle <h> --out <file>` | retire a user's keys, and a fresh invite for the same roles | `members` |
| `suspect-after --handle <h> --at <time>` | flag the user's writes after an instant | `members` |
| `use-community <community>` | a server-level user's session for an existing community | a server-level user |

### 8.7 What refuses an action

- **Assignment authority:** each role is assigned by whoever holds what it takes (§8.6); `server-root` is assigned by none.
- **Key limits:** a key carries only `community-member` or `community-observer`, never more than its issuer holds, and only its issuer or a community admin changes it.
- **The last community admin:** removing or demoting it answers 409.
- **`inbox`:** a submission takes `publish`, a reply takes `gate`, and nothing else goes in.

### 8.8 Other operations

- **Communities.** Names are 1–20 letters, digits or underscores, unique ignoring case. Each community's routes are under `/v1/communities/<community>/…`, and its API keys and file ids are refused in any other. Content is deduplicated within a community, and quota is per member per community.
- **A user's lost or compromised key.** `/symposium rebind-key --handle <h> --out <file>` retires the user's keys and writes a fresh invite that registers a new key with the same roles. `/symposium suspect-after --handle <h> --at 2026-10-01T12:00:00+00:00` flags every version the user wrote after that instant (`"suspect": true` in `stat`); the versions stay.
- **Public collections:** `/symposium data collection set-public --collection <c> --public` opens a collection to reads with no key. `inbox` stays private.
- **Browser apps:** list the origins they are served from in `SYMPOSIUM_SERVER_CORS_ORIGINS` (with Helm, the `corsOrigins` value).

## 9. Maintenance

- **Purge** frees one version's content, with `manage` on its collection.
  - **What stays:** the version stays addressable and answers `410` with its metadata.
  - **What goes:** its bytes are deleted only when no other live version shares them. If the file store refuses, the route reports `"bytes_freed": false` and the janitor finishes the job.

  ```bash
  curl -X DELETE -H "Authorization: Bearer <session key>" https://data.example.org/v1/communities/<community>/files/<file-id>/versions/<n>
  ```

- **The janitor** runs in the background. It removes what a crash mid-write leaves behind (uploads that never completed, names reserved but never used) once they are older than `SYMPOSIUM_SERVER_PENDING_TTL`, and retries failed deletes. Work in progress keeps refreshing its timestamps, so the janitor never removes it.
- **The scrub** re-hashes stored content on a schedule. It records a mismatch and never repairs one: `stat` reports `"integrity": "mismatch"`.
- **Back up** with export, which works however the server runs. It exports one community, with `export` (a community admin, or a server admin), while the server runs: one consistent snapshot of its users, their roles, its rows and its payloads, without invites or API keys.

  ```bash
  curl -fsS -H "Authorization: Bearer <session key>" -o demo.tar https://data.example.org/v1/communities/demo/archive
  ```

  To back up the whole server, stop it and copy its `/apps` directory. On Kubernetes, that means snapshotting its PVC, where the cluster supports CSI volume snapshots.
- **Import** an export into an operational server, with `communities` (a server admin). Each user is created in the new community with its roles, and signs in with the private key file it already holds.
  - **What it needs:** the community must not exist there yet, and none of its handles may be a server-level user's, or a removed user's, there.
  - **What it does:** everything the exported root owned becomes this server's root's.
  - **On failure:** the import is one transaction, so nothing is written. It answers `409` when refused, and `400` when the stream is damaged or the name isn't valid.

  ```bash
  curl -fsS -X POST -H "Authorization: Bearer <session key>" --data-binary @demo.tar \
    -H "Content-Type: application/x-tar" https://data.example.org/v1/communities
  ```

## 10. Verify

```bash
curl -s <url>/v1/status
```

- **Healthy:** it answers `200` with the version, `server_id`, the `mode`, and `"postgres": "ok"` and `"s3": "ok"`. Once operational, it also reports `root`, root's handle, and its key's `fingerprint`.
- **Unhealthy:** it answers `503` while PostgreSQL or the file store is down. That is what the chart's readiness probe checks.
- **The contract:** the API serves its OpenAPI contract with no key, once operational (`501` before then):

  ```bash
  curl -s <url>/v1/openapi.yaml
  ```

## 11. Tear down

- **Docker, keeping the data:** `docker rm -f symposium-data`. The directory, and the key file in it, stay, so the next `docker run` on it starts operational.
- **Docker, deleting everything:** remove the container, then the directory it mounted.
- **Kubernetes, keeping the data:** `helm uninstall symposium-data -n symposium`. It keeps the volume (the PVC), which is named after the release. **The release name decides which data a server has:**
  - **Reinstalling with the same release name, in the same namespace,** mounts that kept volume again: it is the same server, with its data, already bound to its root.
  - **A different release name** gets a new, empty volume and a new server; the kept one stays untouched until you delete it.

  Before reinstalling with the same name, wait for the old pod to be gone. The uninstall returns before it has stopped, and until then it still runs on that volume:

  ```bash
  kubectl -n symposium wait --for=delete pod -l app.kubernetes.io/instance=symposium-data --timeout=5m
  ```

  It returns at once when there is no pod left.
- **Kubernetes, deleting the data:** after the uninstall, run `kubectl -n symposium delete pvc symposium-data`.
