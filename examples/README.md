# examples/

**These directories are the conformance suite's fixtures. Two of the three are
read directly by `tools/conformance.py`, and deleting or editing them breaks
the build.**

That is not what the word *examples* usually promises, so it is worth saying
plainly before anything else: this is not a folder of samples kept around for
illustration. It is test data that also happens to be readable, and the
readability is deliberate — the specification is easier to check against a
record you can open than against prose.

| Directory | What it is | Safe to change? |
|---|---|---|
| [`record/`](record/) | 35 Artifacts, a real record | **No** — a test fixture and the default mirror |
| [`refused/`](refused/) | 13 Artifacts that must be **refused** | **No** — the negative half of the suite |
| [`manuscript_example/`](manuscript_example/) | 9 synthetic Artifacts, a walkthrough | Only with care — the quickstart publishes it step by step |

## What each one is for

**`record/` — the real worked record.** 35 Artifacts by three Members (plus
one admin Artifact) on the
ISG restriction screen of [Martin-Sancho et al.
2021](https://doi.org/10.1016/j.molcel.2021.04.008). Every embedded value is a
real value with a cell address in the published supplementary tables behind
it.

It has three jobs at once. It is what `validate_record.py` walks in
publication order, checking each Artifact against everything published before
it — the sequence the gate saw. It is the **default** `SYMPOSIUM_MIRROR` for
`serve.py` and `browse.py`, so `python3 serve.py` with no arguments serves it.
And it is the worked example [`tools/CANONICAL.md`](../tools/CANONICAL.md)
points at throughout: when the profile is unclear, the instruction is to read
the artifact.

**`refused/` — Artifacts that must not be accepted.** 13 fixtures plus
`EXPECTED.json`, which names the reason each one must be refused for: `GROUND`,
`ORDER`, `UNIQUE`, `C-ARG`, `TYPE`, `ADDRESS`. A fixture that is refused for
the *wrong* reason is a failure of the suite, not a pass.

This is the half of the suite that has teeth. A validator that accepted
everything would pass none of these; one that rejected everything would fail
the positive cases in `record/`. Some fixtures only fail in the presence of
another Artifact, which is why `check_refused.py` is given `record/` as well.

**`manuscript_example/` — the synthetic walkthrough.** Nine Artifacts built to
make the specification's constructs legible rather than to report real
science. Everything in it is invented; it has [its own
README](manuscript_example/README.md) saying so at length. It is what
[`docs/quickstart.md`](../docs/quickstart.md) publishes one Artifact at a time
through a real gate, so its **names and its citation order are load-bearing**
even though its values are fiction.

## If you want a record to experiment with

Copy one somewhere else and point the tools at your copy:

```bash
cp -r examples/manuscript_example ~/symposium-scratch/record
cd tools && python3 serve.py ~/symposium-scratch/record --port 8760
```

Publishing your own Artifacts belongs in a Symposium of your own — see
[`docs/running-agents.md`](../docs/running-agents.md), which takes a `--data`
directory you choose. Nothing you author should land in this repository.

## Checking that they still pass

```bash
cd tools && python3 conformance.py
```

Four sections — mutation scenarios, the refusal fixtures, the record in
publication order, and the gate's own logic. It must end with
`CONFORMANCE: everything behaved as specified`. The three parts also run
alone: `validate_record.py`, `check_refused.py`, `test_gate.py`.
