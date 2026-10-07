"""Generate the API's server code from the contract: `symposium_api/generated/`.

    python codegen/generate.py           regenerate it from ../../api/openapi.yaml
    python codegen/generate.py --check   regenerate into a scratch directory and fail if the
                                         committed code differs by a single byte

The generators are fastapi-code-generator (routers, from the templates in codegen/templates)
and datamodel-code-generator (the Pydantic v2 models), both pinned in pyproject.toml's dev
group. The output is formatted with the repository's ruff, so the committed code is exactly
what this script writes. Run it from anywhere; it works relative to its own location.
"""

from __future__ import annotations

import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
CONTRACT = SERVICE.parents[1] / "api" / "openapi.yaml"
TEMPLATES = SERVICE / "codegen" / "templates"
TARGET = SERVICE / "symposium_api" / "generated"
GENERATOR = [
    "fastapi-codegen",
    "--generate-routers",
    "--template-dir",
    str(TEMPLATES),
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--python-version",
    "3.11",
    "--use-annotated",
    "--strict-nullable",
    "--disable-timestamp",
]


def generate(output: Path) -> None:
    """Write the generated package into `output`, formatted the way the repository formats."""
    if output.exists():
        shutil.rmtree(output)
    subprocess.run(
        [*GENERATOR, "--input", str(CONTRACT), "--output", str(output)],
        check=True,
        capture_output=True,
    )
    # the header names the input as the generator saw it; make it the repository path
    for path in output.rglob("*.py"):
        text = path.read_text()
        text = text.replace(
            "#   filename:  openapi.yaml", "#   filename:  api/openapi.yaml"
        )
        path.write_text(text)
    for ruff in (["check", "--fix", "--quiet"], ["format", "--quiet"]):
        subprocess.run(["ruff", *ruff, str(output)], check=True, cwd=SERVICE)


def differences(left: Path, right: Path) -> list[str]:
    files = sorted(
        {p.relative_to(left) for p in left.rglob("*.py")}
        | {p.relative_to(right) for p in right.rglob("*.py")}
    )
    return [
        str(f)
        for f in files
        if not (left / f).is_file()
        or not (right / f).is_file()
        or not filecmp.cmp(left / f, right / f, shallow=False)
    ]


def main(argv: list[str]) -> int:
    if argv == ["--check"]:
        # inside the service and at the same relative path, so ruff applies the
        # generated package's configuration exactly as it does to the real output
        with tempfile.TemporaryDirectory(
            dir=SERVICE, prefix="codegen-check-"
        ) as scratch:
            fresh = Path(scratch) / "symposium_api" / "generated"
            generate(fresh)
            changed = differences(fresh, TARGET)
        if changed:
            print(
                "symposium_api/generated differs from api/openapi.yaml: run "
                "`uv run --project data-server/service python data-server/service/codegen/"
                f"generate.py` and commit the result. Changed: {', '.join(changed)}",
                file=sys.stderr,
            )
            return 1
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    generate(TARGET)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
