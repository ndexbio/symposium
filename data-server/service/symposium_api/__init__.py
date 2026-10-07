"""The Symposium API: `/api/v1`, the record at the level of the specification's model.

`generated/` is generated from `api/openapi.yaml` by `codegen/generate.py` and never edited by
hand. The rest of this package is the hand-written implementation behind the generated service
interface: authorization from the contract (`authz`, `contract`), API keys (`keys`), the
derived index (`index`), the streams (`streams`) and the operations (`service`).
`symposium_server` mounts it on the data server's app.
"""
