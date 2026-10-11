"""The Helm chart on a live Kubernetes cluster: a kind cluster made for this test and deleted
after it, on this machine's Docker, with its own kubeconfig, so no other cluster is ever
touched. It installs the chart this commit packaged with the image this commit built, loaded
into the cluster and never pulled. Run it with `make test K8S=true` or
`make -C data-server helm-e2e`, which fetch the pinned helm, kind and kubectl.

The runbook's path, end to end: install, non-operational; the admin key set by `helm upgrade`,
which restarts the pod into operational mode; `helm uninstall`, which keeps the volume; and a
new install on it, which is the same server again. Every wait polls."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from symposium_data.auth import PublicKeys

IMAGE = os.environ.get("SYMPOSIUM_DATA_TEST_IMAGE", "")
CHART = os.environ.get("SYMPOSIUM_K8S_CHART", "")
HELM = os.environ.get("SYMPOSIUM_K8S_HELM", "")
KIND = os.environ.get("SYMPOSIUM_K8S_KIND", "")
KUBECTL = os.environ.get("SYMPOSIUM_K8S_KUBECTL", "")
# kind v0.33.0's node image, by digest as kind requires
NODE = "kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5"
NAMESPACE = "symposium"
RELEASE = "symposium-data"
HANDLE = "demo-admin"


class Cluster:
    """A kind cluster of its own, reached only through its own kubeconfig."""

    def __init__(self, workdir: Path):
        self.name = f"symposium-e2e-{uuid.uuid4().hex[:6]}"
        self.kubeconfig = workdir / "kubeconfig"
        self.env = {**os.environ, "KUBECONFIG": str(self.kubeconfig)}

    def run(self, *cmd, check=True, timeout=900) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [str(c) for c in cmd],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise AssertionError(
                f"{' '.join(map(str, cmd))}:\n{result.stdout}{result.stderr}"
            )
        return result

    def create(self):
        self.run(
            KIND,
            "create",
            "cluster",
            "--name",
            self.name,
            "--image",
            NODE,
            "--kubeconfig",
            self.kubeconfig,
            "--wait",
            "180s",
        )
        self.run(KIND, "load", "docker-image", IMAGE, "--name", self.name)

    def delete(self):
        self.run(
            KIND,
            "delete",
            "cluster",
            "--name",
            self.name,
            "--kubeconfig",
            self.kubeconfig,
            check=False,
        )

    def helm(self, *args):
        return self.run(HELM, *args, "--namespace", NAMESPACE)

    def kubectl(self, *args):
        return self.run(KUBECTL, "--namespace", NAMESPACE, *args)

    def pods(self) -> list[str]:
        out = self.kubectl(
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/instance={RELEASE}",
            "-o",
            "jsonpath={.items[*].metadata.name}",
        ).stdout
        return out.split()

    @contextmanager
    def forwarded(self):
        """The server's URL on this machine, through a port-forward to its Service, for as
        long as the block runs. A pod restart ends a port-forward, so each phase opens its
        own."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        forward = subprocess.Popen(
            [
                KUBECTL,
                "--namespace",
                NAMESPACE,
                "port-forward",
                f"svc/{RELEASE}",
                f"{port}:8080",
            ],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            forward.kill()
            forward.wait()


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    missing = [
        name
        for name, value in {
            "SYMPOSIUM_DATA_TEST_IMAGE": IMAGE,
            "SYMPOSIUM_K8S_CHART": CHART,
            "SYMPOSIUM_K8S_HELM": HELM,
            "SYMPOSIUM_K8S_KIND": KIND,
            "SYMPOSIUM_K8S_KUBECTL": KUBECTL,
        }.items()
        if not value
    ]
    if missing:
        pytest.fail(
            f"{', '.join(missing)} not set: run through `make -C data-server helm-e2e`"
        )
    cluster = Cluster(tmp_path_factory.mktemp("kind"))
    try:
        cluster.create()
        yield cluster
    finally:
        cluster.delete()


def status_until(url: str, predicate, message: str, timeout: float = 300) -> dict:
    """Poll /v1/status every 0.5 s until `predicate` holds for its answer."""
    deadline = time.monotonic() + timeout
    last = None
    while True:
        try:
            last = httpx.get(f"{url}/v1/status", timeout=5).json()
            if predicate(last):
                return last
        except (httpx.HTTPError, ValueError):
            pass  # the port-forward is not up yet
        assert time.monotonic() < deadline, f"{message}; last status: {last}"
        time.sleep(0.5)


def admin_key(directory: Path) -> tuple[Path, str]:
    """A public key file as `admin-config` writes it. -> (its path, its fingerprint)."""
    raw = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode(),
    }
    path = directory / f"admin_pub_{HANDLE}.key"
    path.write_text(json.dumps(jwk))
    return path, PublicKeys().thumbprint(jwk)


def test_the_chart_installs_takes_its_admin_key_and_keeps_its_data(cluster, tmp_path):
    # the image is the one loaded into the cluster: never pulled
    values = {
        "image": {"pullPolicy": "Never"},
        "storage": {"size": "1Gi"},
        "resources": {"requests": {"cpu": "100m", "memory": "512Mi"}},
    }
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump(values))
    # every install and upgrade passes the one values file, as the runbook does
    install = ("-f", values_file, "--wait", "--timeout", "8m")

    # installed: up, and non-operational until the admin key is set
    cluster.helm("install", RELEASE, CHART, "--create-namespace", *install)
    with cluster.forwarded() as url:
        status = status_until(
            url,
            lambda s: s.get("mode") == "non-operational",
            "the server never answered non-operational",
        )
        assert status["reason"] == "admin key not provided"
    [first_pod] = cluster.pods()

    # the admin key, set as the runbook sets it: the pod restarts and binds it
    key_file, fingerprint = admin_key(tmp_path)
    values["adminKey"] = {"handle": HANDLE}
    values_file.write_text(yaml.safe_dump(values))
    cluster.helm(
        "upgrade",
        RELEASE,
        CHART,
        *install,
        "--set-file",
        f"adminKey.publicKey={key_file}",
    )
    with cluster.forwarded() as url:
        status = status_until(
            url,
            lambda s: s.get("mode") == "operational",
            "the server never became operational with its key",
        )
        assert (status["admin"], status["fingerprint"]) == (HANDLE, fingerprint)
    assert first_pod not in cluster.pods()  # a new pod: the key's checksum rolled it

    # uninstalled: the volume, and the server on it, are kept
    cluster.helm("uninstall", RELEASE, "--wait")
    pvc = cluster.kubectl(
        "get", "pvc", RELEASE, "-o", "jsonpath={.status.phase}"
    ).stdout
    assert pvc == "Bound"

    # installed again, without the key: the same server, its admin bound from the volume
    values.pop("adminKey")
    values_file.write_text(yaml.safe_dump(values))
    cluster.helm("install", RELEASE, CHART, *install)
    with cluster.forwarded() as url:
        status = status_until(
            url,
            lambda s: s.get("mode") == "operational",
            "the reinstalled server lost its data",
        )
        assert (status["admin"], status["fingerprint"]) == (HANDLE, fingerprint)
