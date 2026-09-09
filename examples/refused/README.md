# refused/ — Artifacts that must be refused

**This is a test fixture directory. `tools/conformance.py` reads it directly,
and removing or editing a file here breaks the build.**

Every `.json` here is an Artifact that the validator must **reject**, and
`EXPECTED.json` names the reason each one must be rejected *for*. A fixture
refused for the wrong reason is a failure, not a pass — otherwise a validator
that rejected everything would score full marks.

```bash
cd tools && python3 check_refused.py ../examples/refused ../examples/record
```

`record/` is passed in as well because some fixtures are only refusable in the
presence of another Artifact — a duplicate name needs the original to collide
with, and a citation of a superseded version needs the supersession to exist.

## What each fixture is for

| Fixture | Must be refused for |
|---|---|
| `B6_ground_cites_nongroundable` | GROUND — a Ground into something declaring `groundable: false` |
| `B7_ground_cites_own_primary` | GROUND — addressing content inside its own Argument |
| `B8_ground_cites_undeclared_groundable` | GROUND — the target never declared itself groundable |
| `C6_undeclared_content_object` | ADDRESS — an address into a Content object that was not declared |
| `E5_produced_by_not_analysis` | TYPE — `produced_by` naming something that is not an Analysis |
| `H3_nongroundable_declares_groundable` | TYPE — a type that cannot be groundable saying it is |
| `H4_groundable_false_header` | GROUND — the header contradicts the declaration |
| `J3_depends_on_cycle` | C-ARG — a dependency cycle between Assertions |
| `J4_assertion_without_basis` | C-ARG — an Assertion resting on nothing |
| `J5_reference_to_later_artifact` | ORDER — citing something published afterwards |
| `J6a` / `J6b_same_instant_mutual` | ORDER — two Artifacts citing each other at the same instant (paired via `with`) |
| `J7_duplicate_name` | UNIQUE — a name already in the record |

## Adding one

A new fixture needs an entry in `EXPECTED.json` giving its `case`, its
`check`, and an `msg` fragment the validator's finding must contain — plus
`with` if it only fails alongside another fixture. The check has to be one the
validator actually emits. Run `conformance.py`
afterwards: a fixture nothing refuses, or one refused for a different reason
than declared, fails the suite.
