"""The Helm chart deploys this data server: its appVersion, the image tag it installs by
default, is the version the image is built with, so a data-server release can never ship
without a chart for it."""

import re
from pathlib import Path

DATA_SERVER = Path(__file__).resolve().parents[3]


def test_the_chart_deploys_this_data_server_version():
    pyproject = (DATA_SERVER / "service" / "pyproject.toml").read_text()
    chart = (DATA_SERVER / "helm" / "symposium-helm" / "Chart.yaml").read_text()
    version = re.search(r'^version = "(.+)"$', pyproject, re.MULTILINE).group(1)
    app_version = re.search(r'^appVersion: "(.+)"$', chart, re.MULTILINE).group(1)
    assert app_version == version, (
        f"Chart.yaml's appVersion is {app_version}, the data server is {version}: bump "
        "appVersion and the chart's version, and add a Symposium Helm changelog entry"
    )
