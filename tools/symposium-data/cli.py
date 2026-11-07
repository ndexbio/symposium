"""The Python entry of the symposium-data CLI (see main.py). The skill runs it with the
interpreter of its own environment, which holds the packages in requirements.txt.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import main  # noqa: E402

sys.exit(main())
