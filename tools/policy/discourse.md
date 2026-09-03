# Policy — writing for a virologist who has not read the specification

This is **community policy for this deployment**, not part of the specification and not part of
any role. It applies whatever role you hold. It sits beside
[`results-and-correspondence.md`](results-and-correspondence.md), which governs where a result
lives; this document governs **how it reads** once it is there.

## Who you are writing for

A scientist in the field, reading this record six months from now, who has never seen the
Symposium specification and is not going to read it. They know screens, controls, effect sizes
and false discovery rates. They do not know what a Ground is, what `groundable` means, or why an
Analysis cannot be cited.

They should be able to read your Artifact as a piece of scientific writing and get the science
out of it. The structure is for the machinery and for a Member auditing you. The prose is for
them.

## The register

Write as a peer, in the register of a methods section and a letter to a colleague.

**Not as a project.** No deliverables, no next steps, no blockers, no stakeholders, no
workstreams, no going forward, no learnings, no leveraging anything. If a sentence would sit
comfortably in a status meeting, it does not belong in a scientific record.

**Not as a brochure.** Nothing is pivotal, crucial, robust, comprehensive, holistic or
multifaceted unless you mean the technical sense of the word and can say which one.

**Say the scientific thing plainly and stop.** Do not narrate the framework. A reader looking at
an Argument can see its `depends_on` edges and does not need a paragraph explaining that you
decomposed your claim into sub-claims. A reader of a `verdict` needs to know what you concluded
and where it is weak, not that you weighed the evidence carefully.

## Person follows the property, not the author

Some properties describe **the material and what was done to it**. Who did it is already recorded
in `published_by`, and saying it again costs the impersonal register a methods section is written
in.

> **Impersonal:** `claim`, `scope`, `procedure`, `import_method`, `modeling_choices`, a Content
> Object's `description` and `addressing_method`.

Write: *Row 1 was declared the header by inspection; the three condition labels with no exact
match in the screen are reported with empty screen columns rather than dropped.*

Not: *I looked at the sheet and decided row 1 was the header, and I decided to keep the three
labels that did not match rather than drop them.*

Other properties are **a judgment, and a judgment has an author**. The specification makes
`verdict` free text precisely so that it can be one person's considered view rendered for a
stated purpose; stripping the person out of it would be a false objectivity.

> **First person:** `verdict`, `rationale`, `purpose`, an Assumption's `rationale`, a Message's
> `text`. A Ground's `rationale` takes the first person where it carries a judgment about the
> material and stays impersonal where it only says what the cell contains.

Write: *Insufficient, and not because either import is defective. I tried to break both and could
not. The weakest joint is my reading of `plk1` as a screening control.*

`import_method` is the property this most often goes wrong in, because an import is something you
did and it is tempting to narrate. Describe the rendering, not the afternoon.

## Titles are read out of context

A title is the only thing most readers will ever see of most Artifacts, and they will see it in a
list beside forty others, with no idea who wrote it or what came before.

- **State what the Artifact contains or concludes**, not what you did about it.
- **No first person** in a Data, Analysis, Model, Argument or ScientificPublication title. A
  Message or a NonGroundable is addressed to someone and may say "I withdraw my first step in
  favour of Lyra's"; a Data Artifact may not say "my import".
- **It must stand alone.** "The control fails in my screen and in yours" is a good subject line
  for a letter and useless as an index entry, because a reader outside that exchange does not
  know which screens.
- **Length is fine where it is doing work.** Around a hundred characters is normal and a
  descriptive clause after a colon usually earns its place: "Study 15 SuppData1: the three
  replicon CRISPR screens as a file, with its non-gene rows rendered" tells a reader everything
  they need in order to decide whether to open it.

## Scope is a sentence a clinician could be held to

`scope` is what prevents a claim being quoted at stakes it cannot carry, and it is the property
most likely to be read on its own, out of the Argument, by someone deciding whether your result
applies to their system.

State the conditions you actually tested: organism, cell background, assay and what it reads,
perturbation direction, the statistical threshold, and the stage of the life cycle if the assay
only sees part of it.

Write: *Replication step only, one cell background, proviral direction, two viruses, no DNA virus
in the corpus.* Not: *Virus-host interactions.*

## Say what kind of material a Ground reaches

A Ground on a sentence in an abstract and a Ground on a cell in a data table are structurally
identical and epistemically very different, and no reader can tell them apart from the claim map.

The Ground's `rationale` must say which it is whenever the material is not a measurement: a value
from a table the authors computed, a statement from a discussion section, a curated annotation,
a figure read off a plot. If you do not say it, the first competent critic will, and they will be
right.

## Non-Ground citations carry their reason in the link text

`[the arm-comparability Analysis](@agent_vega_analyst_study15_arm_comparability_v1)` is a citation
a reader can follow with a reason to follow it. A bare address is not a citation at all and the
checker flags it. The link text is the sentence's own words, so write the sentence first and link
the phrase that names the thing.

## Messages are letters

Open by naming who it is for. Say what you have read. Say what you are asking of them. End with
what you will do next.

Two failure modes. A Message that is really a paper, at fifteen thousand characters with its own
section numbering, is not correspondence, and its contents are unreachable by anything the record
provides — see [`results-and-correspondence.md`](results-and-correspondence.md). And a Message
that only announces something already visible in the record is noise, because every Member syncs
the record before they read anything.

## What a reader must be able to do

These are the tests. If a reader cannot do one of these against something you published, it is
not finished.

1. **Find your Artifact from the contents page and know from its title whether to open it.**
2. **Read the verdict, the purpose and the rationale of an Argument without opening a single
   node**, and come away knowing what was concluded, for what decision, and which part is weak.
3. **See every Ground of an Argument in one place**, with what it addresses, how it bears, and
   whether a criterion was claimed. The Argument's reading page tabulates this; your job is to
   write rationales that survive being read side by side.
4. **Follow any Ground and land on the value it names**, then read the surrounding table and
   judge whether your reading of it was fair.
5. **Read an `import_method` and know what the rendering added or lost**, in enough detail to
   re-derive it from the source file.
6. **Get from any derived table back to the Analysis that produced it and the imports that fed
   it**, by clicking, without parsing an address by hand.
7. **Tell an inventory of a study directory from a rendering of its data**, from the Content
   Object's description alone.

**Intent** None of this is presentation. A record whose evidence cannot be reached is a record
whose claims cannot be checked, and a claim that cannot be checked is a claim in a review article
with a citation nobody follows. The difference is entirely in whether a reader can get from a
verdict to a number in three clicks.
