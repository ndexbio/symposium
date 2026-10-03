"""M6: the NDEx port stays contained (R-S1). The port's own end-to-end tests return with its
admin endpoint in post-M6 stage 3; this module keeps the containment check.
"""

import re
from pathlib import Path

DATA_SERVER = Path(__file__).parents[3]

NDEX = re.compile(r"(?<![a-z])ndex(?!bio/)|cx2|/v[23]/|ndexbio\.org", re.IGNORECASE)
PORT_IDENTIFIER = re.compile(r"PORT_NDEX|port-ndex|port_ndex")
PORT_FILES = {
    "service/symposium_data/port_ndex.py",
    "service/tests/integration/test_port_ndex.py",
    "docker/k8s-data-port-job.yml",
    "PORT_NDEX.md",
}
PORT_LINES = {
    "docker/scripts/start.sh",
    "service/symposium_data/admin.py",
    "README.md",
    "RUNBOOK.md",
}
SKIPPED_DIRS = {".venv", "__pycache__", ".ruff_cache", ".pytest_cache"}
IMPORTS_PORT = re.compile(
    r"^\s*(from\s+\S*port_ndex\s+import|import\s+\S*port_ndex|from\s+\.\s+import\s+port_ndex)"
)


def data_server_files():
    for path in sorted(DATA_SERVER.rglob("*")):
        rel = path.relative_to(DATA_SERVER)
        if path.is_file() and not SKIPPED_DIRS & set(rel.parts):
            try:
                yield rel.as_posix(), path.read_text().splitlines()
            except UnicodeDecodeError:
                continue


def test_ndex_stays_inside_the_port_feature():
    stray, importers = [], []
    for rel, lines in data_server_files():
        for number, line in enumerate(lines, 1):
            if IMPORTS_PORT.match(line):
                importers.append(rel)
            if rel in PORT_FILES or rel.startswith("service/tests/fixtures/ndex_port/"):
                continue
            if not NDEX.search(line) or "github.com/ndexbio/" in line:
                continue
            if rel in PORT_LINES and PORT_IDENTIFIER.search(line):
                continue
            stray.append(f"{rel}:{number}: {line.strip()}")
    assert stray == []
    assert importers == ["service/symposium_data/admin.py"]
    assert (DATA_SERVER / "PORT_NDEX.md").is_file()
