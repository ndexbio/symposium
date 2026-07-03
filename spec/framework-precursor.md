# The Symposium Framework — Annotated Precursor

> **What this document is.** A precursor to the *framework* section of the Symposium
> paper: the description and supporting argument for the trust model, in the order an
> argument would present it — **not** the order we discovered it in, and **not** the
> order any implementation imposes. It is deliberately **separate from implementation**
> (in particular, from any realization of artifacts as knowledge graphs). It is
> *annotated*: it carries open-question and revision markers (**⊘ DEBATE**, **↻ REVISIT**)
> so it stays argued-with, not deferred to.
>
> **How it is structured — interleaved, two depths.** Each numbered section is presented
> twice in place: a **Pass A** statement of the principle in the abstract (no domain
> vocabulary), immediately followed by a **Pass B** grounding that cashes the same
> principle out against concrete representational and assessment choices. Pass A is
> allowed to incur *debts* — points that cannot honestly be made in the abstract — which
> the following Pass B pays. Reading A-then-B in place lets us judge, section by section,
> whether the abstract/grounded boundary is drawn in the right spot.
>
> Source spine: [core-architecture.md](core-architecture.md). This precursor restates
> that spine for an argument; the core-architecture doc remains the working technical
> reference.

---

## Register and vocabulary rules

This document has two readers fused: the **biologist**, who must find the argument
intuitive, and the **architect**, who needs the terms to be precise. The rules below
resolve the tension. They are constraints on the drafting, not decoration — if a sentence
violates one, the sentence is wrong.

**1. Three registers, kept separate.**

- *Scientific-method register* — for the epistemics. Familiar-technical terms a working
  scientist already reasons in: **assertion, claim, evidence, falsification, warrant,
  assumption, consensus, hypothesis (null / alternates), probativeness.** Use freely; this
  is the audience's native language. Define a coined term on first use.
- *Trust register* — for the graded-belief layer. **Trust-bearing**; evidence
  **increases or decreases trust**; an assertion is **trusted to a degree, for a purpose**.
  Introduced *early and deliberately* (see Rule 2).
- *Content register* — **object / relationship / property** — for the *internal structure
  of what an assertion is about* (e.g. AKT1 as object, *phosphorylates* as relationship).
  This is a **lower level** than the trust-bearing concepts and is **not introduced until
  the epistemic/trust layer is established.** Do not let it leak upward into the framing.

**2. Inoculate against binary belief, up front.** The most damaging first-contact misread
is that this is a machine for *proving assertions true or false*. A reader waiting for a
true/false proof will read every later move — interpretive distance, decision-relativity,
contestation, the absence of a stored strength — as evasion rather than as the point.
Therefore: **state before Section 1 that trust is graded, not binary; that evidence bears
on a claim by degree (it raises or lowers trust), as in falsification it never delivers
proof.** Pair the trust register with the falsification register so this reads as native
scientific method, not as a software belief-model.

**3. Symposium names axes; it does not grade them numerically.** Interpretive distance,
reliability, probativeness, and contestation are **named axes an assessor reasons over** —
*not* numbers Symposium computes, stores, or imposes. There is **no Symposium scoring
scale.** An individual assessor *may* bring a rubric (a numeric or ordinal scheme of their
own); that is **their projection**, exactly as adopting a particular controlled vocabulary
(e.g. BEL) is their projection — useful, optional, never baked into the framework.
"Interpretive distance" therefore names a **direction and an ordering-in-principle**, not
a metric; never write or imply a unit, a number, or a fixed scale for it.

**4. Quarantine engineering metaphors.** Terms that ask the reader to import a
software/structural-engineering image cost credibility with the scientific audience and
are banned from the prose:

| Banned | Why | Use instead |
|---|---|---|
| load-bearing | recent metaphor jargon; unfamiliar to most biologists | "critical to the argument," "the conclusion depends on it," "central to the claim" |
| node / edge | summons the **pathway-diagram frame** — the very "single knowledge graph" the framework declines to be (BEL avoided these terms for the same reason) | name the actual thing: **assertion / assessment / artifact**; for connections, **support relationship** / **support link** |
| DAG / directed acyclic graph / leaf / interior | graph register; same pathway-frame risk | **"converging lines of evidence,"** **grounded** (terminates at checkable ground), **traversable / inspectable**; *"the terminating ground"* not "leaf"; *"evidence built on other assertions"* not "interior." (A single parenthetical "formally, a directed acyclic graph" is permitted once, for the architect.) |
| gate-then-gradient | metaphor phrase | keep the idea, lose the phrase: "integrity is granted first; interpretive distance is then graded" |

**5. Keep these coined/technical terms — they earn their precision.** *Interpretive
distance* (define on first use; honor Rule 3), *probativeness*, *addressability* (coined;
flag and define on first use — there is no native equivalent and it does precise work
later). Keep "**grounding**" — it is epistemic, not graph-jargon.

**6. "Converging lines of evidence" carries "not a chain."** The structural claim that
trust rests on *many lines that converge on, and are shared across, assertions* — rather
than a single chain — is to be made in the **biologist's own native phrasing**
("converging lines of evidence," "independent support"), which carries it better than
"DAG" does. Reserve any graph framing for at most one aside.

> **Layering note (to confirm in drafting).** The intended division is:
> **trust layer** (assertion / assessment / evidence — the trust-bearing units) sits
> *above* the **content layer** (object / relationship / property — the internal structure
> of what an assertion is about). The framework's atom, the **assertion**, is closer to a
> *relationship-bearing-a-truth-claim* than to an object — which is why the content
> register is introduced only after the trust layer is set, and only where the internal
> structure of assertions actually needs discussing (Pass B of the vocabulary/precision
> section).

---

## Preamble — trust is graded, not binary

Before any of the machinery: a scientist does not *prove* a claim true and then believe
it. Evidence **bears on** a claim — it raises or lowers how far the claim can be trusted,
and for what. This is the ordinary logic of falsification: a result that survives a
genuine attempt to refute it *strengthens* trust without ever delivering proof; a result
that fails *weakens* it. Trust runs on a graded scale, and it is always trust **for a
purpose** — enough to design the next experiment is not enough to stake a clinical
decision.

Symposium is built on this graded notion throughout. It is **not** a machine that returns
*true* or *false* for an assertion. Everything that follows — how far an inference reaches
from its measurement, how much a test's result actually bears on a claim, why an
assertion carries no single fixed strength, why the same evidence can suffice for one
decision and not another — is a consequence of taking *graded, purpose-relative trust*
seriously. A reader expecting a true/false verdict at the end will misread each of these
as evasion; they are the substance.

Accordingly we speak throughout of assertions as **trust-bearing**, and of evidence and
assessment as **increasing or decreasing trust** — never as proving or disproving.

**A scope note set early, on purpose.** This document is about **epistemic trust in
scientific communities — specifically, communities of agents.** The operation of such
communities — including the one we have implemented and tested — also depends on the
publication of artifacts that are **not** trust-bearing: communications, summary reports,
recommendations. These are useful and real, they may *refer* to trust-bearing artifacts, but
they can never themselves enter the evidence for a claim. We name and distinguish those
artifact types in the artifact-types section below. Flagging it here so no reader expects
the trust machinery to cover every artifact the community publishes — it covers the
trust-bearing ones, by design.

---

## 1. What is trusted: the assertion, and publishing as judgment

### 1 · Pass A — the principle

The thing a reader of the scientific record trusts or doubts is not a *paper*, not an
*author*, and not a *model of a field*. It is a single **assertion** — one trust-bearing
statement that a member of the community has put forward. This is the atom of the whole
framework: trust attaches at the grain of the individual claim.

The reason to locate trust at the assertion, and not at the whole publication, is that
**credibility must not be laundered.** A paper can be excellent in nine assertions and
quietly wrong in the tenth. If trust attached to the publication as a unit, the strength
earned by the nine would extend, undeserved, to the tenth — the credible container would
carry the unsupported claim under the same banner. Trusting at the grain of the assertion
is what prevents a well-earned reputation from silently underwriting a claim that has not
earned it.

Putting an assertion forward is itself an act of **judgment**. A member who publishes is
not making a neutral deposit of content into a record; they are vouching — asserting that
what they put forward holds, in the context in which they put it. There is no
content-without-a-voucher. In this sense **every published artifact is a judgment**, and
the identity of the member who made it is part of what was published, not an annotation
added afterward.

> **Debt to Pass B (Rule 2 of register).** *What* gets vouched for — and the fact that a
> publication contains several *kinds* of trust-bearing move, only some of which the
> author evidences — cannot be made precise in the abstract. It needs the anatomy of an
> actual scientific paper. Held to Pass B.

