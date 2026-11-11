"""The specification's validator, as the package exposes it.

`symposium_rules` is its own distribution, which the data server also depends on, so the validator
is depended on rather than copied: this module is the public name for it, and `validate` here is
the function the gate runs. A finding carries `check`, `level` (`FAIL` or `REVIEW`) and `msg`, and
`passed` is true when none of them is a FAIL.

What this does NOT do is apply a publishing role. The role limits — which Artifact types a role may
publish, whether it may carry `import_method` — are the publishing tool's and are checked by
`Session.check`, because they need the account and the role contracts as well as the artifact.

Importing this module reaches `symposium_rules`, which a bare interpreter does not have on its
path, so the package resolves it on first use rather than at import.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

from symposium_rules.validate import passed, validate

__all__ = ["passed", "validate"]
