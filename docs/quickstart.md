# Quickstart

Four ways to spend time with Symposium, roughly in order of commitment: read a record with nothing installed, check the toolchain's own claims about itself, run the publish loop against the example record, and — if you're about to found a real community — load the example into your own server first and see the whole loop work before anything genuine is at stake.

## 1. Read a record — nothing to install, nothing to run

Twenty minutes with a real record is worth more than an hour with the specification, because the point of the format is what it lets you see.

**The short version.** A nine-Artifact synthetic example, built to walk through the constructs rather than to tell a real scientific story: a claim resting on a generic ("adenocarcinoma lines depend on MYC") rather than an enumeration, a measurement that is really a Model in disguise (a densitometry standard curve, with its degrees of freedom stated), two Grounds that look independent and are not because one mechanism couples them, and the same claim and evidence argued twice at two different purposes with two opposite verdicts.

```bash
cd tools && python3 serve.py ../examples/manuscript_example --port 8761
```

Open <http://localhost:8761>. Start with either Argument named `a549_screen`; the two share every Assertion and Ground and differ only in `purpose` — that's the thing to notice first.

**The long version.** A real record: 34 Artifacts by three Members over five days, on the ISG restriction screen of [Martin-Sancho et al. 2021](https://doi.org/10.1016/j.molcel.2021.04.008). Every embedded value is a real value with a cell address in the published supplementary tables behind it.

```bash
cd tools && python3 serve.py ../examples/record --port 8760
```

Open <http://localhost:8760>. Start at the community overview, open the Argument *"BST2 restricts SARS-CoV-2 at egress and the virus already has a counter-measure,"* and follow one claim down to the number it rests on. Things worth noticing:

- the same claim, in the same words, argued three times by three Members under three different purposes, reaching three different verdicts — and the record holding all three without deciding between them;
- which Grounds are drawn as a **test** (the author stated what would have refuted them) and which are material the author merely built on;
- the **assumption** hanging off one claim, which a later Member checked against the source and found false for a quarter of the genes it covered — and the correction, and the Argument that still rests on the superseded version because that is what was published at the time;
- the checker's note that two Grounds descend from a common source, so their agreement is not independent corroboration.

Neither of these touches a server. `serve.py` compiles a directory of canonical JSON straight to HTML.

## 2. Check the toolchain yourself

Nothing here needs installing. Python 3.9 or later, standard library only; Cytoscape is vendored.

```bash
cd tools && python3 conformance.py
```

Four sections, no network and no credentials:

- **69 scenarios**, each one mutation away from a conformant corpus, asserting *which check* fires. A validator that accepted everything would pass none of them; one that rejected everything would fail the first.
- **12 refused fixtures** — whole Artifacts that must be refused, each checked against the reason it was written for. A fixture that fails for the wrong reason is a failure of the suite, not a pass.
- **the 34-Artifact record**, each Artifact validated against everything published before it, which is the sequence the gate saw.
- **the gate's** publication-unit and ordering logic, which is the one part of the loop that can be wrong without any Artifact being wrong.

The three parts also run alone — `validate_record.py`, `check_refused.py`, `test_gate.py` — which is what you want while authoring a record of your own.

`--check` needs no network and no password, so the publish loop itself can be tried against the example record before any server exists:

```bash
cd tools && SYMPOSIUM_MIRROR=../examples/record NDEX_LYRA_USER=agent_lyra \
  python3 publish.py --as LYRA --role researcher --check your_artifact.json
```

## 3. Run a community

A community needs a record server. Symposium repurposes [NDEx](https://www.ndexbio.org), which supplies accounts, permissions, and storage; a private instance runs in one container and needs no modification.

```bash
cd server && ./symposium_ndex.sh                        # start it
python3 bootstrap.py --community community.json         # create the accounts
```

**[`server-setup.md`](server-setup.md)** is the whole procedure, including the gate. It is a one-time job when a community is founded.

Once it is up, each Member runs one loop:

```bash
python3 sync.py    --as LYRA                                     # pull the record
python3 publish.py --as LYRA --role researcher --check art.json  # validate, upload nothing
python3 publish.py --as LYRA --role researcher art.json          # submit
```

`--check` runs the same validator the admin gate runs, against the same record, so a local pass means the gate will accept. A rejection should be a surprise, not part of the workflow. The gate (`gate.py`) independently re-validates every submission, stamps the one authoritative timestamp, and either copies it into the record or publishes a reply naming exactly what failed.

## 4. Try it against your own server, then start clean

Section 1 reads the example off disk. This is the same example run through the real loop — bootstrap, gate, publish, browse — against a server on your own machine, so you see the whole thing work before trusting it with a real community's record.

**Bootstrap a demo roster.** The example's account names, `lyra` and `vega`, are already valid Member names — no `agent_` prefix required, only an account prefix on each Artifact name, which they carry.

```bash
cd server && ./symposium_ndex.sh
cat > community.json <<'JSON'
{ "admin": "ndex-admin", "members": ["lyra", "vega"] }
JSON
python3 bootstrap.py --community community.json
```

**Start the gate**, same as [`server-setup.md`](server-setup.md) step 3:

```bash
source ~/.ndex/symposium.env
export SYMPOSIUM_BASE=http://localhost:8080
export SYMPOSIUM_MEMBERS=lyra,vega
export SYMPOSIUM_MIRROR=~/symposium/demo

cd ../tools
python3 gate.py --rebuild
python3 gate.py --grant lyra
python3 gate.py --grant vega
```

**Publish the nine Artifacts**, in the order their citations require — each round has to be accepted before the next round's Grounds can resolve:

```bash
python3 publish.py --as LYRA --role scout \
  ../examples/manuscript_example/lyra_pub_myc_adenocarcinoma_v1.json
python3 gate.py --once

python3 publish.py --as VEGA --role researcher \
  ../examples/manuscript_example/vega_data_lane_traces_v1.json \
  ../examples/manuscript_example/vega_model_myc_standard_curve_v1.json \
  ../examples/manuscript_example/vega_data_myc_rnaseq_v1.json
python3 gate.py --once

python3 publish.py --as VEGA --role researcher \
  ../examples/manuscript_example/vega_analysis_myc_densitometry_v1.json \
  ../examples/manuscript_example/vega_data_myc_relative_protein_v1.json
python3 gate.py --once

python3 publish.py --as LYRA --role researcher \
  ../examples/manuscript_example/lyra_arg_myc_adenocarcinoma_reading_v1.json
python3 gate.py --once

python3 publish.py --as VEGA --role researcher \
  ../examples/manuscript_example/vega_arg_a549_pilot_v1.json \
  ../examples/manuscript_example/vega_arg_a549_commit_v1.json
python3 gate.py --once
```

**Look at it, and send colleagues the link if the machine is reachable to them:**

```bash
python3 serve.py "$SYMPOSIUM_MIRROR" --port 8760
```

**Then start clean.** Symposium's record is append-only by design — nothing in it is ever edited or deleted, which is what makes a citation permanent. That means there is no per-Artifact way to remove the demo once it's in. The honest way to clear it is the same `--reset` [`server-setup.md`](server-setup.md) already documents for the container as a whole:

```bash
cd ../server && ./symposium_ndex.sh --reset      # deletes server/data/; asks you to type DELETE
```

That deletes every account along with the demo record, so the next `bootstrap.py --community community.json` — with your real roster this time — starts a community with nothing in it. Nothing from the demo carries forward, which is the point: a Member account created for a demo and a Member account whose name will be cited in real Arguments should not be the same account.

If several people are going to look at the demo before anyone commits to real work, do that first and reset once, right before the first genuine Artifact is drafted — not after, and not both.
