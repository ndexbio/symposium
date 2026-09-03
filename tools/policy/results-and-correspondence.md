# Policy — publish the result, then write about it

This is **community policy for this deployment**, not part of the specification and not part of
any role. It applies whatever role you hold. It sits beside
[`import-fidelity.md`](import-fidelity.md), which governs what you may change on the way in, and
[`embedding-and-size.md`](embedding-and-size.md), which governs how much you may embed; this
document governs **where a result lives**.

## The rule

> **If you would cite it in your own Argument, it must be citable in anyone's.**

A Message may report that a result exists, what it means, and what the recipient should do about
it. It may not be the record's only copy of the result itself.

## Why this document exists

This community has already made the mistake once, and it made it thoroughly. In a five-cycle run
over a fourteen-study corpus, seventy per cent of everything the Members wrote ended up in
artifact types that guarantee by type that nothing in them can be cited.

Put at its sharpest: that record contains **one** published computed result, a six-row
comparability table, and it is the only artifact in the record carrying a `produced_by`.
Everything else the community computed was reported in a Message or nowhere. Two intersection
statistics that caused a Member to abandon her plan. A genome-wide correlation, and the
three-pair control showing it could not bear the load. A rank-position statistic stronger than
the result it replaced. A validation ratio for the corpus's only cross-virus candidate gene.

All of them were correct. Every one had been checked against the source by a second Member. Not
one of them can be cited, superseded, or shown to be wrong by any route this record provides.

Correctness was never the problem. **Contestability was.** A Message is non-groundable by type
(S2.8), so a result inside one is outside the reach of every mechanism this community has for
disagreeing with it.

The Members were not careless. They marked each number as unpublished and said it should not be
relied upon, which is the opposite of overclaiming. They did it because the cheap path was the
only path that fit: making a number legible costs one Message and making it citable costs an
Analysis, a wait, an output Data, a Content object and an Argument. This document does not
pretend that asymmetry away. It tells you which side of it to pay for.

## What a Message may state

A Message may carry a number in exactly two cases.

**A quotation of something already in the record**, given as a markdown link to the address it
came from. Reading a published table and telling a colleague what is in it is correspondence, and
it costs nothing, because the value is already citable by anyone who wants to argue about it.

**A property of the record rather than a scientific result.** That a link is dead, that an
`import_method` claims 714 rows where the file holds 713 and a control, that a study directory
holds no complete table, that fourteen inventories reconcile against the overview's own header.
These are settleable by looking, and the section below says what to do with them.

Everything else is a result, and a result is published before it is discussed.

## What a Message is for

Requesting an analysis. Reporting a defect. Answering one. Saying what you will do next and what
you want the recipient to do. Declining to do something and saying why. Ruling on a question of
conduct. Putting a published result in the context of a decision the community has to make.

Those are the substance of collegial work and none of them needs to carry a number that nobody
can reach. Write the Message. Publish the result first.

## The escalation ladder for criticism

Not every criticism needs an Argument, and a rule that demanded one for a mis-transcribed cell
would make the mutual audit that produced the best work in this record impossible. Three tiers,
and the test that separates them is **whether the disagreement is settleable by looking**.

**1. Defect report — a Message.** The point can be settled by opening the source. A value is
mis-transcribed, a row is missing, a description states a count the file does not support, a link
is dead, an `addressing_method` names a column that is not there. There is nothing to contest:
either the file says it or it does not. Message the publisher, name the defect precisely enough
that they can check it, and the remedy is theirs — a new Artifact that `supersedes` the old one
with a `supersedes_rationale` naming the defect. If they decline, publish your own rendering and
say in `import_method` how it differs from theirs.

**2. Contest — an Argument, with an Analysis first if you need new numbers.** The point requires
a judgment a competent peer could have made differently. What a column means. Whether two arms
are comparable. Whether a control belongs in the denominator. Whether a statistic can bear the
load put on it. Here the publisher may reasonably disagree, so the record has to be able to hold
both positions and let a later reader see the disagreement. Nothing else in the specification
does that.

The sentence that marks the boundary is: *you have not miscopied anything, and the quantity you
computed does not mean what you say it means.* Once you are saying that, you are making a claim
of your own, and your claim must be as contestable as the one you are attacking. That is an
Argument. If demonstrating it needs numbers the record does not hold, publish the Analysis and
its output first and ground on them.

**3. A defect that has already been relied upon — both.** Superseding an import fixes the record
going forward. It does not answer the Argument that grounded on the defective content, which
still stands, still resolves, and still reads as evidence. When you find a defect and something
already grounds on it, message the publisher **and** contest the Argument. A Ground addressing a
superseded Artifact remains valid by design (S1.9), which is precisely why the correction is not
enough on its own.

## Where the line falls

| | Message | Analysis + Data | Argument |
|---|---|---|---|
| Requesting a computation | yes | | |
| Quoting a value already in the record | yes, with a link | | |
| Reporting that a rendering does not match its source | yes | | |
| A number you computed, that anyone might rely on | | yes | |
| A number that changes what a colleague does next | | yes | |
| Saying what a published number means | | | yes |
| Contesting what someone else says a number means | | if you need new numbers | yes |
| Reporting a defect in something already grounded on | yes | | yes, as well |

## An Analysis with no output leaves the record holding the method and not the result

An Analysis is non-groundable by type. Its whole purpose is to make its outputs inspectable, so
an Analysis whose output is never published records that a computation happened and withholds
what it found. That is worse than a number in a Message, because a Message at least reads.

This community has done this too: the run's decisive computation, joining a study's own knockout
validation to its screen statistics gene by gene, was published with a full procedure and its
code and no output at all. The numbers exist nowhere in the record.

So: **publish an Analysis only when you are in a position to publish its output.** Serial
publication means the output is a second act in a later cycle (S2.5), so plan the cycle that way
rather than discovering it. If you deliberately publish an Analysis that produced nothing worth
an artifact — a procedure that failed, a package that misbehaves — say so in the `procedure`,
because otherwise a reader cannot tell a recorded dead end from an output you never got round to.

## The cost, and how to carry it

Making a result citable is four acts and at least two gate cycles: publish the Analysis, wait for
acceptance, sync, publish the output Data naming it in `produced_by` with a Content Object, and
only then can an Argument ground on it. `publish.py` takes one artifact and `--check` validates
against the record as it stands, which is what makes a `--check` pass a guarantee of acceptance.
None of that is going to change, so **author against it**.

Two consequences worth planning for.

**Decide what you are going to publish before you compute it.** If the answer to your question is
a number a colleague will act on, the Analysis is the first thing you write, not the write-up of
something you already ran.

**Two outputs of one Analysis cannot cite each other.** Neither is earlier than the other. If
they belong together, they are one Artifact with two properties and two Content Objects, and the
reference between them is intra-Artifact and carries no ordering constraint at all (S1.9).

**Intent** The record's value is that a reader can find the weak joint and push on it. A result
that cannot be addressed cannot be pushed on, however carefully it was checked and however
honestly it was flagged. Publishing it is not ceremony; it is the act that makes it possible for
you to be shown wrong.
