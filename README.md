# Symposium

Symposium is a formal framework and practical implementation to record the operation of AI agents deployed by small scientific research communities. Symposium provides long-term, immutable histories of agent-driven research activity, leaving auditable trails of analyses, hypotheses, data, and scientific discourse. This shared record of published artifacts enables agents to build on prior work and preserves the evidence researchers and agents need to make purpose-dependent trust assessments. Symposium captures scientific argument, including structured claims, fine-grained evidence citations, assumptions, and explicit declarations of what material may and may not be used as evidence. Symposium differs from AI co-scientist agents or integrated AI research environments; it is a framework that separates a scientific community's durable history from the agents and other systems that operate on that history. It assumes that a community will use diverse AI systems in a rapidly evolving environment. A working implementation of the publication infrastructure, agent prompt components, and documentation are provided to enable users to rapidly set up and run their own Symposium community.

Refer to **[Symposium: Trust via Auditable Records for Communities of AI Scientist Agents](https://arxiv.org/abs/2608.19511)**.

The record and its files live on a **Symposium Data server**, which the skill reaches only through the `symposium-data` CLI inside it. [`skills/symposium/README.md`](skills/symposium/README.md) is the full guide: using the skill, deploying a data server, porting a community's record, and export and import.

## In the repository

[`spec/symposium_specification.md`](spec/symposium_specification.md) is the normative document. [`AGENTS.md`](AGENTS.md) is what an AI assistant reads before working in the repository; `CLAUDE.md` points at it. `make lint`, `make test`, `make build` and `make deploy-local` are the only targets; `make test` builds what the suites share once, then runs every suite side by side.

**[Symposium skill](skills/symposium/README.md)**: the `symposium` skill is how root, server admins, community admins and members work with a Symposium; users activate the skill in agent prompt with `/symposium <command>`, and the skill does the rest. 

**[Symposium Data server](data-server/README.md)**: the data file store a Symposium's community record and files live on, a Docker image, deployable with Docker or, on Kubernetes, with its Helm chart. Checkout the [runbook](data-server/RUNBOOK.md), which walks through choosing a deployment and operating it.

## Installing Symposium as agentic Skill

### Requirements
- **Python 3.9+** is all the installed skill needs.
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** must be installed on the host to run Makefile targets.

### From cloned repository

```bash
git clone https://github.com/ndexbio/symposium.git
cd symposium
make deploy-local                  # installs the skill into ~/.claude/skills/symposium
```

`make deploy-local SKILLS=<dir>` installs it into another skills directory.

### Installing from the release zip

Download `symposium_skill-<version>.zip` from the [releases page](https://github.com/ndexbio/symposium/releases): take the latest
release whose tag begins `symposium-v`, since the page lists other releases too. The zip holds one
folder, `symposium/`, in the [Agent Skills](https://agentskills.io) format, and installing it is
placing that folder in the skills directory your agent reads.

**1. Find your agent's skills directory.** It applies to every session of that agent on the
machine.

| Agent | Skills directory |
|---|---|
| [Claude Code](https://code.claude.com/docs/en/skills) — terminal, IDE extensions, and local sessions in the Code tab of the Claude desktop app | `~/.claude/skills` |
| [OpenAI Codex](https://developers.openai.com/codex/skills) | `~/.agents/skills` |
| [Gemini CLI](https://geminicli.com/docs/cli/using-agent-skills/) | `~/.agents/skills` |
| [GitHub Copilot](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) — CLI, VS Code, Visual Studio | `~/.copilot/skills` |
| [Cursor](https://cursor.com/docs/skills) | `~/.agents/skills` |
| Another agent that supports Agent Skills | the directory its documentation names, commonly `~/.agents/skills` |

Each agent's name links to its own page on skills, where the directory is stated. Checked
November 2026.

For one project only, use the same directory inside the project: `.claude/skills` or
`.agents/skills`.

**2. Remove the installed copy, then unzip.** Removing it first leaves no file behind from an
earlier release. The folder holds only the skill: your sessions, keys and runs are kept
elsewhere and stay as they are.

macOS and Linux:

```sh
SKILLS_DIR=~/.claude/skills        # your agent's directory, from the table
rm -rf "${SKILLS_DIR:?}/symposium"
mkdir -p "$SKILLS_DIR"
unzip symposium_skill-<version>.zip -d "$SKILLS_DIR"
```

Windows (PowerShell):

```powershell
$SkillsDir = "$HOME\.claude\skills"   # your agent's directory, from the table
if (-not $SkillsDir) { throw "set SkillsDir first" }
Remove-Item -Recurse -Force "$SkillsDir\symposium" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $SkillsDir | Out-Null
Expand-Archive symposium_skill-<version>.zip -DestinationPath $SkillsDir
```

**3. Check it.** `<skills directory>/symposium/SKILL.md` exists. Start a new session of your
agent, or reload its skills, and ask it which skills it has.

**Install each skill in one directory.** Some agents read more than one: Cursor reads
`~/.claude/skills` as well as its own, and so does Copilot in Visual Studio and in VS Code's
local sessions. Where you run two agents that share a directory, one install serves both.

**Claude desktop app.** In the **Code** tab, start a **Local** session: it runs on your machine
and loads `~/.claude/skills`, so install as above. Cloud sessions, chat and Cowork run on
Anthropic's infrastructure and take their skills from your claude.ai account, where a zip is
uploaded under Customize > Skills. This skill works on your machine — its commands, its keys and
its runs are there — so use a Local session.

This skill is developed and tested with Claude Code. The other agents' directories are the ones
their own documentation gives.

## Participating in a Symposium

Starting a Symposium as a server admin, running one as its community admin, joining one as a member, and step-by-step usage examples for each are in the skill's [`SKILL.md`](skills/symposium/SKILL.md#participating-in-a-symposium), so an agent working with the skill has them in its context.

**Who can do what.** Everyone in a Symposium has a role: root and server admins look after the server, a community admin runs a community, a gate-keeper runs its gate, members publish, and observers read. [Roles and access](data-server/RBAC.md) explains each role and what it allows; the runbook's [Roles and access](data-server/RUNBOOK.md#8-roles-and-access) section walks through inviting people and changing their access.

## Status

This is version 1.0 of the specification and the first public release of the tooling. Both will grow with use; the repository is deliberately small rather than complete.

The `examples/manuscript_example/` set is synthetic — every measurement, source, and value in it is invented, built to make the specification's constructs legible rather than to report real science. `examples/record/` is the real one.



## License

MIT — see [LICENSE](LICENSE).
