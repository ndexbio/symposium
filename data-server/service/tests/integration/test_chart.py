"""The Helm chart, helm/symposium-helm, without a cluster: it lints, every way it is meant to be
installed renders manifests kubeconform accepts, what it renders holds what the server needs,
and the settings that make no sense together are refused with a message. Helm and kubeconform
run as pinned containers, so Docker is all this needs. The chart on a live cluster is
tests/k8s (make test K8S=true)."""

from pathlib import Path

import pytest
import yaml
from harness import docker

DATA_SERVER = Path(__file__).resolve().parents[3]
CHART = DATA_SERVER / "helm" / "symposium-helm"
HELM = "alpine/helm:4.3.0"
KUBECONFORM = "ghcr.io/yannh/kubeconform:v0.6.7"
# the HTTPRoute's schema (Gateway API v1.6.1), from a pinned commit of the CRDs catalog
CRDS = (
    "https://raw.githubusercontent.com/datreeio/CRDs-catalog/"
    "041baf4c1d3740ca21461cab765e7432ecd073ef/"
    "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
)
GATEWAY_API = "gateway.networking.k8s.io/v1/HTTPRoute"
KEY = '{"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"}\n'

GATEWAY = {
    "expose": {
        "mode": "gateway",
        "gateway": {
            "parentRefs": [{"name": "public", "namespace": "gateways"}],
            "hostnames": ["data.example.org"],
        },
    },
    "publicUrl": "https://data.example.org",
    "trustedProxy": "10.244.0.0/16",
}
INGRESS = {
    "expose": {
        "mode": "ingress",
        "ingress": {
            "className": "traefik",
            "host": "data.example.org",
            "tlsSecret": "data-example-org-tls",
            "annotations": {"example.org/stream": "unbuffered"},
        },
    }
}
# every way the chart is meant to be installed: the runbook's
INSTALLS = {
    "defaults": ({}, ()),
    "docker desktop": ({"service": {"type": "LoadBalancer", "port": 8790}}, ()),
    "gateway": (GATEWAY, ("--api-versions", GATEWAY_API)),
    "ingress": (INGRESS, ()),
    "admin key": (
        {"adminKey": {"handle": "demo-admin"}},
        ("--set-file", "adminKey.publicKey=/values/admin_pub_demo-admin.key"),
    ),
}


def helm(tmp_path, command, values, *args, check=True):
    """`helm <command>` on the chart with `values` as its values file, in the pinned Helm
    container; the key file is beside the values, at /values/admin_pub_demo-admin.key."""
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values))
    (tmp_path / "admin_pub_demo-admin.key").write_text(KEY)
    return docker(
        "run",
        "--rm",
        "-v",
        f"{CHART}:/chart:ro",
        "-v",
        f"{tmp_path}:/values:ro",
        HELM,
        command,
        *(["symposium-data"] if command == "template" else []),
        "/chart",
        "--namespace",
        "symposium",
        "-f",
        "/values/values.yaml",
        *args,
        check=check,
    )


def render(tmp_path, values, *args) -> dict:
    """The manifests the chart renders, by kind."""
    out = helm(tmp_path, "template", values, *args).stdout
    return {doc["kind"]: doc for doc in yaml.safe_load_all(out) if doc}


def refusal(tmp_path, values, *args) -> str:
    result = helm(tmp_path, "template", values, *args, check=False)
    assert result.returncode != 0, result.stdout
    return result.stderr


def pod(manifests) -> dict:
    return manifests["Deployment"]["spec"]["template"]


def chart_yaml() -> dict:
    return yaml.safe_load((CHART / "Chart.yaml").read_text())


@pytest.mark.parametrize("install", INSTALLS)
def test_the_chart_lints_and_renders_valid_manifests(tmp_path, install):
    values, args = INSTALLS[install]
    # `helm lint` cannot be told a cluster has the Gateway API (--api-versions is template's
    # alone), so the gateway install is checked by its render below
    if "--api-versions" not in args:
        linted = helm(tmp_path, "lint", values, "--strict", *args, check=False)
        assert linted.returncode == 0, linted.stdout + linted.stderr
    rendered = helm(tmp_path, "template", values, *args).stdout
    result = docker(
        "run",
        "-i",
        "--rm",
        KUBECONFORM,
        "-strict",
        "-summary",
        "-schema-location",
        "default",
        "-schema-location",
        CRDS,
        input=rendered,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Invalid: 0, Errors: 0" in result.stdout, result.stdout


def test_the_defaults_deploy_the_charts_own_release_of_the_server(tmp_path):
    manifests = render(tmp_path, {})
    assert sorted(manifests) == ["Deployment", "PersistentVolumeClaim", "Service"]
    spec = pod(manifests)["spec"]
    image = f"ndexbio/symposium-data:{chart_yaml()['appVersion']}"
    assert [c["image"] for c in spec["initContainers"] + spec["containers"]] == [
        image
    ] * 2
    deployment = manifests["Deployment"]
    assert deployment["metadata"]["name"] == "symposium-data"
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}
    [server] = spec["containers"]
    assert server["args"] == ["--api-server", "--postgres", "--seaweed"]
    assert server["startupProbe"]["httpGet"]["path"] == "/v1/status"
    assert "livenessProbe" not in server  # a 503 is a dependency down, not a hung pod


