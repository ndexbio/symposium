# Core Architecture — Symposium's Epistemological Foundation

> **Status: working draft for co-editing.** This document is being built and
> revised collaboratively. It is meant to be argued with, not deferred to. Open
> questions and points needing debate are marked **⊘ DEBATE**. Claims inherited
> from existing docs that may need revision are marked **↻ REVISIT**. Nothing here
> is settled until we agree it is.
>
> **Purpose.** The existing [00-trust-thesis](requirements/00-trust-thesis.md)
> states *what Symposium is and is not* — scope discipline, what it does not claim.
> This document states the layer underneath: **the epistemological theory** — what
> makes an assertion trustworthy in this commons, and how trust is constructed,
> carried, composed, and revised. The thesis answers "what are we building and why";
> this answers "what is our theory of knowledge, and how does the architecture
> enact it." Where the two conflict, we reconcile here and propagate.

---

## 0. What this document must do

A defensible epistemological foundation for agentic science has to answer, in order:

1. **What is the object of trust?** (What thing do we trust or distrust?)
2. **What does it mean to trust one?** (Trust is not binary; what is it?)
3. **Where does trust originate?** (The grounding — what stops the regress?)
4. **How does trust compose?** (How does trust in parts yield trust in wholes?)
5. **How is trust revised?** (Knowledge changes; trust must too.)
6. **Why should anyone outside the producing group believe any of it?** (The
   cross-group warrant — the actual point.)

The sections below take these in turn. Each ends with the open questions that
section has not yet closed.

## 0.1 Dexter's initial re-frame:

A key aspect of our argument is that scientific *community* rules are the machinery of trust, enabling members to assess their trust in assertions.

The assertion is, indeed, the object of trust.

Artifacts are published by community members. Artifacts contain assertions. 

The author of the artifact is implictly asserting that the assertions it contains are true, true in the context of the artifact. 

This implies that all artifacts are judgements.

Some assertions, however, may be explicitly stated with qualifications.

We will distinguish types of assertion:

- Assertion of measurable fact. 
  - The fact might be wrong, but there is only trivial interpretation:
  - "the span x in document y contains this string"
  - "decreased rna expression of gene Y between control to treated was measured by X after <further experiment and data analysis description>"

- Assertion of claim.
  - Protein A phosphorylates Protein B. (with current technolgy, this cannot actually be observed directly. Some experimental outcomes are very close to direct observation of phosphorylation but still require assumptions and interpretation)

- Assertion of trust assessment
  - measurement X supports claim 1; claim 1 supports claim 2.
  - with optional justifications

Artifacts can also contain arguments, the logic underlying an explicit or implicit judgement. 

There is, of course, the trap of endless recursion of assertions about assertions. This is tricky to avoid because long-running debates can legitimately have many layers of recursion.

my resolution to this is that agents can record a decision - a judgement - such as:

- I choose to assume this assertion is true/false and proceed
- I choose to abandon this line of investigation despite being unable to find a resolution in order to spend effort elsewhere.

The choice to assume a claim is critical for practical operation. Basic consensus knowledge, such as "AKT1 is a kinase", is not profitable to challenge. Challenging whether it acts in that way in a given context is a different proposition.

These representational choices distinguish a community model of trust from an attempt to build a single knowledge graph. A knowledge graph - such as a pathway - may be derived from the community knowledge. It is a model created for a given purpose, not the body of knowledge published by the community. A hypothesis, or a sub-claim within a hypothesis, is also a kind of model. Depending on validation, it may be built on by other hypotheses.

Our point is to provide auditable chains of trust for an assertion, auditable because the logic is grounded in a DAG running through a set artifacts that can be inspected.

A note on credentialling. It is a reasonable strategy to budget the evaluation of the chain of trust by deciding to end exploring a branch  of the DAG because you decide the source is trustworthy on a given issue and you will assume a truth value for an assertion. But you explicitly record that decision.

---

> **Editorial note (2026-06).** §§1–7 below are the restructured spine, derived from
> the 0.1 re-frame and the design conversation it drove. They replace an earlier
> draft whose §1–§9 are superseded; the still-live open questions from that draft are
> carried forward, with resolutions noted, in the open-question index (Appendix B).

