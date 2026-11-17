# Keeping a run: for a skill built on this one

A skill built on Symposium does work around a record: it searches, computes or reasons, and
then publishes. That work is longer than a conversation and is taken up again across sittings.
This document says how such a skill keeps it, so each skill states only what is its own: what
its run is named, what its working file holds, and which user contexts it works as.

A skill that keeps a run as set out here names this document's subject, and says those three
things. Everything else below applies to it as written.

## The run, and its folder

A **run** is one piece of that skill's work, from its inputs to its last accepted artifact.

Each run keeps one folder, and one file in it:

- **`<user home>/.symposium-<skill>/runs/<run>/run.json`**, under a directory of the skill's own
  in the user's home directory, written the way the host platform spells that path. `<skill>`
  is the skill's name without the leading `symposium-`. `<run>` is the community the run
  publishes to and the run's **short name**, joined by a hyphen.
- **The short name** is a few key words of what the run is about, lowercase, joined by
  underscores. It also goes in the topic part of every artifact name the run publishes, so two
  runs in one community stay apart.
- **JSON**, because it is updated a field at a time across a long run. It holds what the skill
  says it holds, and always: the short name, the user context of every part the run plays, each
  exactly as Symposium printed it, the stage the run has reached, and the address of everything
  the gate has accepted for it.
- **Anything else the run keeps** goes in that folder beside the file: fetched copies, drafts,
  what a sub-agent returns, files the run builds for the user.

Write each decision and each accepted artifact to the working file as it happens. A run that
stops for any reason — a stop for the user, a lost session — resumes by reading it, then
syncing and taking what has been accepted from the record itself.

**You are the one writer of that file.** A sub-agent returns what it did as a file of its own
in the run's folder, named for the artifact, and you record it.

## Which run this agent session is working

Runs belong to the machine, and an agent session works one of them. The agent session is
reported by `/symposium agent-session` as `pid` and `started`; take both from there and work
nothing out yourself.

The choice is kept in **`<user home>/.symposium-<skill>/current/<pid>.json`**, holding the
run's name and `started`. At the start of every sitting:

1. Ask for this agent session.
2. Read your own pointer. Where it names a run and carries this agent session's `started`, that
   is your run: carry on with it.
3. Otherwise read the run folders and the other pointers. A pointer holds its run **in use**
   while `/symposium agent-session <pid>` reports the agent session it names as `running`, with
   the same `started`. Remove a pointer whose agent session has ended.
4. Put the choice to the user as a list: each run that is free, named by what it is about, its
   community and the stage it reached, to resume; and a new run. Show a run in use with the
   agent session that holds it; it is another agent's to work. A finished run is listed as
   finished.
5. Write your pointer.

Where no agent session is reported, keep no pointer and put the list to the user at each start.

**A run belongs to the machine it was started on.** Its folder is there and it is resumed
there. Two machines working one run, or a run folder on a drive they share, is unsafe: nothing
coordinates them.

## Who a command runs as

**Every command a run issues names the user context it runs as**, with `--user-context`. That
is the one way a run chooses who acts, so the run works whatever the agent session's current
context is, and several runs and sub-agents work side by side.

- **A value comes from the listing `/symposium use` prints**, where each entry gives it as
  `user_context`. Record it in the working file against the part it plays, and pass it back as
  it was printed. A value from anywhere else is a guess, and is refused.
- **Read `session` in each command's report** to confirm it ran as the context you named.
- **Where a command is refused for a context this machine does not hold**, the refusal carries
  the listing. Correct the working file from it and tell the user what changed.
- **Listing the contexts changes nothing.** `setup`, `bootstrap` and `use-community` each make
  their session the agent session's current one; the run carries on unaffected, because each of
  its commands names its own.
- **Nobody switches the agent session's current context during a run.** A `use` by one
  sub-agent changes it for all of them.

## The gate, for the whole of publishing

Before a run's first submission, start `gate --watch` as a background command, under a user
context that holds the `gate` grant, and leave it running as
[Commands that keep running](../SKILL.md#commands-that-keep-running) sets out. One gate decides
for a community on a machine: where another is already watching, yours stands by and watches
from the moment that one ends, so start yours without looking for another.

- **Which context**: from the listing, the contexts in the publishing community whose roles are
  `community-admin` or `gate-keeper`. One: use it, and record it. Several: ask the user, as a
  pick list. None: the gate runs from another machine; say so, publish, and wait for its
  decisions.
- **A community's gate runs from one machine.** Where the user says it already runs elsewhere,
  start none here.
- **Validate before submitting.** What the gate will find, `validate` finds first.
- **Read each decision by the artifact's name.** Accepted, the artifact is in the publishing
  context's copy of the record after a `sync`. Rejected, it is among the replies
  `sync --replies` lists, each with the artifact it is about.
- **An artifact cites only what the gate has accepted**, so a run publishes in layers and
  releases each layer once what it cites is in the record.

## Where sub-agents publish side by side

Give each sub-agent the user context it publishes as, exactly as recorded, the publishing role,
and the artifact names it owns. It builds, validates and publishes its share in order, and
returns a file per artifact saying what was accepted. One sub-agent to a name: two publishing
the same name collide, and the second is refused.

## What the skill itself states

| The skill says | For example |
|---|---|
| what a run is about, and so what its short name is drawn from | a hypothesis; a dataset and a question |
| what `run.json` holds beyond the fields above | the inputs, the decisions, the sources and their status |
| which parts the run plays, each needing a user context | a publisher and a gate; a reader of another community; a team of members |
| what a finished run is, and what choosing one shows | a run whose report the gate has accepted shows that report again |
