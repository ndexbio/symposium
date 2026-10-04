# Moving a community off NDEx: `/symposium port`

`/symposium port <ndex_credentials_file> <ndex_url>` copies a Symposium community's record from
an NDEx server into a new, **empty** community on a Symposium Data server. The data server does
the work in the background; the command starts it, waits for it to finish, and prints the
result. It is not a sync: a community that already holds files is refused, so each community is
ported once.

## Before you start
- **A data server, operational**, with your admin key in place (`/symposium admin-config`, see
  the skill's README, section 2). The data server itself connects to NDEx, so it needs outbound
  access to the NDEx server.
- **Drain the gate.** Run the gate on NDEx until nothing is waiting. A member's submission the
  gate has not decided is not ported, because the NDEx admin account does not own it.
- **The NDEx admin account's credentials file**, a bound pair, readable only by you:

  ```json
  {"username": "<the community admin's NDEx account>", "password": "<its password>"}
  ```

  `chmod 600` it; the port refuses a file others can read. It is sent only to the data server,
  which holds the password in memory for the length of the port and never stores or logs it.
  Never paste the password into a chat.

## The order
1. `/symposium bootstrap --community community.json` creates the community (empty) and sets
   this directory's context. List the members you already know in `handles`; the port adds the
   rest.
2. `/symposium port <ndex_credentials_file> <ndex_url>` ports into it.
3. `/symposium bootstrap --community community.json` again: it writes an invite file for every
   author and reply recipient the port added to the roster. Hand each one over out of band.

## What is ported
From the NDEx admin account, every network it owns:
- networks marked `symposium_record` become files in `record`;
- networks marked `symposium_reply` (the gate's rejection replies) become files in `inbox`,
  readable only by the members they were shared with.

Each keeps its **exact bytes** (every sha256 is unchanged), its **name**, its original
**`created`** time and its **author**. The NDEx admin account becomes the data server's admin.
Every author and recipient joins the roster as a reserved handle, waiting for its member.

**Not ported:** undecided submissions (drain the gate first), external `download` files (their
artifacts keep their original location), and NDEx accounts and passwords.

## When it is refused
The command reports the reason:
- **404:** the context's community does not exist: run `bootstrap` first;
- **400:** the community already holds files: a community is ported once;
- **409:** another port is running on the server: wait, and run it again;
- **401 or 403:** this directory's context is not the server's admin;
- **`handle collision`:** an NDEx author or recipient, other than the admin account itself, has
  the data server admin's handle. Nothing was written.

Any failure writes nothing, and the community can be ported again once the cause is fixed.

## What members do afterwards
Each runs `/symposium setup --invite-file <community>-<handle>.invite` with the file you handed
over. Their handle, their authorship and the replies addressed to them are already there.
