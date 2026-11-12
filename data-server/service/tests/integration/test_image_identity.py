"""The ids the image runs its services under, and what it does with a cluster it cannot read.

A system account's id is assigned when the image is built, from whatever the base image
leaves free, and that moved when debian:bookworm-slim gained systemd-journal and
systemd-network: postgres went from 100 to 997. The id is written into every file of a
PostgreSQL cluster, so an image whose postgres is 997 cannot read a cluster written by one
whose postgres was 100, and an operator upgrading in place gets a server that never starts.
Two defences, one tested here and one in test_migration.py: the id is pinned so it stops
moving, and start.sh takes ownership of the volume on every boot so an id that already
moved is repaired.
"""

import pytest
from harness import IMAGE, TEST_ENV, Server, docker

# What every published image carries, and what a volume in the field is therefore owned by.
POSTGRES_UID, POSTGRES_GID = "100", "102"


def test_the_image_runs_postgres_under_the_published_id(server):
    """Pinned in the Dockerfile. Left to the package, this is whatever the base allows."""
    assert server.exec("id", "-u", "postgres").stdout.strip() == POSTGRES_UID
    assert server.exec("id", "-g", "postgres").stdout.strip() == POSTGRES_GID


def test_the_cluster_on_the_volume_belongs_to_that_id(server):
    """Ownership reaches inside the directory, not only the directory itself: postgres reads
    postgresql.conf, and a config file it cannot open stops the server."""
    owner = server.exec(
        "stat", "-c", "%u:%g", "/apps/postgres/data/postgresql.conf"
    ).stdout.strip()
    assert owner == f"{POSTGRES_UID}:{POSTGRES_GID}"


def test_a_cluster_from_another_major_is_refused_with_a_clear_message(tmp_path):
    """A major version reads only the clusters it wrote. Say which two met: the alternative
    is postgres failing on its own terms in a log nobody reads, which is how the ownership
    bug stayed invisible through two CI runs.

    Its own container: the shared one is session-scoped, and this one is made unusable."""
    if not IMAGE:
        pytest.fail(
            "SYMPOSIUM_DATA_TEST_IMAGE is not set; run through `make -C data-server test`"
        )
    broken = Server(TEST_ENV)
    try:
        broken.start()  # no key file: non-operational, but the cluster is initialised
        broken.exec("sh", "-c", "echo 15 > /apps/postgres/data/PG_VERSION")
        # Not Server.start(): the container exits at once, so no port is ever published.
        docker("rm", "-f", broken.name, check=False)
        docker("create", "--name", broken.name, "-v", f"{broken.volume}:/apps", IMAGE)
        docker("start", broken.name)
        said = broken.wait_for_log("pg_upgrade is required")
        assert "PostgreSQL 16" in said and "cluster on /apps is 15" in said
    finally:
        broken.remove()
