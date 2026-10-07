"""The validator, at its historical import path. It lives in `symposium_rules.validate`, which
the data server's API shares; this module is that same module object, so `import validate`
and `from validate import …` reach exactly what they always did."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from symposium_rules import validate as _validate  # noqa: E402

sys.modules[__name__] = _validate
