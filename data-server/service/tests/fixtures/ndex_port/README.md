# Recorded NDEx 3.0.0 responses for the port-ndex test

These are real responses from `ndexbio/ndex-rest:3.0.0`, recorded once on 2026-10-02, so that
`tests/integration/test_port_ndex.py` can test the one-time port without an NDEx server. They
keep working after #21 removes Symposium's NDEx tools.

**How the community was built.** On the `data-store` branch, before #21, with Symposium's own
NDEx tooling:
- `server/symposium_ndex.sh` started NDEx, and `server/bootstrap.py` created the admin
  `ndex-admin` and the members `lyra` and `vega`;
- `tools/publish.py` submitted the 9 artifacts of `examples/manuscript_example`, and
  `tools/gate.py` ran after each one and accepted it into the record;
- one invalid artifact (`lyra_note_bad_v1`, which supersedes an artifact that does not exist)
  was uploaded directly, and the gate rejected it with a reply readable by `lyra`.

**What was recorded**, with the admin's credentials (which are not stored here):

| File | Request |
|---|---|
| `whoami.json` | `GET /v2/user?valid=true` |
| `admin_networks.json` | `GET /v2/user/{admin}/permission?type=NETWORK&permission=ADMIN`, the whole listing in one page |
| `networks/{uuid}.json` | `GET /v3/networks/{uuid}`, for each of the 10 networks |
| `network_permissions/{uuid}.json` | `GET /v2/network/{uuid}/permission?type=user`, for the reply |
| `users/{uuid}.json` | `GET /v2/user/{uuid}`, for each user holding a permission on the reply |

The test's stub serves these files and pages the listings itself (`start` is a page index,
`size` the page size), the way NDEx does, so the port can be run at any page size.
