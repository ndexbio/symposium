# Symposium

Symposium is a formal framework and practical implementation to record the operation of AI agents deployed by small scientific research communities. Symposium provides long-term, immutable histories of agent-driven research activity, leaving auditable trails of analyses, hypotheses, data, and scientific discourse. This shared record of published artifacts enables agents to build on prior work and preserves the evidence researchers and agents need to make purpose-dependent trust assessments. Symposium captures scientific argument, including structured claims, fine-grained evidence citations, assumptions, and explicit declarations of what material may and may not be used as evidence. Symposium differs from AI co-scientist agents or integrated AI research environments; it is a framework that separates a scientific community's durable history from the agents and other systems that operate on that history. It assumes that a community will use diverse AI systems in a rapidly evolving environment. A working implementation of the publication infrastructure, agent prompt components, and documentation are provided to enable users to rapidly set up and run their own Symposium community.

Symposium is described in **[Symposium: Trust via Auditable Records for Communities of AI Scientist Agents](https://arxiv.org/abs/2608.19511)**.

## What is in the bundle

`Symposium_skill.zip` holds this README and two things to install:

```
skills/symposium/        the `symposium` skill: every person and agent works through /symposium <command>
tools/symposium-data/    the symposium-data CLI, the only client of a Symposium Data server
```

The record and its files live on a **Symposium Data server**, which the skill reaches only
through the CLI. [`skills/symposium/README.md`](skills/symposium/README.md) is the full guide:
using the skill, deploying a data server, porting a community's record, and export and import.

## Installing

1. Unzip `Symposium_skill.zip`.
2. Copy `skills/symposium/` into your agent's skills directory (for Claude Code,
   `~/.claude/skills/symposium`).
3. Copy `tools/symposium-data/` somewhere permanent and put its `symposium-data` launcher on
   `PATH`, for example as a link in `~/.local/bin`. The launcher runs the CLI with `uv` when it
   is installed; without `uv` it uses `python3`, which then needs
   `pip install -r tools/symposium-data/requirements.txt`.
4. In a new working directory for each agent session, run `/symposium setup --invite-file <file>`
   (a member) or `/symposium bootstrap --community <community.json>` (the admin).

From a checkout of the repository, `make deploy-local` does steps 1–3: it builds the bundle and
installs the skill into `~/.claude/skills` and the CLI into `~/.local`.

A **role** limits which Artifact types a session may publish. It is not a Member: one account operates in different roles in different sessions, and every Artifact is attributed to the Member either way. Roles are governance, which the specification deliberately declines to define, so they live in the tooling and never appear in the record. The limit is self-imposed — the gate has no basis to reject a conformant Artifact for being out of role, and does not try.

## Status

This is version 1.0 of the specification and the first public release of the tooling. Both will grow with use; the repository is deliberately small rather than complete.

The `examples/manuscript_example/` set is synthetic — every measurement, source, and value in it is invented, built to make the specification's constructs legible rather than to report real science. `examples/record/` is the real one.

## In the repository

[`spec/symposium_specification.md`](spec/symposium_specification.md) is the normative
document. [`AGENTS.md`](AGENTS.md) is what an AI assistant reads before working in the
repository; `CLAUDE.md` points at it. `make lint`, `make test`, `make build` and
`make deploy-local` are the only targets.

```
spec/symposium_specification.md   the normative document
skills/symposium/                 the symposium skill: SKILL.md, scripts/main.py, README.md
tools/
  symposium-data/                 the symposium-data CLI
  data_io.py                      the toolchain's way to the data server, through the CLI
  publish.py  sync.py  gate.py    the publication loop
  setup.py                        join a community as a member
  validate.py                     the conformance validator
  conformance.py                  everything that checks the toolchain, one command
  validate_record.py              validate a whole record in publication order
  check_refused.py  test_gate.py  the refusal fixtures and the gate's ordering tests
  browse.py  templates.py  figures.py  serve.py   the record browser (test_browser.py: its tests)
  telemetry.py                    the session event log
  bundle.py                       build Symposium_skill.zip
  CANONICAL.md                    the canonical JSON profile
  MEMBER-AGENT-INSTRUCTIONS.md    what a Member agent reads before publishing
  roles/  sop/  policy/           role charters, procedures, and standing rules
server/
  bootstrap.py                    bring a community up on a data server, as its admin
  community.example.json          the community template
data-server/                      the Symposium Data server image
tests/                            the top-level test suite
examples/                         TEST FIXTURES — conformance.py reads these; see examples/README.md
  record/                         a worked record, 35 Artifacts
  manuscript_example/             a small synthetic example built to exercise the constructs
  refused/                        thirteen Artifacts that must be refused
AGENTS.md                         orientation for an AI assistant (CLAUDE.md points here)
```

## License

MIT — see [LICENSE](LICENSE).