### 1 · Pass B — grounded in how a scientific paper actually works

Consider what a published paper really is, with respect to trust. It is **not** one claim;
it is a structured bundle of many trust-bearing assertions standing in support relations —
and, crucially, the author has treated those assertions *very differently* from one
another:

- some they back with **evidence they produced themselves** (an experiment, an
  observational study, an analysis they ran);
- some they back by **citing another study's finding** — pointing outside the paper to
  work they did not redo;
- some they back by **citing a review** — adopting, wholesale, someone else's *summary
  judgment* of a body of work (a practice working scientists rightly regard as
  weaker, and sometimes as a way of not looking);
- some they simply **restate as accepted consensus**, with no evidence offered, because
  challenging them is not thought worthwhile ("AKT1 is a kinase");
- and some they leave **entirely unsupported** — implicit assumptions the argument needs
  but never names.

This anatomy is what Pass A could not say in the abstract, and it is the thing the
framework is built around. The crucial observation is the **last row** — but stating its
fix carefully matters, because the obvious overstatement is false.

The overstatement to avoid: *"Symposium makes every tacit move explicit."* It does not,
and could not. Some assumptions **must** go unstated — not even declared — because any
reasonable reader in the target audience would make them too; spelling them all out is an
unbounded task ("I assume matter is composed of atoms") that buries the argument rather
than clarifying it. A discipline that demanded total declaration would be unusable, and
would mistake the goal.

What Symposium actually does is **move the line, and supply a standard for where the line
belongs.** The standard is the **"any reasonable reader" bar**: an assumption that every
competent reader in the *intended audience* would already grant may stay silent; an
assumption such a reader would **not** automatically grant — or that is critical to the
argument — ought to be surfaced. Around that bar the framework provides three things a
paper does not: a **structure** for declaring an assumption or a grounding choice when one
is surfaced; explicit **choice points** for *when to stop digging* and record that one
stopped; and **guidance** toward meeting the bar. It does not provide a guarantee. Members
exercise judgment, and not all will judge the bar well — but they are given structure and
guidance for a choice a paper leaves wholly implicit.

This is the concrete cash value of "every artifact is a judgment." The unit that
corresponds to a scientific paper, in Symposium, is the **assessment** (developed in
Section 5): an authored bundle of grounding choices over a set of assertions, in which the
moves a paper makes tacitly become **declarable** — declared *where the bar calls for it*,
with a brief explanation of the non-obvious cases, and deliberately left silent where a
reasonable reader needs no help. The framework does not invent a new way to argue from
evidence; it takes the one scientists already use, names the point at which an assumption
should stop being silent, and gives members the structure to honor it.