## 1. The object of trust: the assertion, and publishing as judgment

**The assertion is the atom of trust** — a single trust-bearing statement a community
member publishes — *not* the artifact, the agent, or the model. Artifacts are the unit
of *publication and addressing* (the DOI analogue); agents are the unit of
*credentialing*; but the thing that is well-supported-or-not is the assertion. Trust is
therefore **claim-grained**: trust-bearing structure lives wherever it appears, inside
an artifact or across artifacts, and the conformance boundary (trust-bearing vs. domain
content) is *orthogonal to the artifact boundary*. The justification is **no
error-laundering**: if trust attached to whole artifacts, one well-evidenced artifact
could carry an unsupported claim under the same banner of credibility.

**Publishing is itself a judgment.** A member who publishes an artifact *implicitly
asserts that its contents hold, in the context of the artifact*. In this sense **all
artifacts are judgments** — there is no such thing as a neutral deposit of content. This
is constitutive, not incidental: it is why judge-provenance (§5) is not an add-on but
the recorded form of an act that always occurs.

### 1.1 Two factors in the trust of any assertion

Trust in an assertion factors into two *independent* things. Keeping them apart is the
first discipline of the theory.

- **Integrity** — *did the source report honestly and without error?* This is a property
  of the **source**, granted or withheld, and it gates everything beneath it: withhold
  integrity and no downstream evidence is safe, regardless of how good the science looks.
  Integrity is the reputation axis. **It is named here and deliberately scoped out of
  this study (§2).**
- **Interpretive distance** — *given integrity, how far does the asserted conclusion
  travel from what was actually measured?* This is a graded property of an **assertion's
  support**, and it is the axis this architecture instruments (§3, §4).

The two compose as **gate-then-gradient**: integrity is granted first (about the
source); interpretive distance then grades the climb from measurement to claim (about
the support).

### 1.2 Assertions live on an interpretive-distance spectrum

Assertions are not sorted into clean "fact" and "claim" buckets by whether the thing is
*directly observable* — *everything reported about the world is an interpretation of
measurements.* The real axis is **interpretive distance**: how many layers of inference
and scientific belief sit between the measurement and the asserted conclusion. Two poles
of one spectrum:

- **Procedural / behavioral reports** (near-zero distance) — "the researchers performed
  procedure E; the instrument recorded value V." This is still interpretation, but the
  gap between *what happened* and *what is reported* is small, and the only assumption
  needed to trust it is **integrity** (they did not misreport, fabricate, or err). Grant
  integrity, and the reported measurement is trustworthy. Note the sub-split:
  *"the paper says they did E"* is span-faithfulness (fully checkable against the text);
  *"they really did E"* is an integrity assumption (granted, not checkable from the
  artifact).
- **Scientific claims** (large distance) — "A phosphorylates B." Even within the
  experiment's scope, this is *not what was observed*: what was observed was a band, a
  mass shift, a signal. Reaching the claim requires interpreting the measurement *plus*
  a body of belief about what the technique licenses. The interpretive distance is of a
  different *order* than for the procedural report — not categorically separate, but far
  enough along the spectrum to be treated differently.

Interpretive distance is **orthogonal to scope.** A claim can be tightly scoped *and*
interpretively distant ("A phosphorylates B *in this lysate under these conditions*" is
still an inference from a band). Scope bounds *where* a claim applies; interpretive
distance measures *how far the inference reached.*

> **⊘ DEBATE 1.A — "trivial interpretation" must not survive into the final text.**
> The 0.1 draft calls the procedural layer "trivial interpretation." The whole grounding
> story (§3) rests on spans certifying *faithfulness, not interpretation* — and even
> fact extraction (which dataset? which tissue?) is interpretation-laden (the
> assembly-with-inference machinery exists for exactly this). Replace "trivial
> interpretation" with **"faithfulness-checkable, integrity-gated."**

---

## 2. Integrity — named, then scoped out with warrant

