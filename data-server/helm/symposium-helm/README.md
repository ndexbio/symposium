# symposium-helm

The Symposium Data server, the image `ndexbio/symposium-data`, on Kubernetes. The
[runbook](https://github.com/ndexbio/symposium/blob/main/data-server/RUNBOOK.md) walks
through deploying it. This page is the reference for the chart's values.

```bash
helm install symposium-data oci://registry-1.docker.io/ndexbio/symposium-helm --version <version> \
  -n symposium --create-namespace -f values.yaml
```

- **Versions.** The chart's `version` is its own; its `appVersion` is the data-server release
  it deploys, which is also the image's default tag. Each chart version is published as
  `oci://registry-1.docker.io/ndexbio/symposium-helm:<version>`, and as
  `symposium-helm-<version>.tgz` on the GitHub release `symposium-helm-v<version>`. It works
  with Helm 3.8 or later, and Helm 4. No `helm repo add` is needed.
- **One values file per install.** Pass it, with `--version`, to every `helm install` and
  `helm upgrade`, together with the admin key's `--set-file`. Don't use `--reuse-values`: on a
  chart upgrade it drops the new chart's defaults.
- **Resources.** Everything is named after the release: a Deployment of one replica, using
  the `Recreate` strategy; a ReadWriteOnce PersistentVolumeClaim on `/apps`; a Service; and,
  depending on `expose.mode`, an HTTPRoute or an Ingress, plus the admin key's Secret.

## Values

| Value | Default | Meaning |
|---|---|---|
| `image.repository` | `ndexbio/symposium-data` | The image. |
| `image.tag` | `""` | Empty means the chart's `appVersion`. |
| `image.pullPolicy` | `IfNotPresent` | |
| `storage.size` | `5Gi` | Size it to the communities' data. |
| `storage.className` | `""` | Empty means the cluster's default StorageClass. |
| `storage.keep` | `true` | `helm uninstall` keeps the volume and its data (`helm.sh/resource-policy: keep`). |
| `adminKey.handle` | `""` | The `<handle>` in `admin_pub_<handle>.key`, which `/symposium admin-config` writes. |
| `adminKey.publicKey` | `""` | That file's contents: `--set-file adminKey.publicKey=<file>`. Set it together with `handle`. |
| `adminKey.existingSecret` | `""` | Alternatively, a Secret made some other way that holds `admin_pub_<handle>.key`. The chart can't see changes to it, so restart the pod after changing it. |
| `service.type` | `ClusterIP` | Use `LoadBalancer` on Docker Desktop, which serves it on `localhost`. |
| `service.port` | `8080` | Use `8790` on Docker Desktop. |
| `expose.mode` | `none` | `none`, `gateway` or `ingress`; see below. |
| `expose.gateway.parentRefs` | `[]` | The Gateway (or Gateways) the HTTPRoute attaches to. |
| `expose.gateway.hostnames` | `[]` | For example `[data.example.org]`. |
| `expose.gateway.timeouts` | `{request: "0s", backendRequest: "0s"}` | `0s` turns the route's timeouts off, so the Data API's streams stay open. |
| `expose.ingress.className` | `""` | The IngressClass. |
| `expose.ingress.host` | `""` | Required in `ingress` mode. |
| `expose.ingress.tlsSecret` | `""` | The host's TLS certificate. Leave it empty when TLS is terminated elsewhere. |
| `expose.ingress.annotations` | `{}` | The controller's own settings for the streams. |
| `trustedProxy` | `127.0.0.1` | `SYMPOSIUM_SERVER_TRUSTED_PROXY`. When the server is exposed, set it to the network your gateway's or controller's pods run in. |
| `publicUrl` | `""` | `SYMPOSIUM_DATA_API_PUBLIC_URL`, for example `https://data.example.org`. |
| `env` | `{}` | Any other `SYMPOSIUM_*` setting, as `NAME: value`. |
| `resources` | requests of 250m CPU and 1Gi memory | PostgreSQL, SeaweedFS and the API share the one pod. |
| `podSecurityContext`, `securityContext` | `{}` | The init container runs as root to give the volume's directories to their owners, so the chart can't run in a namespace that enforces the `restricted` Pod Security Standard. |

## `expose.mode`

- **`none`:** only the Service is created. The server is reachable inside the cluster, through
  `kubectl port-forward`, or through a `LoadBalancer` Service.
- **`gateway`:** a [Gateway API](https://gateway-api.sigs.k8s.io/) HTTPRoute, attached to a
  Gateway that the cluster's operators run. The Gateway holds the hostname's TLS certificate.
  This mode needs the Gateway API in the cluster, and the chart refuses it when the API is
  missing.
- **`ingress`:** an Ingress, for clusters that expose services through an Ingress
  controller. The controller must stream responses unbuffered, with a read timeout well past
  the streams' 30-second heartbeat, set through `expose.ingress.annotations`.

## The admin key

The server starts **non-operational** until the admin key is set. To set it:

1. Run `/symposium admin-config --handle <handle> --data-server-url <url>`.
2. Add `adminKey: {handle: <handle>}` to the values file.
3. Upgrade with `--set-file adminKey.publicKey=$HOME/.symposium/admin/admin_pub_<handle>.key`.

When the key changes, the pod restarts and the server binds or rebinds it. The Secret is
mounted at `/apps/admin-key/`.
