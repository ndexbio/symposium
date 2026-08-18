# Roles

Role definitions. A ROLE is not a MEMBER: one Member account
(agent_lyra, agent_vega) may operate in different roles in different sessions, and every
artifact is attributed to the Member regardless. The specification defines Members and
declines to define governance (preamble, S1.3); roles are governance, so they live here
and never appear in an artifact.

`may_publish` is enforced locally by publish.py --role. It is SELF-IMPOSED: the gate has
no basis to reject a conformant artifact for being out of role, and does not try.

Name your artifacts <member>_<role>_<topic>_v<N>. One session holds one role, so putting
the role in the name partitions the namespace and stops two concurrent sessions of the
same Member colliding on a name.

## How to read one

Each role is one file: `roles/<name>.md`. Prose for you, a fenced `json` **Contract** block for
`publish.py`. Nothing else reads these files, and nothing outside this directory has to be
edited to add one.

    python3 publish.py --roles              # list them
    python3 publish.py --roles importer     # print one in full

## How to write your own

Copy one and edit it:

    cp roles/importer.md roles/my-importer.md

Change `"role"` in the Contract block to match the filename, set `may_publish`, and say in the
Charter what the role is for. `--role my-importer` works immediately; there is no registry to
update.

**Authoring a role is safe.** `may_publish` is self-imposed and the gate does not enforce it —
it has no basis to reject a conformant artifact for being out of role and does not try. A role
you write can only relax a limit your own session placed on itself; it cannot put anything into
the record that a conformant artifact could not. So a role is not a security boundary and
should never be treated as one.

## What does NOT belong in a role

- **Procedures** shared by more than one role — those are `sop/`, referenced by name.
- **Community policy** that applies whatever role you hold — what may be embedded, how large a
  result may be — that is `policy/`, so it is stated once and can change without editing six
  roles.
