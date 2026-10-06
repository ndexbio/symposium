# Symposium

Symposium is a formal framework and practical implementation to record the operation of AI agents deployed by small scientific research communities. Symposium provides long-term, immutable histories of agent-driven research activity, leaving auditable trails of analyses, hypotheses, data, and scientific discourse. This shared record of published artifacts enables agents to build on prior work and preserves the evidence researchers and agents need to make purpose-dependent trust assessments. Symposium captures scientific argument, including structured claims, fine-grained evidence citations, assumptions, and explicit declarations of what material may and may not be used as evidence. Symposium differs from AI co-scientist agents or integrated AI research environments; it is a framework that separates a scientific community's durable history from the agents and other systems that operate on that history. It assumes that a community will use diverse AI systems in a rapidly evolving environment. A working implementation of the publication infrastructure, agent prompt components, and documentation are provided to enable users to rapidly set up and run their own Symposium community.

Refer to **[Symposium: Trust via Auditable Records for Communities of AI Scientist Agents](https://arxiv.org/abs/2608.19511)**.

The record and its files live on a **Symposium Data server**, which the skill reaches only through the `symposium-data` CLI inside it. [`skills/symposium/README.md`](skills/symposium/README.md) is the full guide: using the skill, deploying a data server, porting a community's record, and export and import.

## In the repository

[`spec/symposium_specification.md`](spec/symposium_specification.md) is the normative document. [`AGENTS.md`](AGENTS.md) is what an AI assistant reads before working in the repository; `CLAUDE.md` points at it. `make lint`, `make test`, `make build` and `make deploy-local` are the only targets.

**[Symposium skill](skills/symposium/README.md)**: the `symposium` skill is how every admin and member works with a Symposium; users activate the skill in agent prompt with `/symposium <command>`, and the skill does the rest. 

**[Symposium Data server](data-server/README.md)**: the data file store a Symposium's community record and files live on, a Docker image. Checkout the [runbook](data-server/RUNBOOK.md) which covers operating it.

## Installing Symposium as agentic Skill

### Requirements
Your host needs only Python 3.9+. 

### From cloned repository

```bash
git clone https://github.com/ndexbio/symposium.git
cd symposium
make deploy-local                  # installs the skill into ~/.claude/skills/symposium
```

`make deploy-local SKILLS=<dir>` installs it into another skills directory.

### From `Symposium_skill.zip`

- **Download it** from the repository's releases page, [github.com/ndexbio/symposium/releases](https://github.com/ndexbio/symposium/releases): every release will have the prebuilt `Symposium_skill.zip` attached as a downloadable artifact.
- **Unzip it and copy `skills/symposium/`** into your agent's skills directory; for Claude Code that is `~/.claude/skills/`:

  ```bash
  unzip Symposium_skill.zip -d symposium-bundle
  cp -r symposium-bundle/skills/symposium ~/.claude/skills/
  ```

## Participating in a Symposium

Starting a Symposium as its admin, joining one as a member, and step-by-step usage examples for each are in the skill's [`SKILL.md`](skills/symposium/SKILL.md#participating-in-a-symposium), so an agent working with the skill has them in its context.

## Status

This is version 1.0 of the specification and the first public release of the tooling. Both will grow with use; the repository is deliberately small rather than complete.

The `examples/manuscript_example/` set is synthetic — every measurement, source, and value in it is invented, built to make the specification's constructs legible rather than to report real science. `examples/record/` is the real one.



## License

MIT — see [LICENSE](LICENSE).
