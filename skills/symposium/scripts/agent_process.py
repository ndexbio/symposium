"""The agent process, at its historical import path. It lives in `symposium.agent_process`, which
the `symposium` package ships so that a skill built on Symposium resolves the same agent session
this one does; this module is that same module object, so `import agent_process` and
`from agent_process import …` reach exactly what they always did.

The package's core is standard library only, so this import works on the interpreter running the
skill, with no virtual environment.
"""

import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
# Installed from the bundle the toolchain sits inside the skill; in a checkout it is the
# repository itself. Same resolution as main.py, which cannot be imported from here.
TOOLCHAIN = SKILL / "toolchain" if (SKILL / "toolchain").is_dir() else SKILL.parents[1]

sys.path.insert(0, str(TOOLCHAIN / "tools" / "sdk"))

from symposium import agent_process as _agent_process  # noqa: E402

sys.modules[__name__] = _agent_process
