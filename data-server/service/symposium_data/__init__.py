"""Symposium Data: versioned file storage and sharing for Symposium communities."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from pathlib import Path

API_VERSION = "1"

# Written by the image build from the DATA_VERSION build argument (the release tag or the
# make TAG); when absent, the installed package's own version is reported.
VERSION_FILE = Path("/opt/symposium-data/VERSION")


def version(version_file: Path = VERSION_FILE) -> str:
    try:
        stamped = version_file.read_text().strip()
    except OSError:
        stamped = ""
    if stamped:
        return stamped
    try:
        return _package_version("symposium-data")
    except PackageNotFoundError:
        return "0+unknown"
