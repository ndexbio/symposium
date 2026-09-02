# Policy — preserve, do not interpret

This is **community policy for this deployment**, not part of the specification and not part of
any role. It applies to anyone publishing an imported Artifact. It sits beside
[`embedding-and-size.md`](embedding-and-size.md), which governs how much you may embed; this
document governs what you may change on the way in.

## The rule

> **An import renders. It does not decide what the data means.**

The specification already requires `import_method` to state what you selected and how you
processed it, "precisely enough that another Member can judge what your rendering may have
added or lost" (S1.10). This document is what that means in practice for supplementary tables,
which are the messiest material this community handles.

Everything below follows from one observation: **a supplementary table is not a dataset, it is
a document.** It carries captions, legends, merged headers, footnotes, publisher conventions
and the occasional mistake. Rendering it into a CSV is a translation, and every translation
loses something. Your job is to lose as little as possible and to write down exactly what you
lost.

## What you must not do

**Do not coerce a value.** If a measurement column holds the text `esiRNA synthesis poor` where
a number would sit, that is not a missing number. It is the reason the measurement does not
exist, and it is the most informative cell in the row. Coercing it to a null, a zero or an
empty string destroys a distinction the publisher took care to record.

**Do not resolve meaning by inference.** If a column holds `0.87/0.73` and you do not know what
the slash denotes, the Content description says so. A guess that reads as fact is worse than an
acknowledged gap, because the gap is checkable and the guess is not.

**Do not publish a second, cleaned copy of the same table.** One canonical rendering per source
table. A filtered copy divides citations between two tables that a later Member cannot tell
apart, and a row absent from the filtered copy cannot be cited at all — so a Member who tries
learns only that the row is missing, never why it was removed. If a filtered set is genuinely
needed by several Arguments, it is an **Analysis output** with a procedure, not a second Content
object on an import.

**Do not read the paper to resolve a spreadsheet quirk.** Bounded effort: if the answer is not
in the file, in its legend, or in an adjacent sheet, record the ambiguity and move on. The one
exception is when the data answers itself cheaply, as when a paired column reveals a delimiter's
meaning by aligning with it.

## What you must do

**Find the header by looking.** Row 1 is not the header in roughly a fifth of the sheets this
community has imported; a caption or a group label sits above it. State in `import_method`
which row you declared as the header and that you did so by inspection.

**Flatten a multi-tier header mechanically, and quote the original.** A CSV has one header row.
Where a sheet has two or three, join them with ` / ` into composite names and reproduce the
original rows verbatim in `import_method`. This is forced by the format, not chosen, and saying
so lets a reader reconstruct what you flattened.

**Drop only what is provably not an observation, and quote what you dropped.** Three classes
qualify and no others: columns with no header and no value in any row, which cannot be addressed
anyway; legend and footnote rows sitting inside the data columns; and phantom empty rows
produced by a sheet declaring dimensions larger than its content. Anything else stays.

**An added column is allowed when it is additive and lossless.** A column derived from cells
already present, that leaves every original cell untouched, is a service to later analysis: it
lets an Argument filter on a column rather than re-derive a test, and it keeps the flagged row
addressable and carrying its reason. Name the added columns explicitly in `import_method` as the
only content that is not the publisher's. A column that *replaces* or *reinterprets* an original
value is not additive and does not qualify.

**Where the publisher ships duplicates, import one and record the rest.** Supplementary
workbooks routinely carry the same table twice in different orderings, or a complete table
alongside filtered views of it. Verify computationally that the row sets are identical, or that
the subsets derive from a stated column, then import the canonical one and record in
`import_method` what the others were and how they relate. Importing all of them puts the
duplication problem into the record with the publisher's name on it.

**Point at the original.** Every imported Artifact carries a `download` Content addressing the
untouched source file on the file store. That is what makes all of the above safe: anything you
flattened, dropped or added is recoverable by a Member who disagrees with your judgment.

## Where the line falls

| | Importer | Analyst |
|---|---|---|
| Which row is the header | yes | |
| Flattening a tiered header | yes | |
| Dropping empty columns, legend rows | yes | |
| Adding a lossless flag column | yes | |
| Deciding a flagged row should be excluded from an analysis | | yes |
| Filtering, normalising, joining, recomputing | | yes |
| Stating what a packed value means | only if the file says | yes, with a procedure |

**Intent** The importer's contribution is fidelity, and fidelity is checkable. The analyst's
contribution is judgment, and judgment needs a procedure on the record. Putting judgment into an
import hides it in a place the record has no way to question.
