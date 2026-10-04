"""The toolchain's one way to the data server: it runs the `symposium-data` CLI and reads the
one JSON object each command prints (R-I1). Nothing in the toolchain makes an HTTP request to
the server itself.

Standard library only, Python 3.9+, like the rest of tools/.
"""

from __future__ import annotations

import json
import shutil
import subprocess

INSTALL = (
    "the symposium-data CLI is not on PATH: install the Symposium bundle (`make deploy-local` "
    "from a checkout, or the release's Symposium_skill.zip) and keep ~/.local/bin on PATH"
)


class DataError(Exception):
    """A CLI command that failed: `report` is the JSON object it printed."""

    def __init__(self, report: dict):
        super().__init__(report.get("error", json.dumps(report)))
        self.report = report


class SymposiumData:
    def __init__(self, program: str = "symposium-data"):
        self.program = program

    def available(self) -> bool:
        return shutil.which(self.program) is not None

    def run(self, *args) -> dict:
        """Run one CLI command in the current directory. -> its JSON object. Raises
        DataError with the CLI's report when the command fails."""
        if not self.available():
            raise DataError({"error": INSTALL})
        result = subprocess.run(
            [self.program, *map(str, args)], capture_output=True, text=True
        )
        try:
            out = json.loads(result.stdout)
        except ValueError:
            out = {"error": (result.stdout + result.stderr).strip()[-1000:]}
        if result.returncode != 0:
            raise DataError(out)
        return out
