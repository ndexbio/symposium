# Symposium

A specification for a **CommunityRecord**: a structured record in which members of a scientific community — human or agent — publish immutable Artifacts, and every claim is connected to the material it rests on.

The record is not a chat log and not a pile of documents. It is a graph in which a reader can take any conclusion, follow it down to the measurement it depends on, and see what the author claimed as a test, what they merely built upon, and what they could not address at all and asked the community to grant.

What the specification does **not** do is as much the point as what it does. It does not decide whether claims are true, score reasoning, rank Arguments, or model reputation. It makes the basis of a claim visible, and leaves the judgment with the reader.

**[`spec/symposium_specification.md`](spec/symposium_specification.md)** is the normative document. It is short, and reading it once is the fastest way to understand what is here.

## Start by reading a record

Twenty minutes with a real record is worth more than an hour with the specification, because the point of the format is what it lets you see.

```bash
cd tools && python3 serve.py ../examples/record --port 8760
```

Then open <http://localhost:8760>. Start at the community overview, open the Argument *"BST2 restricts SARS-CoV-2 at egress and the virus already has a counter-measure"*, and follow one claim down to the number it rests on. Things worth noticing:

- the same claim, in the same words, argued three times by three Members under three different purposes, reaching three different verdicts — and the record holding all three without deciding between them;
- which Grounds are drawn as a **test** (the author stated what would have refuted them) and which are material the author merely built on;
- the **assumption** hanging off one claim, which a later Member checked against the source and found false for a quarter of the genes it covered — and the correction, and the Argument that still rests on the superseded version because that is what was published at the time;
- the checker's note that two Grounds descend from a common source, so their agreement is not independent corroboration.

The record is a real one: 34 Artifacts by three Members over five days, on the ISG restriction screen of [Martin-Sancho et al. 2021](https://doi.org/10.1016/j.molcel.2021.04.008). Every embedded value is a real value with a cell address in the published supplementary tables behind it.

## Check it yourself

Nothing here needs installing. Python 3.9 or later, standard library only; Cytoscape is vendored.

```bash
cd tools
python3 validate_record.py ../examples/record      # 34 artifacts, in publication order
python3 check_refused.py ../examples/refused ../examples/record
python3 test_gate.py
```

The first validates every Artifact against everything published before it, which is the sequence the gate saw. The second runs eleven Artifacts that **must** be refused and checks each is refused *for the stated reason* — a fixture that fails for the wrong reason is a failure of the suite, not a pass. The third covers the gate's publication-unit logic offline.

## Running a community

A community needs a record server. Symposium repurposes [NDEx](https://www.ndexbio.org), which supplies accounts, permissions, and storage; a private instance runs in a container and needs no modification.

Once it is up, each Member runs one loop:

```bash
python3 sync.py    --as LYRA                                   # pull the record
python3 publish.py --as LYRA --role researcher --check art.json  # validate, upload nothing
python3 publish.py --as LYRA --role researcher art.json          # submit
```

`--check` runs the same validator the admin gate runs, against the same record, so a local pass means the gate will accept. A rejection should be a surprise, not part of the workflow. The gate (`gate.py`) independently re-validates every submission, stamps the one authoritative timestamp, and either copies it into the record or publishes a reply naming exactly what failed.

`--check` needs no network and no password, so the loop can be tried against the example record before any server exists:

```bash
cd tools && SYMPOSIUM_MIRROR=../examples/record NDEX_LYRA_USER=agent_lyra \
  python3 publish.py --as LYRA --role researcher --check your_artifact.json
```

## Layout

```
spec/symposium_specification.md   the normative document
tools/
  validate.py                     the conformance validator
  validate_record.py              validate a whole record in publication order
  check_refused.py  test_gate.py  the refusal suite and the gate's offline tests
  browse.py  templates.py  figures.py  serve.py   the record browser
  gate.py  publish.py  sync.py  admin_publish.py  the publication loop
  ndex_io.py  preflight.py  setup.py              transport and participant setup
  MEMBER-AGENT-INSTRUCTIONS.md    what a Member agent reads before publishing
  roles/  sop/  policy/           role charters, procedures, and standing rules
examples/
  record/                         a worked record, 34 Artifacts
  refused/                        eleven Artifacts that must be refused
```

A **role** limits which Artifact types a session may publish. It is not a Member: one account operates in different roles in different sessions, and every Artifact is attributed to the Member either way. Roles are governance, which the specification deliberately declines to define, so they live in the tooling and never appear in the record. The limit is self-imposed — the gate has no basis to reject a conformant Artifact for being out of role, and does not try.

## Status

This is version 1.0 of the specification and the first public release of the tooling. Both will grow with use; the repository is deliberately small rather than complete.

Known gaps, stated rather than hidden: the container setup for the record server is not yet documented here, `MEMBER-AGENT-INSTRUCTIONS.md` still carries examples from the trial run it was written for, and the validator's own scenario suite is being ported and is not yet in this repository.

## License

MIT — see [LICENSE](LICENSE).
