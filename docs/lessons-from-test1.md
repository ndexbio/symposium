# Lessons from the test_1 community, and the changes they call for

This records what six rounds of a real community taught us, and the changes to roles and
instructions made in response. It is written for whoever runs the next community, and for
anyone wondering why a role says what it says.

The community: 45 artifacts, two members and a principal, working over a corpus of published
virology supplementary tables. 0 FAIL throughout. Two supersessions. One positive finding
published and then withdrawn by the community's own scouting.

## 1. Most Arguments were not about biology

Of ten Arguments, seven made claims about the evidence — what a comparison could license, what
a denominator should be, whether an intersection had the power to mean anything — and three
made claims about viruses and host factors.

This was not drift. Every instruction pushed that way. "Do not infer absence from an unmeasured
gene" produces Arguments about measurement status. "State the purpose and the stakes" produces
verdicts about what the record can bear. The agents did as they were told and the accumulated
result was a record a biologist could not easily read.

The evidence Arguments were valuable: one overturned the community's only positive finding,
another stopped it publishing arithmetic as biology. The problem was organisational.

**Change.** A `genre` property on Argument — `finding` or `assessment` — so the two kinds sit
on separate shelves and a reader can take the findings first.

## 2. The reasoning about what data can prove was being done in the wrong place

The clearest case. An Argument titled

> UBE2J1 is required for hepatitis C RNA replication and restrains dengue RNA replication, and
> both measurements report the same step

spends most of its length establishing that a pseudoparticle assay and a replicon assay report
different lifecycle stages, and that the hepatitis C effect is at replication rather than entry.

That is a property of the DATASET. It is true whatever gene you care about, and it was
established while arguing about one gene, so the answer is welded to UBE2J1 and has to be
re-derived by the next Argument that needs it.

**Change.** A `reader` role that characterises a dataset once, after import and before
analysis: what each assay physically measures, at what stage, in what cells, what a non-hit
means, what the controls establish, what the source does not contain. It publishes a
characterisation others ground on, and publishes no Argument, because it makes no claim about
biology.

The pipeline becomes `importer -> reader -> analyst -> researcher`.

This is the change most likely to matter. Careful reasoning about what data can support is the
community's strongest habit and the thing human integrative work most often skips; the failure
was letting it tangle with a claim about a gene.

## 3. Titles and verdicts carried too many claims at once

Measured across the ten Arguments: titles average 18 words and three to four clauses, and
seven of ten verdicts assert and retract within a single sentence ("Supported that X, and
insufficient that Y").

A reader had to unpack the UBE2J1 title for several minutes to find which of its three claims
was being argued.

**Change.** Into `researcher` and `policy/discourse.md`: a title states ONE claim in about
twelve words; the verdict's first sentence is the judgment and qualification begins in the
second; if a title needs "and" to join two claims, it is two Arguments.

## 4. Provenance was checked five rounds too late

The community's only positive finding — that dengue and hepatitis C share a host-requirement
profile — was withdrawn when someone finally read the source paper's Methods. Dengue was
screened in Huh7 and hepatitis C in Huh7.5, a Huh7 derivative, and those two screens alone used
unpooled libraries while the two uncorrelated screens used pooled ones in unrelated cells.

The provenance was one freely available paragraph. A standing Argument had explicitly ASSUMED
it was unrecorded.

**Change.** Into `analyst` and `reader`: establish a source's provenance before computing over
it. Cell line, library, instrument, what the controls establish. Reading a Methods section is
cheaper than any analysis and invalidated more work than any analysis produced.

## 5. Serial publication shapes what gets argued

The first biological Argument took eight artifacts and eight gate cycles. Agents respond
rationally: a claim about a denominator grounds on one published cell, a claim about mechanism
needs an experiment nobody ran. The economics favour meta-claims, which is part of why finding
1 happened.

**Change.** Briefs name the phases and the intended last artifact. When that was done
explicitly, both members reached publishable Arguments inside one round.

## 6. What worked and is kept

- **Worked examples beat principles.** A prose instruction carrying "the EMC inserts
  tail-anchored membrane proteins" moved the biology-to-process vocabulary ratio from 0.33 to
  3.45 in one round. The same instruction as a principle had not.
- **Supersession.** A finding was withdrawn without erasing it, and the reasoning that led
  there stands and stays legible. A record that can be wrong in public is worth more than one
  that is never wrong.
- **Designed refusals.** A Ground bearing on two Assertions, an Assertion with no basis, a
  `supersedes` given as a string. Each was fixed by supplying what the gate asked for and never
  worked around.
- **Declared Assumptions.** `u_compiled` named the check that later overturned its own
  Argument. That is the mechanism working exactly as intended.

## 7. Instruction volume

A member session read roughly ten to twelve thousand words before publishing anything. The
roles were not the problem — 205 to 1,248 words each. The shared documents were:
MEMBER-AGENT-INSTRUCTIONS at 4,445 words and CANONICAL at 3,504, read by every session
whatever it was doing.

**Change.** Use the `sop` array that already exists in every role Contract and that only
`importer` populated. Task-specific material moves into `sop/` files named by the roles that
need them; the core stays short. A scout should not be reading the Argument authoring guide.
