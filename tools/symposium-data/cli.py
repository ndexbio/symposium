# /// script
# requires-python = ">=3.9"
# dependencies = ["cryptography>=42", "keyring>=24"]
# ///
"""The Python entry of the symposium-data CLI (see main.py), run by the `symposium-data` launcher:
with `uv run --script`, which reads the dependencies above, when uv is on PATH; otherwise with
`python3`, which then needs the packages in requirements.txt.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import main  # noqa: E402

sys.exit(main())
