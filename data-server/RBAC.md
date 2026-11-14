# Roles and access

This is the one description of who may do what in a Symposium: the access roles, the grants
they hold, and the rules for changing them. The runbook's "Roles and access" section
([RUNBOOK.md](RUNBOOK.md#8-roles-and-access)) has the step-by-step procedures: setting up a
server, inviting people, issuing API keys and changing someone's access.

## Who holds roles

Access roles are held by **users** and by **API keys**.

- A **community user** belongs to one community: the one their invite named. Their roles act
  in that community only.
- A **server-level user** belongs to no community and works in all of them: **root**, the one
  user named by the data server's root key file, and the **server admins** root invites.
- An **API key** belongs to the community it was issued in. It is issued by a signed-in user,
  for a script or an application (see [API keys](#api-keys)).

A caller's community always comes from who they are, never from a role: a role says what its
holder may do, and the holder's own community says where.

People receive their roles with their invite: the roles are kept on the data server, and are
given to the person when they join with the invite file, which carries no roles itself. Roles
can be added or taken away at any time afterwards; a change applies from the person's next
command.

## Grants

A **grant** is one fixed capability. Every command and every request takes one grant, and
succeeds when the caller holds it where the request acts.

| Grant | Allows | Where it applies |
|---|---|---|
| `read` | read a collection's files and their versions, list and search them, follow its changes, and check citations into it; reading the record (the `record` collection) is `read` on `record` | the collections its value names |
| `write` | add files and new versions, and delete your own files, in any collection but `inbox` and `record`; create a collection, which then belongs to you | the collections its value names |
| `manage` | make a collection public or private; share it read-only with someone; change or delete anyone's files in it; purge a version's content | the collections its value names |
| `publish` | submit an artifact to the community's gate (into `inbox`), and check one before submitting; see your own submissions and the gate's replies to you | the community |
| `gate` | read every submission, accept one into the record, or reject it with a reply | the community |
| `members` | invite people into the community; give and take away community roles; remove users; replace a user's lost key; flag a user's writes after a time; list and revoke any API key in the community | the community |
| `export` | export the community, as a backup or to move it to another server | the community |
| `communities` | list every community; create one, naming its first community admin; import an exported community; port a community's record from NDEx (port-ndex); store files without a quota | the whole server |
| `delegate` | invite server admins, list the server-level users with their roles and pending invites, give or take away the `server-admin` role, and remove server-level users | the whole server |

`inbox` is never reached through `read`, `write` or `manage`: submissions go in with `publish`,
replies with `gate`, and only the gate's acceptance writes into `record`.

## Roles

A **role** is a fixed set of grants. There are six.

| Role | Held by | Grants | In practice |
|---|---|---|---|
| `server-root` | root only | `read`, `write`, `manage` on every collection of every community; `gate`, `members`, `export` in every community; `communities`, `delegate` | runs the server; the only holder of `delegate`, so the only one who creates and removes server admins |
| `server-admin` | server-level users root invites | `read`, `write`, `manage` on every collection of every community; `gate`, `members`, `export` in every community; `communities` | creates, imports and ports communities, and can run any of them |
| `community-admin` | community users | `read`, `write`, `manage` on every collection of the community; `gate`, `members`, `export` | runs a community: invites people, gives roles, runs the gate |
| `gate-keeper` | community users | `read` on every collection of the community; `gate` | runs the gate, and nothing else |
| `community-member` | community users and member API keys | `read`, `write` on its collection value; `manage` on the collections the holder owns; `publish`; a user holding it also always reads `record` | publishes, and works in its collections; reading the record lets it check its work against what is already published |
| `community-observer` | community users, and member and non-member API keys | `read` on its collection value | reads |

No administrative role holds `publish`: the people who decide submissions never decide their
own. Someone who runs a community and also publishes holds `community-member` alongside their
administrative role. A person may hold several roles; their grants add up.

## Collection values

`community-member` and `community-observer` always take a **collection value** when they are
given, written after the role:

| Written | Means |
|---|---|
| `:*` | every collection of the community, `record` included |
| `:` | no collection by name: only the collections the holder owns |
| `:c1,c2` | the collections named, plus the ones the holder owns |

For example `community-member:*`, `community-observer:` or `community-observer:lab,results`.

- **You keep what you own.** Whoever creates a collection owns it, and when signed in keeps full
  access to it (`read`, `write` and `manage`) whatever their roles' collection values.
- **A key reaches only what it names.** An API key reaches exactly the collections its own roles
  name, even ones its issuer owns.
- **Public collections.** A collection made public (with `manage`) can be read by anyone, with no
  key. `inbox` is never public.

## Typical assignments

| Need | Role to give |
|---|---|
| run a community | `community-admin` |
| a member who publishes and works across the community | `community-member:*` |
| a member who publishes, reads the record, and works only in collections they create | `community-member:` |
| a read-only member | `community-observer:*` |
| a reader of some collections, a person or an application's key | `community-observer:c1,c2` |
| run the gate | `gate-keeper` |

## API keys

An API key lets a script or an application call the data server. It is issued from a signed-in
session, belongs to that session's community, and carries roles of its own: only
`community-member` and `community-observer`.

- A **member key** (the default) acts as the user who issued it. Its roles never reach beyond
  what the issuer holds, and with `community-member` it publishes as the issuer.
- A **non-member key** (issued with `--non-member`) is an identity of its own, for an outside
  application. It carries `community-observer` only, so it reads and never writes.
- Only the key's issuer, or a holder of `members` in its community, changes a key's roles or
  revokes it. Revoking deletes the key: its next request is refused, and it cannot be restored.
- An API key never invites, gives roles or issues keys: changing access takes a signed-in user.
- Removing a user deletes every key they issued.

## Who may change access

Giving a role, or taking it away, takes the grant below, held where the person or key being
changed belongs: their community, or the whole server for a server-level user:

| Role being given or taken away | The person making the change holds |
|---|---|
| `server-root` | nobody: root comes from the server's root key file |
| `server-admin` | `delegate` (root) |
| `community-admin`, `gate-keeper` | `members` |
| `community-member`, with any collection value | `members` |
| `community-observer:*` or `community-observer:` | `members` |
| `community-observer` naming collections | `manage` on each collection named: its owner, a community admin, a server admin or root |

- Taking named collections away takes the same authority, for each collection taken away. An
  owner can therefore share their own collections read-only, and take them back, without the
  community admin; they cannot touch anyone else's.
- Taking a whole `community-observer` role away takes authority over every collection it names,
  or `members`.
- On an API key, the issuer's own grants are the limit: a member key's roles stay within its
  issuer's, and a non-member key also needs the authority above.
- Every change is made by a signed-in user.

## What refuses an action

- **A missing grant:** the command, or the request, is refused and names the grant it takes.
- **The last community admin:** every community keeps at least one person holding `members`.
  Taking the role from the last one, or removing them, is refused: appoint another first.
- **Key limits:** a key works in its own community only, carries only `community-member` or `community-observer`, never more than
  its issuer holds, and only its issuer or a `members` holder changes it.
- **`inbox`:** a submission takes `publish`, a reply takes `gate`, and nothing else goes in.
- **A retired handle:** a removed person's handle is never used again, so inviting it, or
  naming it as a new community's first community admin, is refused.

## Removing someone

Removing a community user takes `members` in their community; removing a server admin takes
`delegate`, so only root does it.

- **What ends:** signing in is refused, their roles end, every API key they issued is
  deleted, and the gate skips their submissions still waiting.
- **What stays:**
  - they stay listed among the community's users, marked removed with the date;
  - everything they published stays in the record under their name, and citations of them
    still validate;
  - the collections they own keep them as owner, and the community admin manages them;
  - an export carries them as removed, and an import brings them in still removed.
- **Their handle is retired:** someone returning joins under a new handle.

## Seeing it live

`/symposium access` lists the six roles with their grants, as the server defines them, and the
collections a user holding each always reads (`record`, for `community-member`), followed by your
own roles and grants in the session the command works in. `/symposium users list` shows everyone's roles,
and `/symposium list-api-keys` each key's.

How the data server enforces these rules on every request is described for developers in
`api/DESIGN.md`, in a clone of the repository (it is not part of the installed skill).