Integrity is whether a source reported honestly and without error. It is the axis on
which **reputation** does its work: a member's belief about another source's integrity
is informed by that source's track record. Evidence DAGs (§3) are always *conditioned
on* the assessor's belief in the integrity of the artifacts they draw from.

**This study excludes integrity from the trust model it builds — and the exclusion is
warranted.** Integrity is sufficiently *orthogonal* to the flow of trust from
measurement → assessment that excluding it does not distort the flow we are studying.
We can develop, and demonstrate, the machinery by which interpretive distance, support
structure, and assessment compose into auditable trust *while holding integrity fixed
as granted*. Reputation, credential-weighted integrity belief, and adversarial /
bad-faith sources are real and important, and they are **a different study.**

> **↻ REVISIT 2.A — the exclusion must be stated as loudly as the thesis withdraws the
> self-driving-car analogy.** Name it, justify the orthogonality, and say plainly that a
> *dishonest* source defeats the architecture and is out of scope — so no reader mistakes
> "auditable" for "honesty-guaranteed." (This is the resolution of old DEBATE 5.3 /
> critique C5: the architecture is, for this paper, *cooperative by assumption*, and we
> say so.)

> **⊘ DEBATE 2.B — dual grounding floors.** The evidence DAG bottoms out in two kinds of
> leaf: (a) span-anchored external facts (§3), and (b) **credentialed-source
> assumptions** — "I accept source X's integrity on this issue and terminate the branch"
> (0.1's credentialing note, §5.2). Floor (b) is *integrity-based*, i.e. the very axis we
> scoped out. So integrity cannot be *fully* excluded — it re-enters as a legitimate,
> recorded branch-terminator. The honest position: integrity is excluded *as a modeled
> trust quantity*, but its *use as a recorded assumption* is in scope. Confirm this is
> the line we want.

---

## 3. Grounding: the evidence DAG

Trust does not regress forever and it does not rest on a single chain. It rests on a
**directed acyclic graph of evidence** running through inspectable artifacts:

> **Trust bottoms out in span-anchored external facts at the leaves, composes
> by-reference internally, and is auditable because the whole DAG can be inspected.**

**DAG, not chain.** An assertion is supported by *multiple* lines of evidence; lines of
evidence are *shared* across assertions; assessments built later add new support edges
to assertions made earlier. The structure is a graph, and the auditability claim is
precisely that the graph is grounded and inspectable.

**The leaf — the verbatim span.** The terminating ground for an external fact is the
**verbatim span**: exact source text, copied, never paraphrased or fabricated into false
contiguity. A span certifies **faithfulness** (the quoted text really is in the source),
**not interpretation** (that it was read correctly). This is the architecture's pivotal
move: the ground is not "the agent was right," it is "the agent showed you exactly what
it relied on, so you can check." The span *enables* dispute rather than foreclosing it.
(The anchor is a *set* of spans supported jointly; joining spans is itself a graded
inference — *assembly* when forced by the text, *assembly-with-inference* when the agent
supplies a connective fact or chooses among associations — and the latter is a judgment
carrying judge-provenance. This is where the leaf layer and the judgment layer meet.)

**The interior — composition by reference.** Assertions that build on *other* assertions
reference them **by reference** at assertion/artifact granularity, not by span. The
asymmetry is deliberate: span-MUST for the **boundary with reality**; by-reference for
the **interior of the commons** — enforcing span-level internal cross-references would
breed a machine-precise but human-inaccessible tangle, defeating the legibility the
standard exists to provide.

> **⊘ DEBATE 3.A — provisional identity is a soft floor under the interior.** By-reference
> composition rests on artifact identifiers, but the reference implementation's NDEx
> UUIDs are *resolvable but not portable* (copying re-mints them, breaking references).
> The non-leaf half of the grounding story rests on identifiers the spec itself calls
> provisional. Known gap; no portable-ID design yet.

---

## 4. The support edge — and the dissolution of `evidence_tier`

Trust composes along **support edges**: "measurement X supports claim 1; claim 1 supports
claim 2." How much a support edge *should move belief* is **not one quantity.** The
legacy `evidence_tier` vocabulary (`established` · `supported` · `inferred` · `tentative`
· `contested`) collapses at least four distinct things into five words. **We dissolve it**
and name the factors explicitly.

**Three factors are properties of a support edge** (and an assertion may carry *several*
support edges, each with different values — including edges added later, in other
members' integrative artifacts):

- **Interpretive distance** — how far the inference travels from the measurement to the
  claim (§1.2).
- **Reliability** — sensitivity, accuracy, artifact-proneness of the *test itself*. A
  test can be interpretively *close* yet unreliable (a direct readout from a flaky
  instrument), or interpretively *distant* yet rock-solid. Genuinely orthogonal to
  interpretive distance.
- **Probativeness** — how much a *result* (the pass/fail of a falsification attempt)
  actually bears on the claim, *discounted by whether the test's enabling assumptions
  hold in this case.* A test "worth doing" whose interpretation rests on assumptions we
  cannot defensibly assess here contributes only minorly, regardless of its distance or
  reliability.

**One factor is a property of the assessment's DAG as a whole, not of any edge:**

- **Contestation** — whether, across the assembled DAG, some lines of reasoning tend to
  *falsify* the assertion while others survive falsification. `contested` was mis-filed
  in `evidence_tier` as an edge label; it is in fact a **shape of the graph** in a given
  assessment.

Because these factors are edge- and assessment-relative, **an assertion has no single
stored "strength."** Its evidential standing is **recomputed per assessment**, over
whatever sub-DAG that assessor assembled. The assertion is fixed; its support is
assessment-relative.

> **↻ REVISIT 4.A — replacement vocabulary deferred, not designed.** We have *dissolved*
> `evidence_tier` into (interpretive distance, reliability, probativeness, contestation).
> We have **not** designed the replacement representation (scales, whether each is
> recorded per edge, how contestation is surfaced). Inventing it now would be premature;
> flagged as the next concrete modeling task.

> **Note — this resolves old DEBATE 2.1 / 5.2.** "How do the trust axes combine into one
> number?" was the wrong question. They do **not** combine into a context-free scalar;
> they are assembled and weighed, *per assessment, relative to a decision* (§5).

---

## 5. Assessment — the central act

An **assessment** is the act (and the artifact recording it) in which a member decides
how much to trust an assertion. It is where the DAG stops being a static structure and
becomes a *judgment*. An assessment:

1. **assembles a sub-DAG** of evidence for and against the assertion;
2. **records branch-termination / assumption choices** — the recorded decisions that
   bound the regress (§5.1);
3. **applies non-procedural judgment** to weigh the assembled, dissolved factors of §4
   (no formula does this; the author judges);
4. **is decision-relative** — its conclusion is "belief sufficient (or not) *for some
   decision or class of decision*," not an absolute verdict (§5.3).

An assessment is therefore **both a consumer of the DAG and a node in it**: it reads the
evidence graph and, once published, becomes an artifact other assessments can build on or
challenge.

### 5.1 Terminating the regress: recorded assumptions

Assertions-about-assertions can recurse without end (long-running debates legitimately
have many layers). The regress is bounded **economically, not epistemically** — by
*budgeted, recorded decisions*:

- "I choose to **assume** this assertion is true/false and proceed."
- "I choose to **abandon** this line of investigation, unresolved, to spend effort
  elsewhere."
- "I choose to **adopt a prior assessment** — *Bob already decided he trusts this for
  purposes of class X; I accept Bob's assessment and will not repeat the work.*"

The choice to assume is essential for practical operation: basic consensus knowledge
("AKT1 is a kinase") is not profitable to challenge, though challenging *whether it acts
that way in a given context* is a different proposition. **The discipline is that the
termination is recorded** — the assumption is legible and questionable, not silent.

### 5.2 The depth-of-diligence ladder (and why "citing the literature" is just its first rung)

The same assessment machinery handles literature import — the case usually treated as a
special primitive. To assess "paper X asserts A binds B," a member chooses *how deep to
dig*, and **records the choice**:

1. **Span-correctness only** — the text exists in paper X and means A binds B. (One
   support edge; branch terminated immediately by an assumption: integrity granted, only
   faithfulness checked.)
2. **+ methods/assumptions review** — extend the DAG into *how* they reached the claim;
   weigh the interpretive distance of their inference.
3. **+ repeat their data analysis** — pull their data in as a measurement node;
   *shorten* the interpretive distance by re-deriving.
4. **+ trace their cited support** — extend the DAG across artifact boundaries into the
   papers *they* relied on.

Each rung is a recorded branch-termination choice. **A citation is just rung 1 with
integrity granted and the branch terminated at span-correctness.** The DOI-citation world
hides the depth — a citation looks identical whether the citer read the methods or only
the abstract. Symposium makes depth a *recorded, questionable property* of the assessment
artifact. This is the concrete payoff of "the assessment is the unit, and it records its
own termination choices."

### 5.3 Decision-relativity, and the optional decision statement

An assessment is "trustworthy enough" only *relative to a decision and its stakes* —
"given this assembled evidence, is my belief strong enough to spend the money on the next
experiment?" The same assembled evidence yields different sufficiency verdicts under
different stakes.

The **decision statement is an optional annotation**, not a required field. A member *may*
record "I assembled this DAG such that it was sufficient for me to make <specific
decision / class of decision>." But the *depth choices are inherent in the assembled DAG
regardless* — a future agent can read *how deep the assessor went* off the artifact's
structure and decide for itself whether that depth meets *its own* stakes, with whatever
additional due diligence it chooses. The optional decision statement merely *explains why
the author stopped where they did*; the stopping itself is legible without it.

---

## 6. Re-assessment — the engine that drives members back into the DAG

A theory of *revisable* trust needs an account of **what makes anyone revisit a
node** — otherwise a community where everyone budgets-out by adopting prior assessments
simply freezes (and reproduces the shared-priors failure the thesis opens with). The
engine is **not an abstract duty to challenge.** It is concrete and economic:

> A new **decision** arises whose **stakes** are not met by an **old assessment** made
> over an **evidence base that has since grown.** That mismatch drives re-assessment.

The same adopt-a-prior-assessment mechanism (§5.1) that *saves* work also *exposes the
trigger*: "That assessment was made too long ago; many relevant datasets have appeared
since; it is time to re-assess." **Staleness + new evidence + higher decision-stakes** is
the falsifiable, recorded condition under which a member declines to adopt a prior
assessment and rebuilds the sub-DAG. Re-assessment is itself an assessment: it records
its own assumptions, depth, and judge-provenance, and links to the assessment it
supersedes.

> **Note — this resolves old DEBATE 5.1 / critique C7** ("the chain is described but its
> scheduling is absent / what drives anyone to challenge?"). The driver is decision-stakes
> against a stale evidence base — not duty, and not a central scheduler.

> **⊘ DEBATE 6.A — does this fully answer the cross-group catching problem?** The
> re-assessment engine explains why a member *with a decision* revisits work. It does not
> yet guarantee that a *differently-blind-spotted* member *encounters* the assertion at
> the right time (§7's cross-group warrant). Auditability + a staleness trigger may still
> be necessary-but-insufficient for the junior-researcher error to actually get caught by
> someone who *would* catch it.

---

## 7. Why this is not a single knowledge graph

These representational choices distinguish a **community model of trust** from an attempt
to build *the* knowledge graph. The community publishes **assertions and assessments**;
it does not publish a single integrated graph of settled knowledge.

A pathway, a network, a hypothesis — these are **models derived from the community
knowledge for a given purpose**, not the body of knowledge itself. A hypothesis (or a
sub-claim within one) is likewise a model; depending on validation, other hypotheses may
build on it. The community knowledge is the *substrate of assertions with their
assessment DAGs*; any clean graph a consumer wants is a *projection* of that substrate,
selected and shaped for a task.

This is why **formal and freeform content are equally first-class** (detail to be wired
in from [formal-and-freeform](../design-notes/formal-and-freeform.md)): forcing every
assertion into one formal vocabulary would be an attempt to build the single graph the
architecture explicitly declines to build. The consumer — an LLM-based agent — does the
integration, assembling whatever model its purpose requires from the heterogeneous
substrate.

> **⊘ DEBATE 7.A — "the reader does the integration" is load-bearing in three places**
> (combining §4's factors into a verdict, §5's non-procedural weighing, and §7's
> formal/freeform integration). All three lean on a *capable, honest consuming agent* —
> the very capability "trust, not capability" claims not to depend on. The honest framing
> may be: the architecture makes trust *auditable and assessable*; **exercising** that
> assessment is an agent capability, instrumented (§5 judge-provenance) rather than
> assumed away. Decide how forcefully to say this.

---

## 8. The cross-group warrant (to be rewired to the new spine)

*[Carried from the prior draft; needs rewriting against §§1–7.]* The failure mode that
matters is not hallucination but the *quiet* error of a brilliant, inexperienced junior
(citation taken at face value; a HEK293T-only result treated as generic; an undisclosed
conflict missed). Internal review misses it because the reviewer shares the same priors.
Hence trust requires **cross-group encounter under shared standards** — and the machinery
above (claim-grained assertions, the evidence DAG, recorded assumptions, decision-relative
assessment, the staleness-driven re-assessment engine) exists to make that encounter
*possible*: it hands an outsider exactly the handles needed to check work produced under
priors they do not share, *without redoing it.* (See DEBATE 6.A: possible ≠ guaranteed.)

---

## Appendix A — Source map

- [00-trust-thesis](requirements/00-trust-thesis.md) — what Symposium is/isn't (the layer
  above this one).
- [05-evidence-and-provenance](requirements/05-evidence-and-provenance.md) — §3 (spans,
  assembly grades), §4 (the tier vocabulary we dissolve).
- [07-judgment-and-trust-tracking](requirements/07-judgment-and-trust-tracking.md) — §5
  (judge-provenance, re-review).
- [completeness-as-defensible-standard](../design-notes/completeness-as-defensible-standard.md)
  — feeds §5 (recorded negatives ≈ recorded coverage assumptions; to be wired in).
- [inter-artifact-standard](inter-artifact-standard.md) — §3 (by-reference composition),
  §8 (conformance).
- [trust-not-capability](../design-notes/trust-not-capability.md) — §7.A (instrumented
  capability).
- [formal-and-freeform](../design-notes/formal-and-freeform.md) — §7.

## Appendix B — Open-question index

| # | Section | Status | The question |
|---|---|---|---|
| 1.A | Object | OPEN | Replace "trivial interpretation" with "faithfulness-checkable, integrity-gated". |
| 2.A | Integrity | OPEN | State the integrity exclusion (and cooperative-by-assumption stance) as loudly as a thesis withdrawal. |
| 2.B | Integrity | OPEN | Dual grounding floors: integrity excluded *as a modeled quantity* but in scope *as a recorded assumption*? |
| 3.A | Grounding | OPEN (gap) | Provisional NDEx identity is a soft floor under by-reference composition. |
| 4.A | Support edge | OPEN | Design the replacement representation for the dissolved `evidence_tier` factors. |
| 6.A | Re-assessment | OPEN | Re-assessment explains *revisiting*; does it guarantee cross-group *encounter*? |
| 7.A | Knowledge-graph | OPEN | "The reader does the integration" leans on consuming-agent capability — how forcefully to own this? |
| — | Object | **RESOLVED** | *(was 1.1)* Atom = assertion vs. (assertion, judge)? → publishing *is* judgment (§1); a bare assertion's grounding bundle is its support DAG. |
| — | Trust-is | **RESOLVED** | *(was 2.1 / 5.2)* How do trust axes combine into a scalar? → they don't; assembled and weighed per assessment, relative to a decision (§4, §5). |
| — | Composition | **RESOLVED** | *(was 5.1 / C7)* What triggers re-review? → decision-stakes against a stale, grown evidence base (§6). |
| — | Composition | **PARTLY RESOLVED** | *(was 5.3 / C5)* Bad-faith agents. → integrity scoped out with warrant; cooperative-by-assumption stated (§2). Adversarial layer remains future work. |
| — | Grounding | **RESOLVED** | *(was 3.3 / C3)* Fact vs. claim knife. → interpretive-distance spectrum, orthogonal to scope (§1.2). |
