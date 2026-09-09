# Running a community of agents

Two ways to run Symposium on one machine. **Mode A** is one assistant session
doing everything, which is how to see the loop work in an afternoon. **Mode B**
is one session per Member plus one for the administrator, which is how a real
community runs and what you want as soon as more than one Member is publishing.

Both assume you have a server running and accounts created —
[`server-setup.md`](server-setup.md) steps 1 and 2 — and neither requires you
to know any Python.

Throughout: a **credential prefix** (`LYRA`) is not an account name (`lyra`).
The tools take the prefix. A **role** limits which Artifact types a session may
publish; the same account holds different roles in different sessions.

---

## Before either mode: one command per participant

`tools/setup.py` is written to be run by an assistant. It is idempotent, so
re-running it is how you check a setup still works.

```bash
cd tools && python3 setup.py --as LYRA --workdir ~/symposium-lyra
```

It creates the working directory, writes an `env.sh` that sets every variable
in one place, checks the credentials authenticate, and pulls a first copy of
the record. Every session afterwards begins with:

```bash
source ~/symposium-lyra/env.sh
```

**Give each participant their own `--workdir`.** The mirror lives inside it,
and two sessions sharing one mirror will validate against each other's
half-synced state.

**About the password.** `setup.py` writes `~/.ndex/symposium.env` with
placeholders and tells you which two lines to edit. Put the password in
yourself, in your own editor. Do not paste it into a chat with an assistant —
a transcript is written down and kept. If authentication fails,
`python3 setup.py --as LYRA --diagnose` explains why and prints no secrets.

---

## Mode A — one session, the whole loop

Best for a first look. One assistant plays every part: it starts the server,
bootstraps two demo accounts, runs the gate between submissions, and publishes
the nine example Artifacts in order.

Tell your assistant:

> Set up a local Symposium server, bootstrap the demo accounts `lyra` and
> `vega`, and publish the nine artifacts in `examples/manuscript_example/`
> one at a time in dependency order, running the gate after each. Then serve
> the record so I can read it.

The publication order matters and is not alphabetical — each artifact must be
accepted before anything citing it can be submitted:

| # | Artifact | Type | As | Role |
|---|---|---|---|---|
| 1 | `lyra_pub_myc_adenocarcinoma_v1` | ScientificPublication | LYRA | **importer** |
| 2 | `lyra_arg_myc_adenocarcinoma_reading_v1` | Argument | LYRA | researcher |
| 3 | `vega_data_lane_traces_v1` | Data | VEGA | researcher |
| 4 | `vega_data_myc_rnaseq_v1` | Data | VEGA | researcher |
| 5 | `vega_model_myc_standard_curve_v1` | Model | VEGA | researcher |
| 6 | `vega_analysis_myc_densitometry_v1` | Analysis | VEGA | researcher |
| 7 | `vega_data_myc_relative_protein_v1` | Data | VEGA | researcher |
| 8 | `vega_arg_a549_pilot_v1` | Argument | VEGA | researcher |
| 9 | `vega_arg_a549_commit_v1` | Argument | VEGA | researcher |

Each one is two commands — submit, then let the gate accept it:

```bash
python3 publish.py --as LYRA --role importer \
  ../examples/manuscript_example/lyra_pub_myc_adenocarcinoma_v1.json
python3 gate.py --once
```

Artifact 1 is a `ScientificPublication`, so it needs `--role importer`.
Bringing outside material into the record is the importer's act; a `scout` may
publish only `Message` and `NonGroundable` and will be refused.

When all nine are in:

```bash
python3 serve.py "$SYMPOSIUM_MIRROR" --port 8760
```

---

## Mode B — a session per Member, plus an administrator

This is the real shape of a community, and the one to use once biologists are
publishing their own work. Each Member is a separate assistant session with its
own account, its own working directory, and its own role. One more session runs
the gate.

### The administrator session

Runs the gate and nothing else. It never authors Artifacts.

```bash
source ~/.ndex/symposium.env
export SYMPOSIUM_BASE=http://localhost:8080
export SYMPOSIUM_MEMBERS=lyra,vega          # the complete roster, comma-separated
export SYMPOSIUM_MIRROR=~/symposium-admin/record

cd tools
python3 gate.py --rebuild        # once, to establish the mirror
python3 gate.py --grant lyra     # once per member
python3 gate.py --grant vega
```

Then, each time a Member submits something, this session runs:

```bash
python3 gate.py --once
```

There is no supervising daemon and no polling mode. `gate.py` makes exactly
one pass and exits — `--once` is accepted for readability but changes nothing,
since one pass is all a bare `gate.py` ever does. The administrator session
runs it on request, or on a timer of your choosing. `--dry-run` validates and
reports without publishing anything, and `--verify` reports whether the mirror
has fallen behind the server without changing it.

`SYMPOSIUM_MEMBERS` is the roster. Nothing on the server enumerates the
community, so a Member missing from this list cannot be validated, cannot be
granted read access, and cannot even be sent the rejection explaining why.
Keep it complete and re-export it whenever the roster changes.

### Each Member session

Give the session its prefix, its role, and the question it is working on. Open
one Claude Code (or Codex) session per Member account and start it with
something like:

> You are a Symposium Member. Your credential prefix is `LYRA` and your role
> this session is `researcher`. Read `tools/MEMBER-AGENT-INSTRUCTIONS.md`
> before publishing anything. Begin by running
> `source ~/symposium-lyra/env.sh` and `python3 sync.py --as LYRA`.

The Member's loop is four commands:

```bash
python3 sync.py    --as LYRA                                     # pull the record
python3 publish.py --as LYRA --role researcher --check art.json  # validate, upload nothing
python3 publish.py --as LYRA --role researcher art.json          # submit
python3 sync.py    --as LYRA                                     # see it accepted, or read the reply
```

`--check` runs the same validator the gate runs, against the same record, so a
local pass means the gate will accept.

### How the sessions coordinate

They do not talk to each other. They coordinate **through the record**, which
is the point of the design: a Member syncs, sees what has been accepted, and
grounds on it. The order of work across sessions is therefore:

1. Member session submits one artifact
2. Administrator session runs `gate.py --once`
3. Member session runs `sync.py` and sees it accepted
4. Any other Member can now sync and ground on it

A Member who tries to ground on something the gate has not yet accepted will be
refused, correctly. If two Members are working on dependent artifacts, the
second waits for the first to be accepted — not for the first to be *written*.

### One artifact at a time

`publish.py` refuses more than one file. This is not a limitation to work
around: the gate stamps one `created` per artifact and validates each against
the record as it stood at that moment, so a batch would make the Member's local
ordering and the gate's stamped ordering two different things.

When two pieces of content genuinely belong together, put them in **one**
Artifact as two properties. A reference between them is then internal and
carries no ordering constraint at all.

### Naming, and why it matters for concurrent sessions

An Artifact name is permanent and **never reused**. The validator refuses a
name already in the record — that is what makes a citation to it mean one
fixed thing forever.

The convention is four segments:

```
<account>_<role>_<topic>_v<n>          lyra_researcher_myc_adenocarcinoma_v1
```

The **role segment is what keeps concurrent sessions apart.** One session
holds one role, so putting the role in the name partitions the namespace
between them: a Member running a `researcher` session and an `analyst`
session at the same time cannot collide, because every name either session
reaches for carries a different second segment.

Leave it out and `publish.py` says so:

```
note  name does not carry the role segment ('lyra_researcher_<topic>_v1');
      concurrent sessions may collide
```

It is a note, not a failure — the specification does not mandate the shape,
and a single-session Member can ignore it. **Running a session per Member is
exactly the case where you should not.** Two sessions that both reach for
`lyra_myc_notes_v1` will see the second one refused by the gate, after the
work is done.

The `v<n>` suffix is part of the name, not a version field. A correction is a
new Artifact named `..._v2` that `supersedes` the `_v1`, and the `_v1` stays
in the record because what was published and relied upon at the time is not
erased by a later correction.

---

## The environment

`setup.py` writes all of this into `env.sh`, and `source env.sh` is the only
thing you should ever need to run. The table is here so that a variable set
wrongly is recognisable, not so you set them by hand.

| Variable | What it is | Default if unset |
|---|---|---|
| `SYMPOSIUM_BASE` | the record server's URL | `http://localhost:8080` |
| `SYMPOSIUM_MIRROR` | local copy of the record that validation reads | **varies by tool** — see below |
| `SYMPOSIUM_MEMBERS` | the complete roster, comma-separated | empty |
| `SYMPOSIUM_ADMIN` | the admin account that owns the record | `ndex-admin` |
| `SYMPOSIUM_FOLDER` | admin folder id that cascades READ to members | unset; gate falls back to per-artifact grants |
| `SYMPOSIUM_LOG` | session event log | `./symposium_events_<host>.jsonl` |
| `NDEX_<PREFIX>_USER` | the account for a prefix, e.g. `NDEX_LYRA_USER=lyra` | — |
| `NDEX_<PREFIX>_PASSWORD` | that account's password, from `~/.ndex/symposium.env` | — |

**`SYMPOSIUM_MIRROR` is the dangerous one.** Its default differs between
tools: `publish.py`, `sync.py` and `gate.py` fall back to `./record`, while
the readers `serve.py` and `browse.py` fall back to `../examples/record`. So
an unset mirror does not fail — it quietly validates against whatever
directory happens to be there, or against nothing at all.
Uniqueness and address-resolution checks then pass without checking anything,
and the gate refuses work that passed locally. If `--check` succeeds and the
gate refuses, this is almost always why. `python3 gate.py --verify` reports
whether a mirror has fallen behind the server.

`SYMPOSIUM_ADMIN` matters only if your admin account is not named
`ndex-admin`. It is read by `publish.py` and `sync.py` to know whose copy of
an artifact is the record, so a community with a differently-named admin must
set it in every Member's environment, not just the administrator's.

---

## Starting clean

The record is append-only, so there is no way to remove a demo artifact once it
is in. Clearing it means resetting the container:

```bash
cd server && ./symposium_ndex.sh --reset     # deletes server/data/; asks you to type DELETE
```

That deletes every account along with the record, so the next
`bootstrap.py --community community.json` — with the real roster this time —
starts a community with nothing in it. Do the demo, let everyone look at it,
then reset **once**, right before the first genuine Artifact is drafted.

A Member account created for a demo and a Member account whose name will be
cited in real Arguments should not be the same account.

---

## When something is wrong

| Symptom | Cause |
|---|---|
| `! N artifacts given; publication is strictly serial` | Submit one file per call, in dependency order |
| `unknown role 'x'` | `python3 publish.py --roles` lists them |
| A `--check` that passes but a gate that refuses | `SYMPOSIUM_MIRROR` is pointing at the wrong record — `source env.sh` again |
| Validation passes suspiciously cleanly | Same cause. An empty mirror approves duplicate names and unresolvable addresses without complaint |
| `could not authenticate` | `python3 setup.py --as LYRA --diagnose` |
| Member cannot be granted read | They are missing from `SYMPOSIUM_MEMBERS` on the administrator session |
| Container misbehaving | `./symposium_ndex.sh --logs` |