> **⊘ DEBATE 1·B-i — "every artifact is a judgment" vs. the data-only artifact.** A
> deposited dataset with no claim drawn from it still carries a judgment (*this is what we
> measured, faithfully*) — an integrity-and-faithfulness voucher, not an interpretive one.
> Confirm we want "judgment" to span both the faithfulness voucher and the interpretive
> voucher, rather than reserving the word for the interpretive case. (Resolution likely
> falls out of Section 3's two flavors of ground.)

> **↻ carry-forward.** Two threads opened here resolve later:
> (a) the "cite a review = adopt a summary judgment" row pre-loads the
> *adopt-a-prior-assessment* termination choice (Section 5); and
> (b) the **"any reasonable reader in the target audience" bar** *is* the
> **decision-horizon** of Section 6 — "target audience" is a decision-class. Choosing the
> bar well is choosing the horizon well; the siloed reviewer's failure (Section 6) is
> setting the bar to one's own silo. A review citation is the compound case: someone
> else's assessment, made for *their* horizon, adopted for *yours*.

> **↻ carry-forward — a paper is a *self*-assessment (and often a dataset too).** The unit
> a paper corresponds to is more exactly a **self-assessment**: the author asserts claims,
> builds the evidence for *their own* claims, and some of the grounding data is *theirs,
> newly produced* — so the integrity voucher (Section 2) and the authored-procedure
> grounding choice (Section 3) are self-directed. This sets up a distinction developed in
> Section 5: taking in a literature paper can mean **formalizing their self-assessment**
> (faithfully reconstructing their evidence and reasoning, attributed to them) or
> **performing an independent assessment** (making one's own evidence choices over the same
> claim — bringing in datasets they did not use, running analyses they did not run).

---

## 2. Two factors in trust: integrity, and interpretive distance

### 2 · Pass A — the principle

Trust in any assertion factors into two things that are worth holding rigidly apart,
because they fail in different ways and are earned by different means.

The first is **integrity**: did the source report honestly and without error? This is a
property of the *source*, not of the reasoning — a question of whether what was reported is
what actually happened, free of fabrication, manipulation, or careless mistake. Integrity
is granted or withheld, and it conditions everything else: if a source did not report
faithfully, no amount of careful reasoning built on its report is safe. It is the axis on
which **reputation** does its work — a member's belief in another source's integrity is
informed by that source's track record.

The second is **interpretive distance**: *granted* that the source reported faithfully,
how far does the asserted conclusion travel from what was actually measured? "We recorded
this band on this gel" sits close to the measurement; "protein A phosphorylates protein B"
travels a long way from it, across layers of inference and field belief about what the
technique licenses. This is a property of an assertion's *support*, and — honoring the
register rule — it is a **direction and an ordering in principle, not a number.** Symposium
does not score it; it gives members the means to *see* and *reason about* it.

The two compose in order: integrity is **granted first** (about the source); interpretive
distance is then **reasoned about** (about the support). One cannot grade the climb from
measurement to claim until one has granted that the measurement was honestly reported.

**This framework instruments the second factor and deliberately sets the first aside.**
Integrity, reputation, and the detection of bad-faith or erroneous sources are real,
important, and a **different study.** Interpretive distance, support structure, and how
they compose into auditable trust can be developed and demonstrated *while holding
integrity fixed as granted* — and that is what we do here.

> **Debt to Pass B.** "Set integrity aside" is too clean to be honest in the abstract. The
> scope-out has a cost that must be stated plainly, and integrity does not stay fully
> outside — it re-enters by a side door that Pass A cannot show. Held to Pass B.

### 2 · Pass B — the cost of the scope-out, and where integrity re-enters

Setting integrity aside is a real commitment with a real price, and the framework is only
honest if it names the price as loudly as it claims the benefit.

**The price: this framework is cooperative by assumption.** Holding integrity fixed as
granted means a *dishonest* source defeats the machinery entirely. Every guarantee that
follows — that grounding is checkable, that an outsider can audit work without redoing it —
holds **only for sources reporting in good faith.** A fabricated measurement, faithfully
quoted and cleanly grounded, is indistinguishable within this framework from a real one;
the audit trail certifies that the source *said* it, never that the world *is* that way.
"Auditable" must therefore never be read as "honesty-guaranteed." A reader who takes the
auditability claim to cover fraud has misread the scope, and we say so directly rather than
let the word carry more than it can.

The justification for the scope-out is **orthogonality**: integrity is sufficiently
independent of the flow from measurement to assessed conclusion that holding it fixed does
not distort the flow we are studying. We can build and demonstrate the machinery of
interpretive distance and composition without first solving reputation. That this is a
*separable* study is the claim; that it is a *complete* account of scientific trust is not,
and we do not make it.

**But integrity does not stay wholly outside — and far from being an embarrassment, its
manner of re-entry is one of the framework's strongest claims to describe science as it is
actually practiced.** It re-enters not as a second kind of ground but as a **recorded
decision to stop short of ground** — a *deliberate non-grounding.* When a member decides
to *stop digging* because they accept a source's integrity on a point — "I trust this
group's assays in this organism; I take this measurement as given and will not reconstruct
it" — that is not evidence; it is a recorded choice *not to gather more*, one of the
termination choices developed in Section 5. Checkable ground (Section 3) and a recorded
decision to stop short of it are **two different acts**, and we keep them distinct: *here
is the material you can inspect* is not *I choose to rely on this source and dig no
further.*

Why this strengthens rather than weakens the account: **real scientific communities run
overwhelmingly on exactly these non-groundings.** A reader accepts or rejects a paper's
findings on a ladder of diligence, and the cheap rungs dominate:

- on **reputation alone** — the authors, the journal — *common*, and often only tentative;
- after **critical reading** of the paper — done when the reader cares enough;
- after **reanalyzing the data or cross-checking the cited support** — *rare.*

A framework whose only floor were checkable ground would describe a community that does not
exist: one that re-derives everything it uses. Symposium models the real community
*precisely because* "I accept this paper as reliable" is a first-class, **recorded**
termination choice sitting alongside checkable ground. The one thing it adds over current
practice is to make the *depth* of that choice **legible** — today a citation looks
identical whether the citer reanalyzed the data or merely trusted the masthead. So
integrity is excluded **as a modeled quantity** — nothing is computed about it, no
reputation score is stored — yet a member's *reliance* on it is **in scope and recorded**,
as the honest depiction of how trust actually terminates in practice. (This is the
depth-of-diligence ladder, developed in Section 5.)

> **↻ REVISIT 2·B-i — say the exclusion as loudly as the thesis withdraws its boldest
> analogy.** This scope-out should be stated with at least the prominence the trust thesis
> gives to renouncing the self-driving-car framing — named, justified by orthogonality,
> and paired with the plain admission that a dishonest source defeats the architecture.
> Quiet scoping here would let "auditable" over-promise.

> **✓ RESOLVED 2·B-ii — the integrity-assumption floor is a deliberate non-grounding, and
> we say so loudly.** Evidence bottoms out either in (a) **checkable ground** a reader can
> inspect (Section 3), or — and this is a *different act*, not a second kind of ground —
> (b) a member's **recorded decision to stop short of it** because they accept a source's
> reliability. Far from a concession, (b) is the point at which the framework demonstrates
> it captures the *actual operation of scientific communities*, where reputation-based and
> critical-reading terminations vastly outnumber full reanalysis. The grounding headline is
> therefore stated honestly as: *evidence bottoms out in checkable ground, or in a recorded
> choice to stop short of it* — never as "checkable ground" alone.

---

## 3. Grounding: where trust bottoms out, and how it composes

### 3 · Pass A — the principle

Trust cannot regress without end — but in this framework it also does not rest on a single
unbroken chain of reasoning. It rests on **converging lines of evidence**: an assertion is
typically supported by *several* independent lines; the same line of support is *shared*
across more than one assertion; and support added later attaches to assertions made
earlier. This is the ordinary shape of a well-supported scientific result — independent
lines that converge — and it is what makes the support **traversable**: from any
assertion, a reader can follow the lines back toward where they bottom out. *(Formally,
this is a directed acyclic graph; we use the scientist's phrasing in the prose.)*

Where do the lines bottom out? The honest answer, carried in from Section 2, has **two
parts** and we state both:

1. **In checkable ground** — material a reader can directly inspect to confirm that what
   was reported really is what the source contains. This is the framework's boundary with
   the record: not "trust that the agent read it right," but "here is exactly what was
   relied on, so you can check it yourself."
2. **Or in a recorded decision to stop short of ground** — a member's declared choice to
   rely on a source and dig no further (Section 2's deliberate non-grounding). This is not
   a kind of ground; it is a recorded *refusal to extend* the line, legible and
   questionable as such.

What checkable ground certifies is narrow and exact, and the narrowness is the point: it
certifies **faithfulness** — that the reported material genuinely is in the source — and
**not interpretation** — not that it was read correctly, weighed correctly, or means what
the member took it to mean. Faithfulness is checkable by anyone; interpretation remains
open to dispute. The ground does not foreclose argument; it **enables** it, by putting the
exact relied-upon material in front of the reader to contest.

Above the ground, assertions that build on *other* assertions do not re-quote the
material beneath them. They compose **by reference** — pointing at the assertions they
rely on as whole, addressable units. The boundary with the record demands exact,
inspectable material; the interior of the commons is held together by reference. The
asymmetry is deliberate (Pass B says why).

> **Debt to Pass B.** "Checkable ground" is stated abstractly here, but it has **two
> concrete forms** that behave differently, and *which form a member reaches for — or
> whether they reach for ground at all — is itself a recorded choice that a later member
> can challenge.* That cannot be shown without the concrete forms. Held to Pass B.

### 3 · Pass B — the forms of ground, and the choices that produce them

**Checkable ground comes in two forms — two flavors of *faithful pointer* — not one.**
What they share is the certification: each points at exact source material a reader can
inspect for faithfulness. What differs is what they point into.

- **A text pointer (a verbatim span).** The terminating ground for a claim drawn from a
  document is the **exact source text, copied** — never paraphrased, never stitched into
  false contiguity. The quoted words travel *with* the assertion, so faithfulness is
  checkable even against a source that later moves: the reader sees the very text relied
  on. This is checkable **by value** — the material is carried.
- **A data pointer (a locator into a dataset).** The twin, on the data side: "in derived
  table T, gene A is the fifth-most-significant differentially expressed gene." This is as
  faithfulness-checkable as a quotation — a reader resolves the locator against the dataset
  and confirms the value — and it sits equally close to the measurement. But it is
  checkable **by reference**, not by value: the pointer carries an *address*, and
  confirming it requires resolving that address against the dataset *as it stood.* So the
  data pointer inherits a dependency the text pointer escapes — it rests on the dataset
  having a **stable, resolvable identity** (a known gap; see the identity note below).

That these two are *flavors of one mechanism* — faithful pointers certifying faithfulness,
not interpretation — rather than two unrelated mechanisms, is what keeps Section 2's
grounding headline a single idea with a text side and a data side.

**Reaching for ground at all — and which kind — is an agent's recorded choice, open to
challenge.** This is the part Pass A could not show. When a member grounds a data claim,
they face a choice that is *theirs to make and theirs to defend*:

1. **Point straight at the dataset** — judge that "row 5 of table T" is a
   faithfulness-checkable locator that speaks for itself, and terminate there. Cheap, and
   often right.
2. **Record the procedure that produced the data** — judge that *how* the table was
   derived must be on the record, and so author an analysis (a recorded procedure that
   emits derived data), grounding the claim against *that*. More expensive, more legible.
3. **Reference an analysis someone else already recorded** — neither point raw nor author
   anew, but compose by reference onto an existing recorded procedure.

None of these is dictated by the data; each is a **judgment about how much of the
production needs to be legible**, recorded as the member's choice. A *later* member can
contest it: "you pointed straight at the table; I want the analysis that produced it on the
record before I will rely on this." This is the same depth-and-termination machinery that
governs literature import (Section 5) — here reaching the data side of the ground. The
choice of where to put the ground is not infrastructure; it is part of the argument, and it
is auditable as such.

This also settles a question left open in Section 1: a deposited dataset *with no claim
drawn from it* still carries a judgment — the **faithfulness voucher** (*this is what we
measured; the data pointer resolves truly*) — distinct from the **interpretive voucher** a
claim carries. "Every artifact is a judgment" spans both: the data pointer is precisely the
form the faithfulness voucher takes.

**Why the interior composes by reference, not by ground.** Holding the boundary with the
record to exact, inspectable material is what makes audit possible. But forcing that same
exactness *inside* the commons — making every assertion re-quote the exact material of
every assertion beneath it — would breed a precise but unreadable tangle, defeating the
legibility the framework exists to provide. So the rule is asymmetric on purpose: **exact
material at the boundary with reality; reference in the interior of the commons.** A member
who wants to check an interior line follows the reference down to the assertion it points
at, and only at the bottom — at the boundary — does the demand for exact, checkable
material return.

> **⊘ DEBATE 3·B-i — the interior rests on stable identity, and the data pointer now does
> too.** Composition by reference assumes assertions and artifacts have identifiers that
> *stay put.* The reference implementation's identifiers are resolvable but **not portable**
> (copying re-mints them, breaking references). With the data pointer (form 2 above), this
> identity dependency reaches the **ground layer**, not just the interior: a data pointer is
> only as checkable as the dataset's identity is stable. No portable-identity design yet;
> flagged as a real gap that the grounding story leans on at both layers.

> **✓ RESOLVED (was 1·B-i) — the data-only artifact carries a judgment.** Yes: it carries
> the *faithfulness voucher*, the non-interpretive twin of a claim's interpretive voucher,
> realized as the resolvable data pointer. "Every artifact is a judgment" holds for data
> deposits without straining the word.

---

## 4. The support relationship: why "how strong is the evidence?" is the wrong question

### 4 · Pass A — the principle

When one assertion supports another — a measurement supports a claim; a claim supports a
broader claim — it is tempting to ask *how strong* that support is, as if the answer were a
single grade. Existing practice encourages this: evidence gets stamped with a label from a
fixed vocabulary — *established, supported, inferred, tentative, contested* — as though
strength were one quantity running from weak to strong.

**That single quantity does not exist, and treating it as one hides the questions that
matter.** A support relationship can be strong in one respect and weak in another, and the
respects are independent. Pulling them apart, at least three distinct properties hide
inside "how strong":

- **Interpretive distance** (Section 2) — how far the conclusion travels from what was
  actually measured. A near-readout sits close; a mechanistic claim from an indirect signal
  sits far.
- **Reliability** — how trustworthy the *test itself* is: its sensitivity, its accuracy,
  its proneness to artifact. This is genuinely independent of interpretive distance — a
  test can sit *close* to the measurement yet be *unreliable* (a direct readout from a
  flaky instrument), or sit *far* yet be rock-solid.
- **Probativeness** — how much the *result* actually bears on the claim, *discounted by
  whether the test's enabling assumptions hold in this case.* A test worth doing in general
  can be nearly uninformative here if the conditions it relies on cannot be defensibly
  assumed — regardless of its distance or its reliability.

And one property that the "strength label" misfiles entirely, because it is **not a
property of any one support relationship at all**:

- **Contestation** — whether, across the *whole* assembled body of support, some lines tend
  to *falsify* the assertion while others survive the attempt. "Contested" was listed among
  the strength labels as if it were a grade of one relationship; it is in fact a feature of
  the *shape of the assembled evidence* — a property that exists only once a member has
  gathered the competing lines together.

Because these properties are several, independent, and — for contestation — properties of
an *assembly* rather than of a relationship, **an assertion carries no single stored
strength.** There is no number attached to it waiting to be read off. Its standing is
**worked out afresh by each member who assesses it**, over whatever body of support that
member assembles, weighing these distinct properties for the decision at hand. The
assertion is fixed; how strongly it is supported is not a stored fact about it but a result
of an assessment (Section 5).

Two cautions, both from the register rules. First: naming these properties is **not**
introducing a scoring scheme. Symposium gives members the vocabulary to *see and reason
about* distance, reliability, probativeness, and contestation; it computes no values for
them and stores no grades. A member may bring a rubric of their own — that is their
projection, never the framework's. Second: replacing one fixed vocabulary with four named
properties is a *dissolution*, not a new fixed vocabulary. We are unbundling a question
that was being answered too crudely; we are not proposing four new stamps.

> **Debt to Pass B.** *Why* the old single-label vocabulary felt workable for so long — and
> exactly how each of its labels smuggled several of these properties together — is best
> shown against the specific legacy vocabulary it replaces. Held to Pass B.

### 4 · Pass B — against the legacy strength vocabulary

The concrete target is the inherited five-label scheme — *established · supported ·
inferred · tentative · contested* — under which a piece of evidence was tagged with one
word meant to convey its weight. Seen against the four properties, each label turns out to
be a *blend* a reader cannot unmix:

- *inferred* silently fuses **interpretive distance** (the conclusion is several inferential
  steps from the measurement) with low **probativeness** (the inference rests on
  assumptions that may not hold). Two assertions both stamped *inferred* can differ
  completely in which of these is the problem — and the fix differs accordingly.
- *tentative* blends low **reliability** (the test is shaky) with low probativeness and with
  *contestation* (other evidence pushes back). A reader sees one weak word and cannot tell
  whether to distrust the instrument, the inference, or the existence of opposing results.
- *contested* is the clearest mistake: it names a property of the **assembled body** of
  evidence and files it as if it graded a single relationship — so it could never be
  recorded correctly on one support link in isolation, because it is not about one link.

The cost of the blend is not pedantic. Each of the four properties **calls for a different
response**: large interpretive distance invites re-deriving with closer evidence; low
reliability invites a better test; low probativeness invites checking whether the enabling
assumptions hold in this case; contestation invites weighing the opposing lines against
each other. A single label that fuses them tells a member *that* the evidence is weak while
hiding *why*, and therefore hides *what to do about it.* Dissolving the label is what makes
the next action legible.

This is also where the **self- versus independent-assessment** distinction (Section 1's
carry-forward, developed in Section 5) first bites concretely. Reliability and
probativeness are judged differently depending on *whose* test it is: an author assessing
their *own* newly produced data is vouching for a test they ran; a member performing an
*independent* assessment is judging a test they did not run — and may choose to *lower the
interpretive distance themselves* by bringing in other datasets and re-deriving, rather
than accept the author's reliability claim. The four properties are not read off the
evidence once and for all; they are evaluated by an assessor, and *which* assessor, with
*what* independent evidence, changes the evaluation. The support relationship has no
strength until someone assesses it — which is the whole of Section 5.

> **↻ REVISIT 4·B-i — replacement representation deferred, not designed.** We have
> *dissolved* the single-label scheme into four named properties; we have **not** designed
> how a member records them — whether each is noted per support relationship, how
> contestation is surfaced over an assembly, what (if any) ordinal language is offered
> without tipping into a mandated scale. Inventing that now would be premature and would
> risk re-introducing the fixed vocabulary we just removed. Flagged as the next concrete
> modeling task, to be done in a way that honors Rule 3 (names, not scores).

---

## 5. Assessment: the central act, and how the regress ends

### 5 · Pass A — the principle

Everything so far converges on one act. An assertion has no stored strength (Section 4);
its support bottoms out in checkable ground *or* in a recorded decision to stop short of it
(Sections 2–3); whoever wants to know how far to trust it must do something. That something
is an **assessment**: the act in which a member assembles the support for an assertion,
weighs it, and reaches a judgment of how far to trust it — and the recorded artifact of
that act. The assessment is the center of the framework. It is where the static structure
of assertions and support becomes an actual judgment, and it is the unit that corresponds
to a scientific paper (Section 1).

An assessment does four things:

1. **It assembles the support** — gathering the lines of evidence for *and against* the
   assertion into one body the member will weigh. Different members assemble different
   bodies; the assembly is a choice, not a given.
2. **It records where it stops** — the **termination choices** that bound the regress
   (below). This is the part current practice leaves silent.
3. **It applies judgment** — weighing the dissolved properties of Section 4 over the
   assembled body. No formula does this; the member judges, and the judgment is theirs to
   defend.
4. **It is made for a purpose** — its conclusion is "trust sufficient (or not) *for some
   decision, or class of decision*," never an absolute verdict (below).

Because an assessment is itself published, it is **both a consumer of support and a new
piece of support**: it reads the body of evidence and, once recorded, becomes something
other members can build on, adopt, or challenge.

**Ending the regress.** Assessments can in principle recurse without end — one can always
assess the assessment beneath. A long-running scientific debate legitimately has many such
layers. The regress is ended not by reaching some epistemic bedrock but **economically, by
a recorded decision to stop** — and there are three such decisions:

- **Assume and proceed** — "I take this assertion as true (or false) for now and move on."
- **Abandon the line** — "I cannot resolve this, and I choose to spend my effort
  elsewhere," recorded as unresolved rather than silently dropped.
- **Adopt a prior assessment** — "someone already assessed this for a purpose like mine; I
  accept their judgment and will not repeat the work."

The discipline is not that members dig to the bottom — they cannot, and should not try. The
discipline is that **wherever they stop, the stopping is recorded** and therefore legible
and questionable, rather than hidden. Where to stop is governed by the **"any reasonable
reader" bar** of Section 1: stop where a competent reader in the intended audience would be
satisfied, surface what such a reader would not simply grant — a judgment members make, and
make with varying skill, but now make *on the record.*

> **Debt to Pass B.** The three termination choices, the depth a member digs to, and the
> "self versus independent" distinction are all the *same machinery* viewed from different
> sides — and that only becomes visible against the concrete case the framework most needs
> to absorb: taking in the existing literature. Held to Pass B.

### 5 · Pass B — the depth-of-diligence ladder, and self versus independent

The case that proves the machinery is **literature import** — the one current systems treat
as a special primitive ("cite the paper") and the one Section 2 already showed runs, in
real communities, overwhelmingly on cheap terminations. Here is that practice ladder from
Section 2, now seen as a sequence of **recorded depth choices**, each a legal place to
stop:

1. **Faithfulness only.** Confirm the source really makes the claim — the text pointer
   resolves, the words mean what they are taken to mean — and stop. Integrity is granted,
   not checked; the branch terminates at "they said it." *This is the reputation-tier
   termination of Section 2, and it is exactly what a bare citation is.*
2. **+ read the methods.** Extend into *how* they reached the claim; weigh the interpretive
   distance of their inference. *This is the critical-reading tier.*
3. **+ re-run their analysis.** Pull their data in as support of your own and re-derive,
   *shortening the interpretive distance* by reproducing the step yourself rather than
   trusting it. *This is the reanalysis tier.*
4. **+ trace their cited support.** Follow the references *they* relied on, extending your
   assessment across into the work beneath theirs.

The point Section 2 promised, now precise: **a citation is just rung 1 with integrity
granted and the branch terminated at faithfulness.** Current practice records *only* that
rung 1 happened — and records it identically whether the citer stopped at rung 1 or climbed
to rung 4. Symposium makes the **depth itself a recorded, questionable property** of the
assessment. That is the single concrete thing it adds over the citation: not a new way to
read a paper, but a record of *how deeply this one was read.*

This ladder is also where **self- and independent assessment** become one mechanism seen
from two ends (Section 1's carry-forward). A scientific paper is a **self-assessment**: its
author assembles support for *their own* claims, vouches for data *they* produced, and
records (implicitly) their own termination choices. When another member takes that paper
in, they choose where on a spectrum to stand:

- **Formalize the self-assessment** — reconstruct the author's evidence and reasoning
  faithfully into the framework's structure, attributed to them, claiming no independent
  judgment of one's own. This is rung 1–2 territory: making *their* assessment legible
  without substituting *yours.*
- **Assess independently** — make your *own* assembly choices over the same claim: bring in
  datasets they did not use, run analyses they did not run, terminate different branches.
  This is rungs 3–4 with *substitution of your own evidence* — and it produces a new
  assessment that *references* their paper rather than merely restating it.

Independent assessment is therefore not a separate mode bolted on; it is **choosing the
deeper rungs while supplying your own evidence.** The same depth ladder spans from "I
faithfully record what they claimed" to "I rebuilt the case myself and reached my own
judgment," and *where on it an assessment sits is recorded* — which is exactly what lets a
later reader tell a translation from an independent confirmation, a distinction the
citation world erases.

**An assessment carries two kinds of content, and only one of them is trust-bearing.**
Alongside the assertions, the support, and the recorded termination choices — the
trust-bearing structure — an assessment may carry **rationale**: explanation of *why* the
member made a choice. These are different in kind, and keeping them apart matters. Suppose
a member re-runs an author's analysis (rung 3) but chooses a different test — "I ran a
Wilcoxon rather than the authors' *t*-test because I suspect the values are not
approximately normal." That explanation is **valuable but not trust-bearing**: it annotates
a *choice*; it is not evidence for any assertion. The analysis result stands or falls on its
own support, entirely apart from the member's motivation for running it. Rationale is
decision-support for *later* members — it helps an agent choosing which dataset or method to
reuse — and it lives outside the support structure, raising or lowering trust in nothing.

The subtle case sharpens the line. Suppose the member *actually ran a distribution
analysis* to justify the Wilcoxon choice. That analysis raises trust in **the decision to
act** — that choosing Wilcoxon was well-grounded — but contributes **nothing to trust in
the Wilcoxon result itself**, which still stands on its own support. *A well-justified
decision to run a test* and *a trustworthy test outcome* are independent; treating the
first as evidence for the second is a category error. (And such a justifying sub-analysis
sits at the altitude of a faithfulness-checkable datum — like "gene A is the
fifth-most-significant DEG." Reifying it as its own artifact is a **poor choice, not an
error**; the broader question of *what earns its own artifact* is the reuse-driven
separation spectrum, taken up in the artifact-types section.)

**Decision-relativity, and the optional decision statement.** An assessment's verdict is
"trustworthy enough" only *relative to a decision and its stakes* — and, as Section 6 will
develop, relative to *how wide a class* of future decisions the assessor held in view (its
**horizon**). The same assembled body
of evidence is sufficient to justify the next exploratory experiment and insufficient to
justify a clinical commitment; there is no stakes-free "enough." A member *may* record a
**decision statement** — "I assembled this to a depth sufficient for me to make decision X"
— but it is an **optional annotation**, not a required field. The reason it can be optional
is the heart of the design: **the depth choices are inherent in the assembled assessment
regardless.** A later member can read *how deep this assessor went* directly off the
recorded termination choices and decide for themselves whether that depth meets *their own*
stakes — doing whatever further work they choose. The decision statement only *explains why
the author stopped where they did*; the stopping itself is already legible without it.

> **↻ carry-forward to Section 6.** "Sufficient for a decision, or *class* of decision"
> hides a dimension this section deliberately leaves flat: *how wide* a class of future
> decisions the assessor held in view. That width — the **decision horizon** — is what
> separates a member assessing for their own next step from a reviewer assessing for the
> field's future use, and it is the hinge of the cross-group argument. Developed in
> Section 6.

> **⊘ DEBATE 5·B-i — does "formalize the self-assessment" import the author's silent
> assumptions, or expose them?** Faithfully reconstructing a paper's reasoning may mean
> faithfully reproducing the assumptions it left silent (Section 1's last row). Is
> formalization obligated to *surface* what the paper left tacit — and if so, by whose
> "reasonable reader" bar, the author's audience or the formalizer's? This is the §1 bar
> and the §6 horizon meeting on the literature-import case; resolved in Section 6.

---

## 6. Re-assessment, and why an outsider can catch what insiders miss

### 6 · Pass A — the principle

A theory of *revisable* trust needs an account of what makes anyone go back. Without one,
the framework has a quiet failure mode: members who economize by adopting prior assessments
(Section 5) and never revisiting them produce a commons that **freezes** — everyone
standing on the same settled judgments, no one re-opening them — which is exactly the
shared-priors trap the whole project is meant to escape. So the question "what drives
re-assessment?" is not housekeeping; it is central to whether the framework delivers what it
promises.

The answer is **not a duty to challenge**, and not a central scheduler deciding what gets
re-examined. It is concrete and economic:

> A new **decision** arises whose **stakes** are not met by an **old assessment** that was
> made over a body of evidence which **has since grown.**

That conjunction — *staleness* (time has passed), *new evidence* (relevant work has
appeared since), and *higher stakes* (this decision demands more than the old one did) — is
the recorded condition under which a member declines to adopt a prior assessment and
rebuilds it instead. The same *adopt-a-prior-assessment* mechanism that saves work also
**exposes the trigger**: an adopted assessment carries its own date, depth, and the
evidence it was built on, so a member can see *"this was settled too long ago, over too
little, for what I now need"* and choose to re-open it. Re-assessment is itself an
assessment — it records its own choices and links to the one it supersedes.

> **Debt to Pass B.** This explains why a member *with a decision* revisits *their own* line
> of work. It does **not yet** explain the harder thing the framework actually exists for:
> why an assertion gets re-examined by *someone positioned to see what its original
> assessors could not.* That requires the dimension Section 5 left flat — the decision
> horizon. Held to Pass B.

### 6 · Pass B — the decision horizon, and the siloed reviewer

Section 5 spoke of an assessment being sufficient "for a decision, *or class* of decision,"
and deliberately left flat *how wide* that class is. That width is the **decision horizon**,
and it is the hinge of this section.

Every assessment is built for some class of future uses — some set of readers and the
decisions they face. Picture that class as a region drawn around those readers, as one
circle in a Venn diagram: the **decision horizon** is *how widely, and around whom, the
assessor draws it.* A member assessing for **their own next step** draws a small region —
enough to choose which experiment to run next. A peer reviewer assessing for **the field's
future use** draws a large one — enough that others, with purposes the reviewer cannot fully
anticipate, can rely on the work. *Same act* — assemble, weigh, record termination —
*different horizon.* Note that a wider region is not simply *better*: it is more demanding
and costs more diligence, and the right width is itself decision-relative (Section 5). What
matters is not size alone but **where the circle is drawn** — as the siloed-reviewer case
below makes plain.

And the horizon is not a separate field to fill in; it is **implicit in the "any reasonable
reader" bar** of Section 1. To choose the bar is to choose whose future decisions you hold
in view. A wide horizon and a demanding reasonable-reader bar are the same choice seen from
two sides.

This is what finally locates the failure the framework was built to address. The dangerous
error is not the crude blunder; it is the **quiet** one — a citation taken at face value, a
result from one cell line treated as general, an undisclosed conflict unremarked — made by a
capable member and **missed by reviewers who share the same priors.** Internal review misses
it precisely because the reviewers' reasonable-reader bar is set to their *own* community:
the shared assumption is invisible *from inside*, so no one surfaces it.

Now name that failure in the framework's own terms, and something useful happens. The
siloed expert reviewer is not low-diligence — they may climb to rung 4, reanalyze
everything. Their failure is one of **placement, not size**: they drew a demanding circle,
but *around their own community* — and the very reader who would catch the buried assumption
sits outside it. In Venn terms, the reviewer's circle and the field's circle were supposed
to overlap on that reader, and do not. **High diligence aimed at a wrongly-placed
horizon.** It is the same error as the naive junior's, wearing a senior's clothes — and its
root is identical: an assessment whose unstated assumptions are exactly the ones a
*differently-positioned* reader needs surfaced.

Here is what the framework can and cannot do about it, stated honestly. It **cannot make**
an assessor adopt a wide horizon — that is a judgment, and no mechanism manufactures good
judgment (a limit Section 7 owns directly). It also cannot make the siloed reviewer *name*
their own blind spot — by definition they cannot name what they do not recognize. What it
**can** do is make the **work itself legible**: because the assertions, the depth, the
termination and grounding choices are all recorded, an assessment exposes the *shape of what
was and was not done* — which lines were pursued, where they stopped, what was taken as
given. A reader from a *different* silo, whose own priors make them sensitive to exactly the
edges the insider could not perceive, reads that recorded shape and **recognizes the gap** —
not because the assessment declares its blind spot, but because the absence is visible to
someone positioned to see it. The silo is not self-reported; it is **detected**, by the
differently-blind reader the record now makes such detection possible for. They can then
re-assess against *their own* horizon **without redoing the sound parts of the work.**

This is the precise, and honestly limited, answer to the cross-group problem. The framework
does not **guarantee** that the right outsider shows up at the right moment — auditability
plus a staleness trigger make the encounter *possible*, not *certain*. But it converts the
siloed failure from **invisible** (today: a narrowly-scoped review and a broadly-scoped one
are indistinguishable) to **detectable** (here: the work's recorded shape lets a
differently-positioned reader perceive the narrow horizon, even though the assessor could not
name it). Necessary, not sufficient — and that is the strongest claim the machinery actually
supports.

This also resolves the question left open in Section 5 about **formalizing** a paper's
self-assessment. Faithful formalization reproduces the paper's reasoning — *including the
assumptions it left silent for its own audience.* That is correct as far as it goes, but it
silently **imports the author's horizon.** The resolution: formalization should record the
reasoning at the author's bar *and* flag, as recorded assumptions, the tacit moves a reader
at a **wider** horizon would not grant — not by adjudicating them (that would be independent
assessment, not formalization), but by **marking them as assumptions inherited from the
source, unexamined.** Formalization thus carries the author's silences *forward as visible
placeholders* rather than reproducing them as invisible gaps — which is exactly the
invisible-to-visible conversion this section turns on, applied to import. Whose bar? The
formalizer's, used not to *judge* the assumptions but to *find* the ones worth marking.

> **✓ RESOLVED (was 6.A) — does re-assessment guarantee cross-group encounter?** No, and we
> stop claiming it might. Re-assessment + recorded horizon make the cross-group catch
> *possible* by rendering a narrow assessment auditably narrow; they do not *schedule* the
> encounter. Necessary-not-sufficient, stated as such.

> **✓ RESOLVED 5·B-i — formalization records at the author's bar but marks, as inherited
> unexamined assumptions, the tacit moves a wider horizon would not grant.** It surfaces
> (as placeholders) rather than either silently reproducing or actively adjudicating;
> adjudication would be independent assessment.

> **⊘ DEBATE 6·B-i — detection still leans on a differently-positioned reader actually
> encountering the work.** Making the silo *detectable* helps only when a reader whose priors
> differ in the right way *reads* the recorded shape. The residual gap from old 6.A is not
> closed, only relocated: from "the blind spot is invisible" to "the detectable blind spot
> goes undetected because the reader who could perceive it never encounters this work."
> **Discovery / encounter is therefore its own first-class problem, not a footnote** — and it
> is also where the *generative* cross-silo value lives (below), not only the defensive one.
> Routes into Section 7's reliance on a capable consuming agent.

> **↻ GENERATIVE COUNTERPART (new) — the same legibility that catches errors discovers
> synergies.** Sections 6's argument so far is *defensive*: a differently-positioned reader
> detects a buried error. The identical machinery runs *generatively*: a reader in an
> adjacent silo discovers a dataset, method, assessment — or, higher up, an **integrative
> hypothesis** spanning what several silos produced independently (e.g. a host mechanism
> targeted by multiple viruses, in ways more complex than shared interactors) — that they
> could reuse or build on, and never would have found. This is a strong motivation expressed
> by prospective users (loosely-collaborating labs), though not *the* foundation of the
> framework. It shares 6·B-i's unsolved half: legibility enables the encounter; it does not
> *schedule* it. Develop alongside Section 7 (models as projections) and the
> discovery/encounter problem.

---

## 7. What the commons is: a substrate, not a single graph

### 7 · Pass A — the principle

It is tempting to imagine the goal as building *the* knowledge graph — one integrated,
consistent model of what the field knows, into which every finding is slotted. The
framework **declines to build that**, and the decline is principled, not a deferral.

What the community publishes is **assertions and the assessments over them** — not a single
settled model of the world. A pathway, a network, a hypothesis is a **model derived from
that published substrate for a purpose**: someone selects the relevant assertions, applies
the assessments they trust, and shapes a coherent picture *for a question they have.* The
substrate is the assertions-with-their-assessments; any clean graph is a **projection** of
it, chosen and shaped for a task. Change the purpose and a different projection is the right
one. There is no single privileged graph because there is no single privileged purpose.

This is *why* the framework can hold what would otherwise be a contradiction: that **formal
and freeform content are equally first-class.** Forcing every assertion into one formal
vocabulary would *be* the attempt to build the single graph the framework declines to
build — and, worse, would discard meaning the formal vocabulary cannot carry (the precision
argument, developed in the vocabulary section). Because the commons is a substrate to be
*projected*, not a graph to be *populated*, heterogeneity at the substrate level is not a
defect; it is the precondition for letting each consumer build the projection their purpose
needs.

And that names the consumer the framework leans on. The thing that turns the heterogeneous
substrate into a usable model — selecting assertions, applying assessments, integrating
across forms — is **a consuming agent**, doing the integration for *its* purpose. The
community does not pre-integrate; the consumer integrates on demand.

> **Debt to Pass B.** Two things Pass A glossed: (1) that "the consumer integrates"
> quietly relocates a great deal of capability into the consuming agent — which must be owned,
> not hidden; and (2) that "what the community publishes" presumes a boundary — between what
> an agent *publishes* and what it keeps to *itself* — that the framework has not yet drawn.
> Held to Pass B.

### 7 · Pass B — the publication boundary, and the honesty about the consumer

**The framework governs publication, and only publication.** An agent in this community has
a private interior — its own working memory, its search and triage records, its
intermediate reasoning — and the framework says *nothing* about it. There is no constraint
on how an agent is built or what it thinks. The framework's rules bite at exactly one place:
the **boundary where an artifact crosses from private to published.** What an agent keeps to
itself is unconstrained; what it publishes must conform.

The analogy is the **lab notebook.** A wet-lab scientist keeps a detailed notebook but
shares it sparingly — they do not leave it open to the community. That reticence does real
work: it avoids burdening others with intellectual clutter, and — just as important — it lets
the scientist be *candid* in what they record, precisely because the record is private.
Agents face the same boundary choice. A literature-search agent (we have prototyped a
data-scout role) may keep its search-and-triage history to itself, using it only to avoid
redundant work. What it *publishes* is the trust-bearing residue: the detailed analyses and
imports of papers and their datasets. It *may also* publish non-trust-bearing artifacts —
summary reports or recommendations about what it found — useful to the community but, as the
preamble warned, never admissible as evidence.

Two consequences worth stating plainly:

- **Implementation is free; publication is constrained.** The agents we have built happen to
  use the same platform for private self-knowledge as for published artifacts, which is a
  convenience, not a requirement. Nothing in the framework constrains an agent's internals —
  only what crosses the boundary into the commons.
- **The boundary is itself a judgment the agent makes.** *What deserves publication* — what
  crosses from notebook to commons — is a choice, with the same candor-versus-clutter
  tradeoff the scientist faces. Publishing too little hides reusable work; publishing too
  much clutters the commons and may chill candid private recording.

**Now the honesty Pass A owed about the consumer.** Three of this framework's central moves
hand real work to the consuming agent: combining Section 4's dissolved properties into a
judgment; performing Section 5's non-procedural weighing; and integrating Section 7's
heterogeneous, formal-and-freeform substrate into a usable model. All three presume a
**capable, honest consuming agent** — the very capability the project's "trust, not
capability" stance is careful *not* to claim it guarantees. The honest framing is not to
hide this but to locate it exactly: **the framework makes trust *auditable and assessable*;
it does not perform the assessment.** Exercising the assessment is an agent capability —
**instrumented** (the recorded judge-provenance, depth, and termination choices of Section 5
make *what the agent did* inspectable) rather than **assumed away.** The framework's claim is
about what it makes *possible and checkable*, not about guaranteeing the consumer is good at
it.

This is also where the discovery/encounter gap (6·B-i) finally rests. Whether the *right*
consumer — the differently-positioned reader who would detect the silo, or the adjacent-silo
researcher who would find the synergy — actually *encounters* a given assertion is **not
something the trust machinery decides.** It depends on discovery: how agents search,
recommend, and surface work to one another. **Every** artifact is a vehicle for discovery —
all are indexed for search — so trust-bearing findings and non-trust-bearing reports alike
carry work to those who might use it; the non-trust-bearing review or recommendation is a
*distinctive* such vehicle (it exists largely to point), not the only one. The parallel to
current practice is exact: a findings paper is searchable *and* the journal that carries it
is read by its field — both the artifact and the venue do discovery work. The framework
makes the encounter *fruitful when it happens* — the outsider can check or build without
redoing — but making it *happen* is a separate concern from auditable trust, treated below
as an in-scope-but-non-trust matter of the example community.

> **⊘ DEBATE 7·B-i — how hard to lean on the consuming agent's capability.** We have chosen
> to *own* the reliance (instrumented, not assumed) rather than minimize it. Open question
> whether the paper should go further and characterize the *minimum* consumer capability the
> framework presumes — or deliberately leave that unspecified to avoid coupling the
> epistemic claims to a particular class of agent.

> **✓ RESOLVED 7·B-ii — discovery is in the paper, outside the trust machinery.** Unlike
> integrity (absent from the example community), discovery *must* be solved in our example
> community and project — so it earns **brief conceptual treatment in the body**, with
> implemented mechanisms placed in **supplemental methods** alongside agent prompts and other
> practical implementation. *Studies* of discovery mechanisms — like studies of agent
> design — are explicitly other-paper work. **All artifacts are discovery vehicles** (all
> indexed for search); non-trust-bearing reviews/recommendations are a distinctive vehicle
> (they exist largely to point), not the sole one — exactly as findings papers *and* their
> journals both do discovery work in current practice.

---

## 8. The kinds of published artifact

The framework has spoken of "artifacts" throughout without cataloguing them. This section
does — but it leads with the cut that matters most, because everything else depends on it.

### 8.1 The first partition: trust-bearing or not

The coarsest division of published artifacts is whether they are **trust-bearing** at all.

A **trust-bearing artifact** carries assertions that can enter the support for a claim — it
can be a part of the evidence another member assesses. Source material, datasets, recorded
analyses, hypotheses, assessments: these are the artifacts the whole of Sections 1–7 was
about.

A **non-trust-bearing artifact** carries no assertion admissible as evidence. Communications,
summary reports, recommendations: these are real, published, useful — and they **may refer
to** trust-bearing artifacts — but they can **never themselves be part of the support for a
claim.** The asymmetry is the clean signature of the class: **support flows *into* a
non-trust-bearing artifact, never *out of* it into evidence.** A recommendation may cite into
datasets, sources, and assessments to support itself; **nothing may cite the
recommendation** as a premise. A recommendation that "dataset D is worth using" is not
evidence that D is good; it is a pointer, and treating it as evidence is a category error —
the artifact-level form of the rationale-versus-evidence distinction of Section 5. The rule
is sharp: **a non-trust-bearing artifact is never a node another assessment grounds on —
in-references permitted, evidence out-references forbidden.**

The distinction is not a demotion. Non-trust-bearing artifacts do indispensable work —
notably **discovery** (Section 7): a review or recommendation exists largely to *point*, and
pointing is how members find work to use. They also **qualify** trust-bearing results
without becoming part of them. Consider an **expert agent** consulted by another agent (a
role in the demonstration community). Asked a loosely-specified question — "given the
methods and datasets you are expert in, what processes are regulated in this drug-treatment
differential-expression dataset?" — the expert may emit a *bundle that straddles the
partition*: an **analysis** and its **data** (trust-bearing ground), an **assessment** over a
set of assertions (trust-bearing judgment), *and* a **recommendation** that qualifies the
result — "be careful using this: only 5 of the top 50 genes drove the overlaps with known GO
biological-process terms, leaving 45 unaccounted for, and those 5 encode hub proteins
involved in many processes." That qualifier is decision-support *about how to use* the
assessment, not evidence *within* it: discoverable, citable-into, never citable-as-evidence.
The partition keeps two jobs from being confused — *carrying evidence* and *carrying
attention or caution.* An artifact may do the latter without being admissible for the former.

> **Why surface this so prominently.** A reader primed by Sections 1–7 could reasonably
> assume the trust machinery covers *everything* the community publishes. It does not, by
> design. Naming the non-trust-bearing class protects the evidence layer from contamination
> (no laundering a recommendation into evidence) and gives discovery artifacts an honest
> home.

### 8.2 The trust-bearing types

Within the trust-bearing class, the types fall out of the principles already established —
they are *derived*, not catalogued by convention:

- **Source material** — external text or records a claim can be grounded against. Its role is
  to be *pointed at* by a text pointer (Section 3): the terminating, faithfulness-checkable
  ground on the document side.
- **Data** — measurement or derived data a claim can be grounded against by a data pointer
  (Section 3). *Data* is the category; **a dataset of tabular values is one shape of it, a
  gel image (or a set of gel images) another.** The finer taxonomy of data categories is
  deliberately **left open**, to be created and refined as the system accrues mileage rather
  than fixed now (the same restraint as Rule 3: name the category, do not prematurely fix its
  sub-structure). Whether data was *produced here* or *imported* is **provenance, not type**
  (see 8.3): imported and freshly derived data are the same kind of thing, differently
  sourced — and we import *derived* data too, since some sources supply only that.
- **Analysis** — a **recorded procedure that emits derived data, and nothing more.** The
  moment a *claim* is drawn from the data, that is an assessment, not part of the analysis.
  Holding analysis to "procedure + emitted data, interpretation excluded" is what lets the
  reusable computation stand apart from any particular use made of its output.
- **Hypothesis** — a **structured model of competing explanations** (a claim, its null, its
  alternates, with rationale); a *prediction* is a hypothesis of this kind. It is a *model* —
  a **proposal**, not a single assertion — and, standing alone, **it is not trust-bearing.**
  A hypothesis is a candidate to be assessed, not evidence. It becomes trust-bearing only
  when an **assessment** addresses its claims; an assessment **may subsume a hypothesis**,
  drawing its claims inside, where the assessment's grounding makes them trust-bearing.
  Assessing a hypothesis is **adjudication among its alternates**, not a single trust verdict
  on one statement — which is why it is its own type and stands separate from the assessments
  made on it. (This is also what dissolves the worry in 8·A: an implicit prediction inside a
  recommendation is a *hypothesis*, hence not evidence until separately assessed — never a
  reason to promote the recommendation itself.)
- **Assessment** — the central act and artifact of Section 5: a bundle of grounding and
  termination choices over a set of assertions, reaching a purpose-relative judgment. It is
  both a consumer of support and, once published, new support others can build on. A
  scientific paper corresponds most nearly to an assessment (a *self*-assessment, Section 5)
  — and often bundles a dataset besides.

### 8.3 Two cross-cutting properties — not types

Two things that look like they might be types are in fact **properties every trust-bearing
artifact carries**, orthogonal to the catalog above:

- **Provenance** — whether the artifact was **imported** from an external source or
  **authored** within the commons. This cuts across all types (an imported dataset, an
  imported analysis, an assessment built on imported source material) and is recorded as a
  property, not used to mint parallel types. Some papers supply only *derived* data, the raw
  being unavailable or impractical — so we import derived data too; "imported vs. derived" is
  provenance, never a type boundary.
- **Leaf-grounding flavor** — for the artifacts that serve as terminating ground, *which
  faithful pointer* applies: a **text pointer** into source material, or a **data pointer**
  into data (Section 3). Two flavors of one grounding mechanism, recorded as a property of the
  ground.

### 8.4 What earns its own artifact: the reuse-driven separation spectrum

A recurring choice runs through this catalog: **how finely to carve the work into separate
artifacts.** It is not free-for-all, and it is not fully determined — it is governed by one
principle: **separate into its own artifact whatever downstream members will depend on
independently.** Reuse drives reification.

The principle has two clearly-decided ends and a band of judgment between them.

- **The high end — separation is *required*; conflation is an *error*.** The canonical case
  is the high-throughput paper that both **produces a dataset** and **uses it to validate a
  few hypotheses** (offered as evidence of the dataset's value). The dataset, together with
  the assessment of *how it was produced*, is reusable by nearly everyone downstream; the
  authors' specific validated hypotheses are reusable by few. Bundling them forces the common
  consumer — who wants only the dataset — to drag along the rare one. So the dataset (plus its
  production-methods assessment) **must** be a separate artifact from the authors'
  self-assessment that uses it. Here, conflation is not a stylistic lapse; it is an error,
  because it defeats the dominant downstream reuse.
- **The low end — separation is *optional*; over-reifying is a *poor choice*, not an error.**
  Recall the member who runs a quick distribution analysis to justify choosing a Wilcoxon
  test (Section 5). That sub-analysis sits at the altitude of a faithfulness-checkable
  datum — like "gene A is the fifth-most-significant DEG." Reifying it as its own published
  artifact is **a poor choice** (clutter, for something almost no one will reuse) but **not an
  error** (it remains checkable and correctly placed). The judgment is better-or-worse, not
  right-or-wrong.
- **The band between** is genuine judgment, made well or poorly, and — like every other
  choice in the framework — **recorded and therefore questionable.** Under-reification hides
  reusable work (the production no one can now reuse); over-reification clutters the commons.
  A member chooses, and a later member can contest the choice.

This spectrum is the same axis as the publication boundary of Section 7 (what crosses into
the commons), one level down: *given* that something is published, **how much of it earns
standing as an independently reusable unit.** Both are answered by the same question — *what
will a downstream member need to depend on by itself?*

> **✓ RESOLVED 8·A — recommendation is definitely non-trust-bearing; the prediction worry
> dissolves through hypothesis.** A recommendation may cite *into* evidence but is never
> citable *as* evidence (in-references permitted, evidence out-references forbidden). Its
> implicit "worth using" prediction is a **hypothesis**, and a stand-alone hypothesis is not
> trust-bearing until separately *assessed* — so nothing promotes the recommendation itself.
> Whether to emit an analysis, an assessment, a recommendation, or a bundle is an **agent's
> choice given current needs** (the expert-agent case). No finer non-trust-bearing taxonomy
> forced now.

> **✓ RESOLVED 8·B — the trust-bearing ground type is *data*, with an open sub-taxonomy.**
> Q2 stands: text-pointer ground (source material) and data-pointer ground are distinct,
> human-intuitive, practical. The non-text/non-dataset case (gel image, specimen record) is
> **still *data*** — it just is not a *dataset* of tabular values. Resolution: **`data` is the
> category; `dataset`, `gel image`, etc. are characterizations of data**, and the taxonomy of
> data characterizations is left open to refine with system mileage (Rule-3-style restraint).

---

## 9. Conformance and precision: what the community requires, and what it merely values

This section introduces, for the first time, the **content register** — *object,
relationship, property* — for the internal structure of what an assertion is about. It is
held until now on purpose: the trust layer (assertions, assessments, evidence) had to be
established first, because conformance is defined *in terms of* that layer, not the content
beneath it.

### 9.1 Two tiers, and only one is mechanical

The community cannot demand that every published artifact be *good*; it can demand that
every artifact be *usable by the machinery.* These are different requirements, and conformance
splits along the line between them.

**Tier 1 — the addressability floor (procedural, checked before publication).** For the
trust machinery to work at all, members must be able to **find and reference into** each
other's artifacts: an assertion must have a stable identity, references must resolve, the
structural slots that carry recorded assumptions and termination choices must be present and
well-formed. Call the property these requirements secure **addressability** — *the capacity
for a later assertion's support to land on this one.* Tier 1 is the minimal vocabulary that
secures addressability, and it is **mechanically checkable**: an artifact either has resolvable
identity and well-formed structure or it does not. This tier can be enforced at the moment of
publication, near-automatically, the way a journal's submission system rejects a manuscript
missing required fields.

**Tier 2 — good practice (rubric-guided, ultimately a matter of judgment).** Above the floor
lies everything that makes an assertion *good*: precise, well-chosen, appropriately grounded,
declared to the right depth for its audience. This **cannot** be reduced to a procedure,
because where the bar sits is decision- and horizon-relative (Sections 5–6) and because no
fixed rule anticipates every case. Tier 2 can be **guided by a rubric** and checked against
it, but the final call rests with assessors exercising judgment — and members will meet it
with varying skill.

The governance consequence is worth stating, because it is the social institution the whole
framework has been implying. Tier 2 is not enforced by an absolutist policy or a validator;
it is enforced the way scholarly communities already enforce good practice — **by editors and
peer review**, applying a shared rubric *with judgment*, and rejecting work that falls below
community expectations promptly rather than by rule. The framework supplies the structure and
the rubric; it does not replace the editorial judgment with a checker. **Mechanism for the
addressability floor; institution for everything above it.**

### 9.2 Precision and addressability are different axes

A natural temptation is to equate "precise" with "machine-structured" — to assume that
putting an assertion into a controlled vocabulary makes it both addressable *and* precise.
The two come apart, and seeing how is what makes the conformance line defensible.

- **Addressability** is whether a later assertion's support can *land on* this one — whether
  it can be referenced. It is what Tier 1 secures.
- **Precision** is how much of the author's intended meaning *survives* the way it was
  expressed — how little is silently lost.

These are independent. The clearest case is a free-text assertion about "AKT" when the work
was in fact done only on human AKT1. The token "AKT" is perfectly **addressable** — a later
assertion can reference it — yet it is **imprecise**: a reader cannot recover whether the
author meant the gene, the family, or the specific isoform, and *the author may not have been
able to say either.* Addressability is high; precision is low. The two axes are orthogonal.

This matters because a member assessing such a paper has a **trust concern** rooted exactly in
the precision gap — and the concern is **weighted by how critical the imprecise term is to the
argument.** "AKT" in a passing remark costs little; "AKT" where the entire argument turns on
which isoform acts is a real trust hit, because the imprecision may hide that the author never
established the thing the argument needs. Imprecision is not a conformance failure (the
assertion is addressable, hence Tier-1 conformant); it is an **assessment finding**, surfaced
by a reader exercising Tier-2 judgment.

### 9.3 The enemy is information loss — and a coarse vocabulary is a common cause of it

Here the content register earns its keep. A controlled vocabulary represents an assertion's
internal **objects, relationships, and properties** in a fixed scheme. The usual assumption
is that doing so is *strictly better* than free text — more rigorous, more computable. That
assumption is false, and correcting it sets the framework's stance on formal representation.

The thing that actually matters is **how much of the author's intent survives encoding.** Rank
representations by that, and the ordering cuts *across* the formal/free-text line rather than
along it:

> **a precise formal vocabulary  >  precise free text  >  a coarse formal vocabulary**

A precise formal representation — BEL (the Biological Expression Language) is the strong
example, designed to capture molecular relationships with nuance: distinguishing direct from
indirect causality, transcriptional from degradation-mediated from protein-level effects —
sits at the top: it carries the meaning *and* makes the objects and relationships addressable
and computable. But a **coarse** formal vocabulary sits at the *bottom*, **below precise free
text.** A scheme whose causal relationship is just "activates / inhibits" — conflating direct
and indirect causality, transcriptional regulation, degradation, and protein-protein effects
into one undifferentiated arrow — **throws knowledge away.** If such a scheme is used to encode
an author's intent, it is *worse* than recording the free-text sentence the author would have
written, because the sentence at least preserved the distinction the vocabulary destroyed. A
coarse controlled vocabulary launders imprecision as structure: it *looks* rigorous while
having discarded exactly what a careful reader needs.

So the framework's operating rule for representation — borne out in our prototype experiments,
where agents were instructed precisely this way — is:

> **Use a controlled vocabulary where it genuinely carries the meaning; depart from it to
> precise free text wherever it cannot.**

A common case where vocabularies fail is **context**: an attempt to force rich biological
context (the conditions under which a relationship holds) into a rigid contextual scheme tends
to be awkward and lossy, and a **context-rich free-text object** preserves more than a
forced encoding would. Choosing where to use the vocabulary and where to depart is itself a
**recorded, challengeable choice** — the same machinery as every other grounding and
declaration choice in the framework.

This is why Section 7's "formal and freeform are equally first-class" is not relativism. It is
the recognition that **fidelity to meaning, not formality, is the standard** — and that
formality serves the standard only when it is precise enough to carry the intent. Where it is
not, free text is the more faithful choice, and the framework treats it as fully legitimate.

> **Note — this is the precision argument Section 4 deferred.** Section 4 said the weakness of
> a support relationship is often a *representation* choice and held the detail here. The
> coarse-vocabulary case is exactly that: an assertion can be weakened not by its evidence but
> by an encoding that discarded the meaning the evidence supported.

> **⊘ DEBATE 9·A — addressability of free-text internal elements.** Tier 1 secures that an
> *assertion* is addressable (referenceable as a whole). It does **not** secure that the
> *objects inside* a free-text assertion (the "AKT" token) are individually addressable —
> that is the optional upgrade a controlled vocabulary buys. Open question whether the
> conformance floor should ever require *element-level* addressability for certain critical
> assertion classes, or leave it always optional (Tier 2). Leaning: always optional —
> mandating it would re-impose the single-vocabulary regime the framework rejects — but the
> "critical term" case of 9.2 is where pressure to require it would come from.
