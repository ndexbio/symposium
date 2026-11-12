"""The record's routes of `/v1`: the community record at the level of the specification's
model, generated from the contract.

`generated/` is generated from `api/openapi.yaml` by `codegen/generate.py` and never edited by
hand. The rest of this package is the hand-written implementation behind the generated service
interface: the derived index (`index`), the streams (`streams`) and the operations (`service`).
Access is `symposium_data.access`'s, as for every route. `symposium_server` mounts it on the
data server's app.
"""
