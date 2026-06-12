# Why "Done" is a Defensible Standard, not a Proof

The hardest question in the validation model is completeness: *did the agent
find everything it should have?* This note explains why completeness cannot be
made provable, why that is acceptable, and why the move that rescues it —
recorded negatives under a versioned coverage procedure — is the most
important single idea in the trust architecture.

## Why completeness resists a clean test

Faithfulness is grounded: every claim points at a span, so a checker verifies
the link without re-deriving the science (see
[evidence-and-provenance](../spec/layer-a-scientific/06-evidence-and-provenance.md)).
Completeness has no such ground. To know what the report *omitted*, a checker
would have to know what the source contains that the report does not — which is
to say, it would have to redo the extraction. "Did the agent find every
dataset, every experiment?" has no closed-form answer, especially for
information that hides where extractors under-look: results sections and
supplementary materials, not just methods.

## The temptation, and why it fails

The temptation is to chase proof: add enough mechanical checks that
completeness becomes testable. Some incompleteness *is* mechanically catchable
— a locator sweep finds accession patterns the report missed; an
internal-consistency check flags an assay named in prose but absent from the
records — and the standard requires running these. But the residue is
irreducible: whether the agent correctly understood which experiments produced
which data, and found experiments described only narratively, cannot be proven
complete by any check short of redoing the work. Pretending otherwise would be
the same overconfidence the architecture exists to catch.

## The move that rescues it: recorded negatives

> An extractor is **done** when every claim is faithfulness-anchored, every
> required field is populated or explicitly marked absent, and a **declared
> coverage procedure has been run across all source sections, with its
> negative results recorded.**

The third clause is the crux, and the word that matters is *recorded*. "I
scanned methods, results, data-availability, and supplementary for accession
patterns and dataset mentions; none beyond the three catalogued" is a
**recorded negative** — it converts an absence into evidence. The agent is no
longer claiming "I found everything" (unprovable); it is claiming "I ran *this*
procedure across *these* sections and *this* is what it turned up, including
where it turned up nothing" (checkable, and honest about its own limits).

Completeness thereby becomes **a documented process trusted to a degree**,
rather than a guarantee. The trust is no better and no worse than the trust in
the procedure that was run.

## Why the coverage procedure must be versioned and cited

Because "done" rests entirely on the coverage procedure, that procedure has to
be a real, inspectable, **versioned** artifact — not a vague gesture at "I
looked carefully." A report cites coverage-procedure *name + version*; a reader
auditing the report retrieves *that exact version* and can judge whether it was
adequate. This has three payoffs:

1. **Honest labeling across time.** A report validated under v1.3 stays
   correctly labeled after v1.4 exists; re-validation under v1.4 is a distinct,
   logged act, not a silent upgrade.
2. **Independent improvement.** The procedure improves on its own track; every
   report that cited an old version remains interpretable.
3. **A rising bar.** The community decides which coverage procedures count as
   adequate, and that bar rises as agents improve. This is the
   [completeness frontier](../spec/layer-a-scientific/07-validation-model.md)
   research goal: how far completeness can be pushed toward procedural
   testability before it must fall back on SOP and judgment.

## Why this is where community SOPs do their real work

Completeness is exactly where "trust" stops being mechanical and becomes
social. No procedure can prove completeness; the community's *agreement* on
which procedures are adequate is what carries the residual trust. This is not a
weakness — it is how human science handles the same problem. No reviewer proves
a paper reported every relevant experiment; the field's shared standards for
"adequate methods" carry the trust, and those standards rise over time.
Symposium makes the same move explicit and machine-legible: the standard is a
named, versioned procedure, and "done" means "ran the standard and recorded
what it found, including the nothings."

## The honest dependency on orchestration

One more thing the recorded-negative framing makes visible: running a coverage
procedure "across all sections" presumes the orchestration gave the agent the
budget and the context to do so. When it did not — too small a batch, the
supplementary never loaded — the agent does not get to claim "done." It records
what it could cover and the verdict becomes VALID-WITH-GAPS. The standard stays
fixed; the shortfall is recorded, not hidden. This is the adequacy rule (see
[layer-separation.md](layer-separation.md) and
[CRITIQUE.md §7](../CRITIQUE.md)), and completeness is the place it bites hardest.
