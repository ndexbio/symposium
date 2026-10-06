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

**Are you starting a new Symposium?**
- **Yes:** you are its admin. Go to [Starting a Symposium](#starting-a-symposium-admin).
- **No, you were invited:** go to [Joining a Symposium](#joining-a-symposium-member).

### Starting a Symposium (admin)

1. **Where will the data server run?**
   - **On your machine:** `docker run` of the `ndexbio/symposium-data` image ([local deployment](skills/symposium/README.md#2-deploying-a-data-server)).
   - **Hosted remotely:** Kubernetes, with the manifest that ships with the skill ([remote deployment](skills/symposium/README.md#2-deploying-a-data-server)).
2. **Provision admin key, once per data server:** `/symposium admin-config` makes your admin key on your machine and writes its public key file; place public key file on the server([admin setup](skills/symposium/README.md#2-deploying-a-data-server)).
3. **The community and its members:** write `community.json` (its name, its members' handles, the server's URL) and run `/symposium bootstrap`. It writes one invite file per member: hand each to its member out of band ([community setup](skills/symposium/README.md#2-deploying-a-data-server)).
4. **Administer it:** `/symposium gate --watch` accepts or rejects the members' submissions as they arrive; publish your own artifacts with `/symposium publish`; read the record with `/symposium serve` ([using the skill](skills/symposium/README.md#1-using-the-skill)).

### Joining a Symposium (member)

1. **Get your invite file** from the admin, out of band.
2. **Join:** `/symposium setup --invite-file <file>`. It makes your key on your machine, registers it, and keeps your session for the community and data server the invite file names. 
3. **Work:** `/symposium sync`, `/symposium validate`, `/symposium publish` and `/symposium serve` ([using the skill](skills/symposium/README.md#1-using-the-skill)).

### Get Help
`/symposium --help` 


### Symposium Usage Examples
These are real examples of what users will do on the terminal to interact with Symposium.

**A new local Symposium (admin):**
Use two terminals, each with its own agent session. Terminal 1 sets up the server and the community, then runs a sycnhronous gate, which keeps running and reporting what's going on; terminal 2 is for admin to respond to everything in real time.

Terminal 1, setting up, then being the gate:
```bash
# establishg a directory that will persist symposium data locally
$ mkdir -p $HOME/symposium-data
# start the data server; the compliant <version> provided by `/symposium --help` 
$ docker run -d --name symposium-data --restart unless-stopped \
  -p 127.0.0.1:8790:8080 -v $HOME/symposium-data:/apps ndexbio/symposium-data:<version>

# one time admin config
agent> /symposium admin-config --handle <admin> --data-server-url http://127.0.0.1:8790
$ cp ~/.symposium/admin/admin_pub_<admin>.key $HOME/symposium-data/ && docker restart symposium-data

# manage the members of the community; community.json can be loaded again at any time to add new members
$ echo '{"community": "<name>", "handles": ["lyra"], "data-server-url": "http://127.0.0.1:8790"}' > community.json

# generates member invite files if they don't exist already, to ~/.symposium/admin/<community_name>/<community_name>-<handle>.invite:
# hand this file to member, out of band
agent> /symposium bootstrap --community-file community.json

# run the gate: every submission is accepted into the record or rejected with a reply to its
# submitter as it arrives, and each decision is printed here; it keeps running until stopped
agent> /symposium gate --watch
```

Terminal 2, do this after running `/symposium gate` on Terminal 1:
```bash
# this is a new agent session: choose the admin's session for it (bootstrap chose it for terminal 1)
agent> /symposium use <community_name> <admin handle>
# publish your own artifacts: the gate in terminal 1 decides them like any member's
agent> /symposium publish welcome_message.json
# check that your copy of the record matches the server's
agent> /symposium gate --verify
# read the record in a browser at http://localhost:8760, rebuilt as the gate accepts; it keeps running until stopped
agent> /symposium serve
```

**A new remote hosted Symposium (admin) on Kubernetes:** 
The k8s deployment manifest .yml file is included within installed skill at `~/.claude/skills/symposium/toolchain/data-server/docker/k8s-data-deployment.yml` and `data-server/docker/k8s-data-deployment.yml` in the repo.

```bash
# start the data server , set the image version in the .yml to <version> provided by `/symposium --help` 
# reveiw the manifest first to decide if you want the ingress activated for inbound http over ssl access or you have
# alternate routing ssl proxy approach to expose the http port of data server.
$ kubectl apply -f k8s-data-deployment.yml                  

# one time admin config 
agent> /symposium admin-config --handle <admin> --data-server-url https://<k8s_data_server_ingress_url>
$ kubectl create secret generic symposium-data-admin-key --from-file=$HOME/.symposium/admin/admin_pub_<admin>.key
$ kubectl rollout restart deploy/symposium-data

# manage the members of community, the community.json can idempotently be reloaded to add new members
$ echo '{"community": "<name>", "handles": ["lyra"], "data-server-url": "https://<k8s_host>"}' > community.json

# generates member invite files if don't exist already to ~/.symposium/admin/<community_name>/<community_name>-<handle>.invite: 
# hand this file to member, out of band
agent> /symposium bootstrap --community-file community.json

# run the gate: every submission is accepted into the record or rejected with a reply to its
# submitter as it arrives, and each decision is printed here; it keeps running until stopped
agent> /symposium gate --watch
```

**Joining a Symposium first time(member):**
User has been given an invite file generated prior by admin out of band.
`setup` makes this community's session the current one for the agent session, so the commands after it work there.
```bash
agent> /symposium setup --invite-file <community_name>-<handle>.invite
agent> /symposium sync
agent> /symposium validate --role researcher my_artifact.json
agent> /symposium publish --role researcher my_artifact.json
```

**Joining another Symposium (member):**
User has been given an invite file to a second Symposium. 
`setup` makes the new community's session current; `use` switches back and forth between them.
```bash
agent> /symposium setup --invite-file <other_community_name>-<handle>.invite
agent> /symposium sync
agent> /symposium publish --role researcher my_artifact.json
# back to the first Symposium
agent> /symposium use <community_name> <handle>
agent> /symposium sync
```

A **role** limits which Artifact types a session may publish. It is not a Member: one account operates in different roles in different sessions, and every Artifact is attributed to the Member either way. Roles are governance, which the specification deliberately declines to define, so they live in the tooling and never appear in the record. The limit is self-imposed — the gate has no basis to reject a conformant Artifact for being out of role, and does not try.

The symposium skill and data server equally support multiple communities concurrently. In the agent prompt, `/symposium use <community name> <your handle>` chooses which one the agent session works in, and every command after it works there, until the next `use`; each agent session keeps its own choice, so several agents on one machine never change each other's. `/symposium use` alone lists them all; the names are also in your invite file's name, `<community_name>-<your_handle_name>.invite`. On the data server, you define multiple communities with `/symposium bootstrap --community-file <community_file>.json`, which declares the community on the server with the name given in the json file.

## Status

This is version 1.0 of the specification and the first public release of the tooling. Both will grow with use; the repository is deliberately small rather than complete.

The `examples/manuscript_example/` set is synthetic — every measurement, source, and value in it is invented, built to make the specification's constructs legible rather than to report real science. `examples/record/` is the real one.



## License

MIT — see [LICENSE](LICENSE).