def test_the_volume_outlives_an_uninstall(tmp_path):
    pvc = render(tmp_path, {})["PersistentVolumeClaim"]
    assert pvc["metadata"]["annotations"] == {"helm.sh/resource-policy": "keep"}
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
    claim = pod(render(tmp_path, {}))["spec"]["volumes"][0]["persistentVolumeClaim"]
    assert claim == {"claimName": pvc["metadata"]["name"]}


def test_the_admin_key_is_a_secret_mounted_where_the_server_reads_it(tmp_path):
    values, args = INSTALLS["admin key"]
    manifests = render(tmp_path, values, *args)
    secret = manifests["Secret"]
    assert secret["stringData"] == {"admin_pub_demo-admin.key": KEY}
    spec = pod(manifests)["spec"]
    volume = next(v for v in spec["volumes"] if v["name"] == "admin-key")
    assert volume["secret"] == {
        "secretName": secret["metadata"]["name"],
        "optional": True,
    }
    mount = next(
        m for m in spec["containers"][0]["volumeMounts"] if m["name"] == "admin-key"
    )
    assert mount == {
        "name": "admin-key",
        "mountPath": "/apps/admin-key",
        "readOnly": True,
    }


def test_without_a_key_nothing_is_made_and_the_server_starts_non_operational(tmp_path):
    manifests = render(tmp_path, {})
    assert "Secret" not in manifests
    volume = next(
        v for v in pod(manifests)["spec"]["volumes"] if v["name"] == "admin-key"
    )
    assert volume["secret"]["optional"] is True


def test_a_new_admin_key_restarts_the_pod(tmp_path):
    """The pod template carries a checksum of the key: a new key is a new template, which
    Kubernetes rolls out, and the server reads the key at start-up."""

    def checksum(handle, key):
        (tmp_path / "admin_pub_demo-admin.key").write_text(key)
        values = {"adminKey": {"handle": handle, "publicKey": key}}
        return pod(render(tmp_path, values))["metadata"]["annotations"][
            "checksum/admin-key"
        ]

    first = checksum("demo-admin", KEY)
    assert checksum("demo-admin", KEY) == first
    assert checksum("demo-admin", KEY.replace("11qY", "22qY")) != first
    assert checksum("other-admin", KEY) != first


def test_the_gateway_route_keeps_the_data_apis_streams_open(tmp_path):
    route = render(tmp_path, GATEWAY, "--api-versions", GATEWAY_API)["HTTPRoute"]
    assert route["spec"]["parentRefs"] == [{"name": "public", "namespace": "gateways"}]
    assert route["spec"]["hostnames"] == ["data.example.org"]
    [rule] = route["spec"]["rules"]
    assert rule["timeouts"] == {"request": "0s", "backendRequest": "0s"}
    assert rule["backendRefs"] == [{"name": "symposium-data", "port": 8080}]


def test_the_ingress_carries_only_the_controllers_own_settings(tmp_path):
    ingress = render(tmp_path, INGRESS)["Ingress"]
    assert ingress["metadata"]["annotations"] == {"example.org/stream": "unbuffered"}
    assert ingress["spec"]["ingressClassName"] == "traefik"
    assert ingress["spec"]["tls"] == [
        {"hosts": ["data.example.org"], "secretName": "data-example-org-tls"}
    ]


@pytest.mark.parametrize(
    "values, args, message",
    [
        (GATEWAY, (), "this cluster has no Gateway API"),
        (
            {"expose": {"mode": "gateway"}},
            ("--api-versions", GATEWAY_API),
            "needs expose.gateway.parentRefs",
        ),
        ({"expose": {"mode": "ingress"}}, (), "needs expose.ingress.host"),
        ({"adminKey": {"handle": "demo-admin"}}, (), "set without its key"),
        ({"adminKey": {"publicKey": KEY}}, (), "set without its handle"),
        (
            {
                "adminKey": {
                    "existingSecret": "s",
                    "handle": "demo-admin",
                    "publicKey": KEY,
                }
            },
            (),
            "not both",
        ),
        ({"adminKey": {"handle": "not a handle"}}, (), "does not match pattern"),
    ],
    ids=[
        "gateway, no gateway api",
        "gateway, no parent",
        "ingress, no host",
        "a handle, no key",
        "a key, no handle",
        "two keys",
        "a bad handle",
    ],
)
def test_settings_that_make_no_sense_together_are_refused(
    tmp_path, values, args, message
):
    assert message in refusal(tmp_path, values, *args)
