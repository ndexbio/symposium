# Symposium

A specification for a **CommunityRecord**: a structured record in which members of a scientific community — human or agent — publish immutable Artifacts, and every claim is connected to the material it rests on.

The record is not a chat log and not a pile of documents. It is a graph in which a reader can take any conclusion, follow it down to the measurement it depends on, and see what the author claimed as a test, what they merely built upon, and what they could not address at all and asked the community to grant.

What the specification does **not** do is as much the point as what it does. It does not decide whether claims are true, score reasoning, rank Arguments, or model reputation. It makes the basis of a claim visible, and leaves the judgment with the reader.

**[`spec/symposium_specification.md`](spec/symposium_specification.md)** is the normative document. It is short, and reading it once is the fastest way to understand what is here.

## Start here

**[`docs/quickstart.md`](docs/quickstart.md)** — How to read a CommunityRecord with nothing installed, check the toolchain's own conformance suite, and run the publish loop against your own local server. Reviewing the example CommunityRecord from the manuscript is a better place to start than the specification itself.

**[`docs/server-setup.md`](docs/server-setup.md)** — Create a Symposium community: the one-time procedure for standing up a Symposium server and admitting its first Members.

## Layout

```
spec/symposium_specification.md   the normative document
tools/
  validate.py                     the conformance validator
  conformance.py                  everything that checks the toolchain, one command
  validate_record.py              validate a whole record in publication order
  check_refused.py  test_gate.py  the refusal fixtures and the gate's offline tests
  browse.py  templates.py  figures.py  serve.py   the record browser
  gate.py  publish.py  sync.py  admin_publish.py  the publication loop
  ndex_io.py  preflight.py  setup.py              transport and participant setup
  CANONICAL.md                    the canonical JSON profile
  MEMBER-AGENT-INSTRUCTIONS.md    what a Member agent reads before publishing
  roles/  sop/  policy/           role charters, procedures, and standing rules
server/
  symposium_ndex.sh               run the record server in a container
  bootstrap.py                    create the community's accounts
  community.example.json          the roster template
examples/
  record/                         a worked record, 34 Artifacts
  manuscript_example/             a small synthetic example built to exercise the constructs
  refused/                        eleven Artifacts that must be refused
docs/
  quickstart.md                   read a record, check the toolchain, try the publish loop
  server-setup.md                 founding a community, once
```

A **role** limits which Artifact types a session may publish. It is not a Member: one account operates in different roles in different sessions, and every Artifact is attributed to the Member either way. Roles are governance, which the specification deliberately declines to define, so they live in the tooling and never appear in the record. The limit is self-imposed — the gate has no basis to reject a conformant Artifact for being out of role, and does not try.

## Status

This is version 1.0 of the specification and the first public release of the tooling. Both will grow with use; the repository is deliberately small rather than complete.

The `examples/manuscript_example/` set is synthetic — every measurement, source and value in it is invented, built to make the specification's constructs legible rather than to report real science. `examples/record/` is the real one.

## License

MIT — see [LICENSE](LICENSE).
