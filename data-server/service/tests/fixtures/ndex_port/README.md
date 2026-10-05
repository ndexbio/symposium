# Recorded NDEx 3.0.0 responses for the port-ndex test

These are responses from `ndexbio/ndex-rest:3.0.0`, so that `tests/integration/test_port_ndex.py`
can test the port without an NDEx server.

**The community they hold:** the admin `ndex-admin` and the members `lyra` and `vega`; the 9
artifacts of `examples/manuscript_example`, accepted into the record; and one rejected
submission (`lyra_note_bad_v1`, which supersedes an artifact that does not exist) with its reply,
readable by `lyra`.

**The files**, each the response to the admin's request (no credentials are stored here):

| File | Request |
|---|---|
| `whoami.json` | `GET /v2/user?valid=true` |
| `admin_networks.json` | `GET /v2/user/{admin}/permission?type=NETWORK&permission=ADMIN`, the whole listing in one page |
| `networks/{uuid}.json` | `GET /v3/networks/{uuid}`, for each of the 10 networks |
| `network_permissions/{uuid}.json` | `GET /v2/network/{uuid}/permission?type=user`, for the reply |
| `users/{uuid}.json` | `GET /v2/user/{uuid}`, for each user holding a permission on the reply |

`stub.py` serves these files, for the data server's port test and the CLI's, and pages the listings itself (`start` is a page index,
`size` the page size), the way NDEx does, so the port can be run at any page size.
