"""The worked record cites its source files on the data server, in the form the profile gives
(`tools/CANONICAL.md` §3): each `download` Content holds one citation, the file's sha256 and
how to get it."""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from symposium_rules.validate import method_of  # noqa: E402

EXAMPLES = REPO / "examples"
# the citation as the client parses it (`CITATION` in tools/symposium-data/main.py)
CITATION = re.compile(r"^symposium-data:([0-9a-fA-F-]{36})@v(\d+)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# a file store reached by a path on the reader's machine
LOCAL_STORE = re.compile(
    r"stores\.json|SYMPOSIUM_STORE_ROOT|MANIFEST\.json|`community` store", re.IGNORECASE
)


def downloads() -> list:
    found = []
    for path in sorted((EXAMPLES / "record").glob("*.json")):
        for obj in json.loads(path.read_text(encoding="utf-8")).get("objects", []):
            if (
                obj.get("type") == "Content"
                and method_of(obj.get("name")) == "download"
            ):
                found.append((path.name, obj))
    return found


def test_every_download_in_the_worked_record_cites_a_file_on_the_data_server():
    found = downloads()
    assert found, "the worked record holds no `download` Content"
    for name, obj in found:
        where = f"{name}: Content '{obj['name']}'"
        assert CITATION.match(obj.get("location", "")), f"{where}: location"
        assert SHA256.match(obj.get("sha256", "")), f"{where}: sha256"
        assert obj.get("access_method"), f"{where}: access_method"
    cited = [obj["location"] for _, obj in found]
    assert len(set(cited)) == len(cited), "one file per `download` Content"


def test_the_examples_name_no_file_store_on_the_readers_machine():
    hits = [
        f"{path.relative_to(REPO)}: {match.group(0)}"
        for path in sorted(EXAMPLES.rglob("*"))
        if path.is_file() and path.suffix in (".json", ".md")
        for match in LOCAL_STORE.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not hits, hits
