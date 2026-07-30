# Symposium specification, version 5

The Symposium schema intentionally establishes a *minimal* controlled vocabulary, preserving maximum flexibility for users. It is a framework for documenting the scientific dialog within a community in a structured, inspectable form. Its driving motivation is the need for members, human or AI agent, to assess trust in the outputs of diverse AI agents operating as a community over indefinite periods. It is *not* meant to establish a structured world model for representing scientific knowledge and activity. 

This minimal specification reflects the intent that Symposium should be extended and customized by users. Communities have diverse needs and should control what they record and the forms in which they store it. Their needs can be expected to change over time, especially because the rapid advance of AI agent capabilities may radically change what they produce and how they produce it.

This specification does not:

- determine whether scientific claims are *true*.
- determine whether reasoning about a claim is scientifically sound.
- require scientific meaning to be expressed in controlled vocabularies.
- define a model of scientific reputation.
- establish a scoring system for trust.
- define criteria for correct modeling, statistical, experimental, or other methods.
- mandate a storage format, interface, or specification enforcement regime.
- define how Members are admitted to, governed within, or removed from a Community.
- detect when content is deliberately or unintentionally misrepresented or omitted from the record.

## 1. Core Vocabulary

A **Community** is a set of **Entities**, things of type **Entity**. Entities may *contain* **Objects**. Entities and Objects may have **properties**.

Properties *defined* by the specification are those considered important enough to warrant a controlled vocabulary to express a concept. Some defined properties are *required* because they are necessary for the operation of a Community: they must have *some* value. 

Properties are constrained to values of either **numeric**, **string**, **date-time**, or **address** (see below); a reference to an Entity or Object is expressed as an address. A property value may also be a **list** whose elements are each of one of these types. Where this specification declares a property's value to be a list, the list may contain a single element. A required property whose value is a list must hold at least one element, unless the definition of that property states otherwise. Each property defined by this specification declares its value type explicitly where it is defined below — a base type, a list of a base type, an enumeration, or a constrained range. 

No defined property is left to a default type. A property *not* defined by the schema may take any of these value types, or a list of them; Entities may have such properties beyond those the Symposium schema defines. 

Similarly, some Object types are defined by the schema but Entities may have Objects of types not defined by the schema.

Three descriptive properties are defined generically and may appear on any Entity or Object, though none is required by default. They exist to aid consistency and legibility, not because any rule depends on them; a particular type may nonetheless require one.

Generic descriptive properties (optional on any Entity or Object):
 - `title` (string): a short human-readable label.
 - `description` (string): a prose account.
 - `text` (string): a free-text body.

Every Entity and every Object must have a `name` and a `type`. Where a type below defines its own required or defined properties, those are in addition to these universal properties.

Universal properties (every Entity and Object):
 - `name` (string): a label identifying the Entity or Object — unique within the Community for an Entity, and within its containing Entity for an Object. A `name` must not contain the characters `.` or `#`, which are the structural delimiters of an address (below); the generic `title` property carries a label under no such restriction.
 - `type` (string): names the kind of the Entity or Object. 

Objects within an Entity do not nest; an Object cannot contain another Object. Objects may be linked to one another by **relationships**. A **relationship** is directional, from a *source* object to a *target* object. Relationships can also have properties. An Entity is therefore a *property graph*: its Objects correspond to nodes, their properties to attributes, and the relationships among them to edges.

An **address** is a *string* that identifies, and enables access to, a thing within the Community. Every Entity, every Object, and every property value is *addressable*; an address may also identify content at a finer grain within a property value (below). Entities can therefore refer to content within other Entities via addresses. An address is valid only if it resolves within the Community.

Relationships and their properties are the exception: they are not addressable, and no address form identifies an edge or content held on one. A relationship expresses the internal structure of an Entity rather than content the Entity publishes, and content that is to be referenced — or offered as evidence — belongs in an Object, in a property, or within content an addressing method reaches (§4). Scientific data whose own structure is a graph is content of this last kind: it resides within an Artifact and is addressed by that Artifact's declared methods, not by the relationships of the Symposium schema.

An address is a sequence of dot-separated segments naming a path into the Community. Its base forms address an Entity, an Object, or a property:

- `<entity_name>` — an Entity;
- `<entity_name>.<object_name>` — an Object within that Entity;
- `<entity_name>.<property_name>` — a property of the Entity;
- `<entity_name>.<object_name>.<property_name>` — a property of that Object.

Any base form may be followed by a **schema reference** that addresses content at a finer grain within the thing it names, giving the further forms:

- `<entity_name>.<schema_reference>` — content within an Entity;
- `<entity_name>.<object_name>.<schema_reference>` — content within an Object;
- `<entity_name>.<property_name>.<schema_reference>` — content within a property of the Entity;
- `<entity_name>.<object_name>.<property_name>.<schema_reference>` — content within a property of that Object.

A schema reference is written with a leading `#`, followed by the `name` of one of the addressed Artifact's declared **AddressingMethod** Objects (§4), followed by a `.` and a reference that the named method interprets — for example, a cell in content whose addressing method describes a table. Everything after the method name is interpreted by that method and is not parsed as further structural segments. A schema reference resolves only if the Artifact declares an AddressingMethod of that name. Entity and Object names resolve within the Community and within their Entity respectively; so that the segment after an Entity name resolves unambiguously, an Entity's Object names must not collide with its own property names. Property names are subject to the same prohibition on `.` and `#` as Entity and Object names.

While relationships and addresses express similar concepts, they play distinct roles. A relationship connects Objects within a single Entity, forming its internal property graph. An address is a pointer, enabling a reference to an Entity or into an Entity to be stated as a property with an address as its value: one Entity refers to another, or to content within it, by holding that address as a property value. An address always resolves within the Community; content held outside the Community is reached only through an Artifact that represents it and declares its location and access methods (§6), so the address names that Artifact and the Artifact does the reaching. Relationships stay within an Entity; addresses cross between them.

An Entity's `type` makes it either a **Member** — if its `type` is `Member` — or an **Artifact**, whose `type` is one of the Artifact types defined in §2 (or a type the community defines). Objects are typed the same way, by a `type` naming their Object kind — `Assertion`, `Assessment`, `Ground`, `Assumption`, `AddressingMethod`, and the others defined below, or community-defined ones.

A **Member** is an Entity that *participates* in the Community, meaning that it is considered to act with *agency*, such as person, AI agent, laboratory, or organization. 

Required properties:
 - `description` (string)
 - `member_type` (enumerated string): one of `ai_agent`, `human`, `organization`, `other`

Defined properties:
 - `operator` (address): if `member_type` = `ai_agent`, the Entity address of the Member on whose behalf the agent acts. 

An **Artifact** is a data structure that is `published_by` a Member to the Community. It has a required `created` property recording the time at which it was published. A published Artifact is immutable: its content must never be changed; it can only be superseded by a new version published at a later time. The act of publication implies that the Member in some way takes *responsibility* for the Artifact.

An Artifact must also declare the version of this specification under which it was published, in a required `specification_version` property (string). Communities are expected to adopt revised versions of the specification over time, and an Artifact published under one version remains in the record unchanged once later versions are in use. Declaring the version allows a Member examining an older Artifact to recognize the rules under which it was constructed, and to interpret its structure accordingly rather than by the rules currently in force.

Required properties (in addition to the universal `name` and `type`):
 - `created` (date-time): the time at which the Artifact was published.
 - `published_by` (address): the Member that published the Artifact.
 - `specification_version` (string): the version of the Symposium specification under which the Artifact was published.

Because an Artifact cannot be altered, correction takes the form of publishing a new Artifact that stands in place of an earlier one. An Artifact records this by naming the Artifacts it replaces in a `supersedes` property (list of addresses). The list admits more than one address so that a single Artifact may consolidate several earlier ones. `supersedes` states replacement only and conveys no evidential support (§4): the superseding Artifact must make its own case, and a Ground addressing content in a superseded Artifact remains valid, since the record of what was published and relied upon at the time is not erased. A withdrawal is expressed the same way, by an Artifact that supersedes an earlier one and retracts rather than restates its content.

What the superseding Artifact does with respect to what it replaces — restate, correct, consolidate, or withdraw — is not typed but stated, in a `supersedes_rationale` (string) required whenever `supersedes` is present. A single rationale covers the whole list rather than one per address, because the cases worth explaining are the ones a per-address type would fragment: an Artifact consolidating several earlier ones, or restating part of the record while withdrawing another part, is best accounted for as one statement of what the new Artifact does with respect to all of them. No rule of this specification depends on the distinction — Grounds addressing superseded content remain valid under every one of them — so the record carries an account a reader can weigh rather than an enumeration a reader would have to interpret.

An Artifact may supersede Artifacts published by other Members. `supersedes` is the publishing Member's claim that her Artifact stands in place of those it names; it is not a judgment of the Community, and it removes nothing. The superseded Artifacts remain published, addressable, and groundable, and a Member who disagrees that they have been superseded may say so in a further Artifact.

Defined properties:
 - `supersedes` (list of addresses): earlier Artifacts that this Artifact replaces. Not evidential (§4).
 - `supersedes_rationale` (string): what this Artifact does with respect to the Artifacts it supersedes. Required whenever `supersedes` is present.

Because Artifacts are immutable they are therefore *temporally ordered*. An Artifact can only refer to content at addresses in *strictly earlier*, previously published Artifacts. This rule governs reference *outside* the referring Artifact. An Artifact may always address content within itself — an Argument's required `primary_assertion` names one of its own Assertions — and such intra-Artifact references carry no temporal condition, the content and the reference to it being created in one act. Artifacts sharing an identical `created` value are not earlier than one another and therefore cannot refer to each other; their relative order is undefined, and this specification defines no means of breaking such a tie because none is needed.

There is one exception, and it is the reason the Bundle exists. An Analysis and the Artifacts it produces are two facets of a single act (§10): they are created in the same instant and must refer to each other, the Analysis naming its `outputs` and each output naming its `produced_by`. Neither can precede the other. A **Bundle** is an Analysis together with its output Artifacts, published in one atomic act; Artifacts within a Bundle may refer to each other's content by address despite sharing an instant, and all must declare the same `specification_version` and an identical `created` value. The two declarations of production must agree: an Artifact X is among an Analysis A's `outputs` if and only if `X.produced_by` names A. Neither declaration alone constitutes the relation, so a Bundle in which an Analysis names an output that does not name it back is not well formed.

A Bundle is not a general facility for co-publication. Only an Analysis and its outputs may be bundled. Two Arguments in particular cannot be, so no Argument can ground on another published in the same instant, and circular evidential support cannot arise. Should communities find other atomic-publication needs, admitting them is a backward-compatible change available to a later version of this specification.

## 2. Artifact Types

This specification defines the Artifact types below but does not forbid the publication of other types; an Artifact names its type in its required `type` property (§1). The defined types play three roles in evidence:

- The **Argument** (§3) is the core type. It presents claims and the author's assessment of them; its Assertions are its only groundable content.
- **Non-groundable types** (§10) guarantee that none of their content is groundable: **Analysis**, **Model**, **Report**, and **Message**.
- Every other Artifact declares which of its content is groundable in its **AddressingMethod** Objects (§4). Two such types are defined by this specification because they are common sources of evidence a Ground may address: **Data** and **ScientificPublication** (§7).

## 3. Argument

Symposium is centered on the concept of evidential reasoning and its core Artifact type is the Argument.

An Argument contains at least one Assertion Object. An Assertion states a `claim` (string): a free-text statement about the world. An Argument must have exactly one *primary* Assertion, addressed by its `primary_assertion` property (address); the Argument's purpose is to present evidence and reasoning that could falsify that Assertion. The intent of a scientific argument is typically to explain observed data with a proposed causal mechanism. Sometimes it may be contrasted with other explanations and this can be embodied in an Argument as additional Assertions, each linked from the primary by a `has_alternative` relationship. `has_alternative` relationships must be acyclic and they convey no evidential support.

An alternative is an Assertion in full. It may carry its own `depends_on` structure, its own Grounds and Assumptions, and it has its own Assessment as any Assertion does; what distinguishes it is position rather than kind, since it is not the claim the Argument is a case for. An Assertion may not be both an alternative and a dependency within the same Argument: a dependency is material the primary rests on, an alternative is a rival the primary must beat, and no Assertion can hold the primary up and compete with it at once.

Every Assertion in an Argument must be reachable from the primary Assertion by `depends_on` and `has_alternative` relationships. An Argument is therefore rooted: it contains no Assertion whose role in the case is undefined, and none outside the reach of the purpose stated on the primary Assessment (below).

The bar on an Assertion being both an alternative and a dependency is read over reachability rather than over direct links alone. No Assertion linked from X by `has_alternative` may be reachable from X by `depends_on`, and X may not be reachable by `depends_on` from any of its alternatives: neither may rest, however indirectly, on the other. Two rivals may nonetheless share a dependency. A sub-claim that both an Assertion and its alternative rest on is a common and coherent structure, since neither competes with what holds them both up, and it is often exactly what makes the two accounts comparable.

An author who comes to judge an alternative the better account does not promote it in place, since Artifacts are immutable and the earlier Argument stands. She publishes a *new* Argument whose primary Assertion is that account, recording the earlier Argument in `reassesses`. A verdict of `supported_for_purpose` on an alternative is therefore not a contradiction: verdicts are independent and relative to purpose, and an alternative may be adequate for some purpose while the Argument makes its case for the primary. Where an alternative genuinely prevails, that is the occasion to author the new Argument.

Every Assertion must state the `scope` (string) in which its statement is asserted to hold, such as species, tissue-type, or disease state.

An Assertion may also carry a `derived_from` property (list of addresses) naming content in prior Artifacts from which the Assertion is drawn — an earlier Assertion it restates or operationalizes, or a proposal recorded in a Report that it takes up — so that a claim can be traced to the material it came from. `derived_from` asserts that the Assertion is based in some way on the content it names; it is not a citation relation, and an Assertion arriving at a similar claim by an independent route should not record a lineage it does not have. `derived_from` establishes lineage, not evidential support, and carries none (§4): the material it names may be non-groundable, and even where it is groundable, the Assertion still requires a basis of its own.

An Argument making a complex primary Assertion may be decomposed into a dependency structure of supporting Assertions linked by `depends_on` relationships. `depends_on` relationships must be acyclic. Like all relationships (§1), they stay within a single Argument: an Assertion can never depend on an Assertion in another Argument. The two mechanisms therefore divide the work without overlap — `depends_on` expresses structure *within* an Argument, and a Ground reaches *outside* it for evidence.

Because an Argument's Assertions are groundable, §5 requires an Argument to declare its `authors`. In the ordinary case these name the publishing Member and the property appears redundant. It is not: an imported Argument (§9) carries the attribution of the scientists whose reasoning it presents, while `published_by` records the Member who extracted and published it, and the two must be distinguishable.

Argument (Entity) required properties:
 - `primary_assertion` (address): the address of the Argument's single primary Assertion.
 - `authors` (list of strings): the author or authors of the Argument's reasoning (§5).

Argument (Entity) defined properties:
 - `reassesses` (list of addresses): earlier Arguments that this Argument reassesses, contests, or otherwise responds to. See *Reassessing a claim*, below. `reassesses` is not evidential (§4).

Assertion (Object) required properties:
 - `claim` (string): a free-text statement about the world.
 - `scope` (string): the conditions under which the claim is asserted to hold.

Assertion (Object) defined properties:
 - `derived_from` (list of addresses): content in prior Artifacts from which the Assertion is drawn.

Each Assertion is paired with an **Assessment** object via an `assessed_by` relationship. The pairing is strictly one to one: every Assertion has exactly one Assessment, and every Assessment belongs to exactly one Assertion. The verdict could instead have been carried as properties on the Assertion itself. Keeping it in its own Object holds the claim and the judgment on it apart, so that neither blurs into the other, gives the verdict, its purpose, and its rationale a single addressable home, and follows the practice elsewhere in this specification of making each distinct move its own Object rather than burying some in properties.

An **Assessment** renders a `verdict` (enumerated string, below) on an Assertion for a stated `purpose` (string) and provides the rationale for the verdict via an `evaluation` (string). The verdict of the Assessment is limited to that Argument, created by a specific Member at a specific time. It does not automatically become a belief of the Community any more than a finding presented by the authors of a scientific publication.

The value of `verdict` is constrained to one of `supported_for_purpose`, `insufficient` or `falsified`. This is a central design choice of Symposium: trust in an Assertion is neither a binary nor a score, it is relative to the stated purpose of the author of the Argument, the stakes of decisions to be made based on the Assertion. The same evidence and reasoning presented for an Assertion may be sufficient for a low-stakes decision by a particular author but not for a high-stakes decision by another author.

Each verdict is rendered on the Assertion's `claim` within its stated `scope`, and each is the judgment of the Argument's author rather than a value computed from the basis.

- `supported_for_purpose`: the author judges the basis adequate to rely on the claim for the stated `purpose`. This is not a judgment that the claim is true, and it does not carry to purposes at higher stakes.
- `insufficient`: the basis does not settle the question at the stated stakes. The claim may well be correct; what the record lacks is evidence adequate to rely on it. Typical cases include too few observations, effects too small or too variable to discriminate, a test that could not have distinguished the claim from its alternatives, a negative result whose absence is not inconsistent with the claim, evidence drawn from a scope other than the one asserted, and reliance on Assumptions the author cannot expect the Community to grant at those stakes.
- `falsified`: the basis contains material inconsistent with the claim — most directly, a Ground whose `criterion` was met. The record does not merely fail to support the claim; it weighs against it.

The distinction between `insufficient` and `falsified` is a distinction in the state of the record, not in the fate of the claim. Under both verdicts the claim fails to be supported, and in that sense both report that the Assertion did not survive the case made for it. What separates them is whether the failure is an absence of adequate evidence or the presence of contrary evidence, and the difference bears directly on what a reader should do next: an `insufficient` verdict identifies work that could be undertaken, whereas a `falsified` verdict identifies evidence that would have to be answered.

The three verdicts are not equally sensitive to purpose. Raising the stakes can turn `supported_for_purpose` into `insufficient` on an unchanged basis, because adequacy is defined relative to the decision at hand. Contrary evidence, by contrast, does not become consistent with a claim because the stakes are low, so a `falsified` verdict is more readily carried across purposes by a later reader. It remains an authored judgment nonetheless: an author may hold that a met `criterion` was too weak a test, or too poorly matched in scope, to falsify the claim, and may render `insufficient` while stating that reasoning in the `evaluation`.

Every Assertion in an Argument is paired with an Assessment, subsidiary Assertions and alternatives included. A verdict on a subsidiary Assertion is needed in its own right and not only as an input to the primary verdict: it is what allows a reader to see which part of a decomposed Argument is well made and which part is not, and a decomposition whose parts carried no verdicts would record structure without judgment.

The `purpose` of the Assessment on the primary Assertion is the purpose of the Argument as a whole, and is required. On the Assessment of any other Assertion `purpose` is optional, and where it is absent the purpose stated on the primary Assessment applies. An author states a `purpose` on a subsidiary Assessment only where that verdict is rendered at stakes different from the Argument's own, and should give the reason in the `evaluation`.

Verdicts are not computed or propagated through `depends_on`: a verdict of `falsified` on Assertion A *does not* force that verdict on an Assertion B that depends on A. Instead, the `evaluation` of B's Assessment may reach down through the `depends_on` subtree beneath B and weigh the Grounds found there directly — necessary because a dependent Assertion may carry no Grounds of its own. The Assessments of the descendant Assertions, their sub-verdicts, are available as context that the author may cite in B's `evaluation` as they see fit, but they carry no automatic force. For example, a `falsified` sub-verdict might be judged to weigh little if it rested on a circumstantial test, a marginal effect size, or a different experimental context.

Assessment (Object) required properties:
 - `verdict` (enumerated string): one of `supported_for_purpose`, `insufficient`, or `falsified`.
 - `evaluation` (string): the rationale for the verdict.
 - `purpose` (string): the purpose and stakes for which the verdict is rendered. Required on the Assessment of the Argument's primary Assertion. Optional on any other Assessment, where its absence means that the primary Assessment's purpose applies.

### The basis of an Assertion

Every Assertion must have a basis: at least one **Ground** connected to it by a `grounded_by` relationship, at least one **Assumption** connected to it by an `assumes` relationship, or at least one Assertion it depends on by `depends_on` — or any combination of these. An Assertion may thus rest entirely on the Assertions beneath it with no basis of its own, or rest only on Grounds, or only on Assumptions; but none may stand with no basis at all, so every chain of dependence terminates in Grounds, in Assumptions, or in both. Where a chain terminates only in Assumptions, the Argument states on its face that it offers no addressable evidence for that branch.

A Ground and an Assumption each belong to exactly one Assertion. A Ground's `rationale` explains how the addressed material bears on *that* Assertion, and an Assumption's states what *that* Assertion rests on and why, so a basis Object connected from two Assertions would have to mean two things at once. Where two Assertions rest on the same material, each carries its own Ground: the addresses coincide while the rationales differ, and that difference is the information worth recording.

Like the other relationships in an Argument — `has_alternative`, `depends_on`, and `assessed_by` — `grounded_by` and `assumes` are directed outward from the Assertion, so an Argument is traversed downward from its primary Assertion to its basis.

### Grounds

A **Ground** identifies material the author offers as bearing on an Assertion, by an `address`, together with a `rationale` explaining how it bears. The choice of `grounded_by` rather than "supported_by" is deliberately neutral: it does not state whether the material supports or opposes the Assertion. That judgment belongs in the Assessment's `evaluation`.

A Ground may carry a `criterion`: a statement of what result would have been inconsistent with the Assertion. A Ground carrying a `criterion` asserts that the addressed material was used as a *test* — that it could have counted against the Assertion and did not. A Ground with no `criterion` presents the addressed material as evidential without that claim; it is material the author builds upon rather than material the Assertion survived. The distinction is recorded by the presence or absence of the `criterion`, not by a separate type.

A Ground always reaches *outside* its own Argument. Its `address` may name content that has been declared groundable: content within an Artifact reached by an AddressingMethod that Artifact declares groundable (§4) — a value within a Data Artifact, a passage within a ScientificPublication — or an Assertion within *another* Argument. It may not name content in a non-groundable Artifact (§10), content reached by an AddressingMethod declared addressable only, a Member, or anything within the Argument that contains it. An Assertion's reliance on another Assertion in the same Argument is what `depends_on` is for. Grounding on another Argument's Assertion takes that author's conclusion as evidential testimony, which is appropriate where the author accepts the earlier conclusion and builds upon it. It is not appropriate where the earlier conclusion is what the author disputes; see *Reassessing a claim*, below.

Ground (Object) required properties:
 - `address` (address): the address of the material on which the `rationale` rests.
 - `rationale` (string): a free-text explanation of how the addressed material bears on the Assertion.

Ground (Object) defined properties:
 - `criterion` (string): the criterion of falsification — what result would have been inconsistent with the Assertion. Its presence marks the Ground as a test.

### Assumptions

An **Assumption** records a premise the author adopts without any addressable material to support it. It has no `address`: if the author can point at material bearing on the premise, the premise belongs in a Ground. An Assumption is therefore not evidence and supplies none. It is a declaration of where the record is silent, made so that a reader can see what the verdict rests on beyond what has been published.

An Assumption's `rationale` carries the whole of the author's stance toward the premise, and must state three things: what is being assumed, why no evidence is offered for it, and the standing the author expects the premise to have within the intended Community. Assumptions vary continuously in standing — from background so widely held that stating it is a courtesy, through claims standard in a field but untested in the scope at hand, to premises the author posits as unestablished in order to make an open dependency explicit. This specification does not partition that range into types. A classification coarse enough to be applied consistently would displace the specific account the `rationale` can give, and it is that account a reader requires in order to judge what the Assertion rests on.

No verdict follows automatically from the presence of an Assumption. An Assessment must weigh the Assumptions in an Assertion's basis as it weighs its Grounds, and its `evaluation` should state what the verdict would be were the premise not granted. An Assertion resting only on Assumptions has no addressable evidence at all, and an author who nonetheless renders `supported_for_purpose` on such an Assertion makes a claim about the purpose and its stakes for which the `evaluation` is answerable.

A premise actively contested within the intended Community may be recorded as an Assumption. What the specification requires is that the `rationale` state the premise's standing accurately, not that any particular standing disqualifies it: an author may write that a premise is contested and is adopted here for the purposes of a conjectural Argument. What is not permitted is to record a contested premise as though the Community would grant it.

Assumption (Object) required properties:
 - `rationale` (string): a free-text statement of the premise, of why no evidence is offered for it, and of the standing the premise is expected to have within the intended Community.

An Assumption has no `address` property; if there is a groundable basis, the author should use a Ground.

### Assertion relationships

Assertion relationships (each directed outward from the Assertion):
 - `has_alternative` → Assertion: a rival Assertion; must be acyclic; conveys no evidential support.
 - `depends_on` → Assertion: a supporting Assertion the Assertion rests on; must be acyclic.
 - `assessed_by` → Assessment: the Assertion's Assessment.
 - `grounded_by` → Ground: a Ground for the Assertion.
 - `assumes` → Assumption: an Assumption the Assertion rests on.

### Reassessing a claim

A verdict belongs to its Argument alone, so a Member who judges an existing claim differently does not attach a second Assessment to another Member's Assertion; an Assertion is grounded and assessed only within the Argument that contains it. Instead the Member publishes a *new* Argument.

Where that new Argument contests the earlier verdict, its primary Assertion restates the claim and may record the earlier Assertion in `derived_from`, identifying the claim as the same one. Its Grounds address the evidence the earlier Argument rested on — the values in a Data Artifact, the passages in a ScientificPublication — and not the earlier Assertion itself. To ground on the earlier Assertion is to take that author's conclusion as evidential testimony, and a Member who disputes the conclusion cannot consistently offer it as evidence. The reassessing Member returns to the material and weighs it again, and the new Assessment's `evaluation` renders a verdict for her own `purpose`.

Where the material the earlier Argument rested on cannot be addressed within the Community — held behind a firewall, or never published — the reassessing Member records what she relies on as an Assumption, whose `rationale` states the premise and why no address can be given. No further mechanism is needed for this case.

To record that a new Argument bears on an earlier one without taking its conclusion as evidence, an Argument may carry a `reassesses` property (list of addresses) naming the earlier Arguments. `reassesses` conveys no evidential support (§4); it states a discourse relation only, and is available whether the later Member is extending the earlier work, contesting it, or offering a rival case for the same claim. Keeping claim lineage (`derived_from`), evidential reliance (a Ground), and discourse (`reassesses`) in three separate properties means a reader never has to infer from a single link which of the three an author intended.

Both Arguments then stand in the record. Where the first author judged the claim `supported_for_purpose` for a low-stakes decision, a second may judge it `insufficient` for a higher-stakes one; neither verdict overwrites or propagates to the other, and a reader sees both judgments together with the evidence each rests on.

Contesting is one of several ways a later Argument may take up an earlier claim, and the others differ from it along two independent choices: whether the author accepts the earlier conclusion, and whether the claim is restated from the earlier Assertion or formulated independently. An author who accepts the earlier conclusion grounds on the earlier Assertion and builds upon it, perhaps adding evidence the earlier author did not have or replacing the earlier decomposition with a finer one. An author who does not accept it grounds past the conclusion, on the material beneath. Only a restatement warrants `derived_from`. `reassesses` is orthogonal to both choices.

## 4. Reference vs. Grounds

An address used outside of a Ground is not *evidential*. Such an address may establish identity, provenance, lineage, or discourse — as `primary_assertion`, `derived_from`, and `reassesses` do — but it can never serve as *evidence*. Accordingly, the evidence an Assessment weighs in its `evaluation` is limited to Grounds: those attached to the Assertion and, for a decomposed Assertion, the Grounds reached down its `depends_on` subtree (§3). No content reached by direct address is evidence. A descendant Assertion's sub-verdict, reached through `depends_on` rather than by address, remains citable context that carries no evidential force (§3).

Reaching down a `depends_on` subtree is an operation *within* a single Argument only. Where a Ground addresses an Assertion in another Argument, it reaches that Assertion alone — the author's conclusion, taken as testimony — and not the `depends_on` subtree beneath it. The material beneath the cited Assertion remains inspectable, and an author who wants a particular Ground of the earlier Argument to weigh in her own case addresses that Ground's material directly with a Ground of her own. Evidential weight therefore does not accumulate transitively across the grounding link. Grounding on a claim is taking up its conclusion, as citing a paper takes up its finding rather than silently adopting the whole of its evidence.

An Assumption is likewise not evidence, and for a different reason: it holds no address at all. Assumptions are part of an Assertion's basis and must be weighed by its Assessment, but what they contribute is a declared absence rather than material. The Grounds beneath an Assertion record the material the case is built from; the Assumptions beneath it record what the case requires but does not supply.

Some Artifact types, presented below, are *non-groundable* in that they *guarantee* that *none* of their content is *groundable*. No address in a non-groundable Artifact may be used in a Ground. A non-groundable Artifact may declare addressing methods, and may have good reason to — a section of a Report, an entry in an Analysis's execution log, may be worth referring to precisely — but every method it declares is addressable only, whatever the Artifact itself may state. Designating specific Artifact types as non-groundable is intended to simplify compliance with the specification: a reader can tell from the type alone that nothing within can be offered as evidence, without consulting the Artifact itself.

A Member may judge that a procedure recorded in an Analysis — a normalization, a batch correction, the handling of replicates, a version of a tool — bears on the credibility of the outputs it produced. Nothing prevents that judgment from being stated in an `evaluation`, which is the author's reasoning and may weigh whatever she finds relevant, including material she has inspected but cannot ground on. What such a judgment does not do is enter the evidential case, which remains limited to Grounds. A Member who wants a concern of this kind to carry evidential weight converts it into groundable content — an audit, a re-run, a validation result, published as Data with its own provenance — and grounds on that. Provenance is accordingly an *audit path* rather than an evidence chain: it is what a Member follows in order to know what is worth checking, and what she finds by following it must be published before it can count.

Fine-grained addressing lets a Ground reference values inside arbitrary data or other materials taken as evidence, and the addressing method is specified by the addressed Artifact itself. Any Artifact may declare addressing methods, as **AddressingMethod** Objects, each naming a way in which content within it may be referenced; an Artifact other than an Argument and the non-groundable types must declare at least one.

Addressability and groundability are separate, and an AddressingMethod declares both. Its `description` states how a reference under the method is written and what such a reference reaches: a table addressed by row, column, and cell is the common case, but the content, and hence the method, may be anything, and this specification constrains neither. Its `groundability` states whether the content the method reaches may be used in a Ground. Content that is *addressable only* may be referred to precisely — a passage in a publication may be named, quoted, or discussed — but may not be offered as evidence. The separation lets an author expose fine-grained addresses into material they are unwilling to offer as evidence, and it places the decision with the author of the Artifact rather than with its type.

Only the `name` and the `groundability` of a method are constrained; its `description` is free text. The division follows a general principle of this specification. Whether a particular reference is well formed under a method is a matter of the author's description and, in the end, of a reader's judgment, and prose serves it better than any vocabulary this specification could impose. Whether the content that reference reaches may serve as evidence is not a matter of judgment: a rule depends on it, since a Ground addressing content declared addressable only is invalid, and a rule should not rest on prose. Where an Artifact declares no groundable method at all it carries no groundable content, though a reader must consult its methods to learn this, which is what the non-groundable types spare them.

The AddressingMethod Objects of an Artifact are not themselves groundable. They declare how the Artifact's content is reached and are not among the content reached.

Content reached by a method declared groundable must have provenance. The Artifact must either be `produced_by` an Analysis published with it as a Bundle (§10), or declare an `import_method` recording how the content was brought into the record from outside it (§8). Groundable content offered with neither is invalid: material put forward as evidence must state where it came from. Content that is addressable only carries no such requirement. Arguments are outside this rule, their Assertions being groundable by virtue of the type rather than by a declaration; their provenance is carried by `authors` (§5) and, for an imported Argument, by `extracted_from` and `import_method` (§9).

Arguments are the exception to the requirement. An Argument need declare no AddressingMethod: its Assertions, and only its Assertions, are groundable, and they are so by virtue of the type. An Argument may nonetheless declare addressable-only methods where finer reference into its content is useful — a passage within a long `evaluation`, say — but no method it declares may be groundable, what is groundable in an Argument being fixed by the type rather than by declaration.

AddressingMethod (Object) required properties, in addition to the universal `name` and `type` (§1), the `name` being the method name that opens a schema reference:
 - `description` (string): how a reference under this method is written, and what content it reaches.
 - `groundability` (enumerated string): one of `groundable` or `addressable_only`, stating whether content reached by this method may be used in a Ground.

On a non-groundable Artifact, and on an Argument, `groundability` must be `addressable_only`.

## 5. Attribution

The Member who publishes an Artifact may or may not be the author of its content. An Artifact must declare its content's author or authors in an `authors` property (list of strings) whenever that content is groundable, or whenever it was authored by anyone other than the publishing Member — in particular, any content imported from an external source. Authors are recorded as free strings; this version of the specification does not define an address form for naming a Member as an author. Imported content, for example, carries the attribution of its external authors even when it is non-groundable.

Required property:
 - `authors` (list of strings): the author or authors of the content, recorded as free strings; required when the content is groundable or was authored by anyone other than the publishing Member.

## 6. Locations of content

An Artifact may itself *contain* its content, expressed in its properties, Objects, and Object properties. For example, a free text property may contain large and structured values such as tables formatted as CSV text.

An Artifact may also represent content in an external database, file store, or other location that the Community accepts as archival. It must satisfy the constraint that Artifacts are immutable and dated. For example, an Artifact published in a Community working with protected data might represent a database at a firewalled location, documenting its schema and access methods.

If an Artifact represents external content, it must specify its location in a `location` property (list of strings) and access methods in an `access_methods` property (list of strings). This specification defines no syntax for either; conventions may emerge through use. Access methods, such as a database API, are different from the schema for the content at that location.

Any Artifact type may represent external content, the non-groundable types included: a Model or an execution log held in an external store is recorded the same way. `location` and `access_methods` state where content *resides*. They are not provenance and do not satisfy the requirement that groundable content state where it *came from* (§4). An Artifact representing external content that it declares groundable must therefore also record how that content entered the record, under §8.

Properties (required when the Artifact represents external content):
 - `location` (list of strings): where the external content resides.
 - `access_methods` (list of strings): how the content at that location is accessed, such as a database API.

## 7. Common groundable Artifact types

Any Artifact other than an Argument and the non-groundable types may declare groundable content in its AddressingMethods (§4). The following Artifact types correspond to common sources of evidence. Use of these types facilitates legibility and consistency for Members using the Community record but their use is not required.

- **Data** is a Member's published record of scientific *values* that may be original observations or derived results. Data enters the record by one of the two routes open to any Artifact with groundable content (§4): it is `produced_by` an Analysis and published with it as a Bundle, or it is imported under an `import_method` (§8) — whether from an external resource or from the Member's own results held outside the record. If the Data is imported, it is the importing Member's rendering, not a canonical copy; another Member may publish their own Data based on the same source.

- **ScientificPublication** is an external source that is, broadly, a part of the scientific literature. This is typically a published paper containing evidential statements, figures, or tables, but the ScientificPublication Artifact type can include alternative forms of publication. 

## 8. Importing content

To *import* content is to bring it into the record from outside the record. The boundary that matters is the Community's own record and not the Member's institution. An external publication, a public data resource, and a third party's model are all imported; so are a Member's own experimental results, where those results were not produced by an Analysis published to the Community. Import is therefore the general case rather than a provision for reusing other people's work, and the two routes by which groundable content acquires provenance (§4) divide on exactly this line: content produced by an act recorded in the Community, and content that originated outside any such act.

A Member holding results from a bench experiment accordingly has two ways to place them in the record, and the choice is about what she wishes the record to carry. If she wants the generating procedure inspectable, she publishes an Analysis describing the experiment — an Analysis records a procedure that was performed, and nothing confines it to computation — and bundles the Data with it. If she wants only the values, she publishes Data representing them, wherever they are held, describing under `import_method` how they were rendered. The values may be declared groundable either way; what differs is whether the record carries an account of how they were produced.

A Member might choose to *import* some or all of the content from a publication, data resource, or external model to create an Artifact such as a ScientificPublication or Data, processing it to be stored in the Artifact's data structure. 

They may also process the original external content and store it as a new external source. For example, an author might choose to convert the text of a PDF document to Markdown for efficiency in future use by agents. In both cases, the Member bears responsibility for the *fidelity* of the import and is required to describe the import method in an `import_method` property (string). Note that a different Member may create their own imported Artifact from the external source.

An imported Argument (§9) is an import in this sense and carries the same obligation. The extraction of an author's reasoning is the method by which their content was brought into the Community, and it is recorded in `import_method` alongside the `extracted_from` address; naming the same act twice, once as extraction and once as import, would be two words for one thing. The presence of `import_method` is what marks an Artifact as imported. An Artifact that does not carry it presents content originating within the Community, and the conditional requirements of this section are therefore determinable from the Artifact itself.

Required property:
 - `import_method` (string): a description of how the content was brought into the record from outside it; the importing Member bears responsibility for the fidelity of the import.

## 9. Findings vs content

An imported Artifact such as a ScientificPublication may have presented one or more *findings* to its readers. It is permissible to ground on those findings by addressing specific content, but when an author's finding is presented with an argument of any complexity, it is better practice to extract the author's arguments as an Argument created by a Member, linked to the source Artifact via an `extracted_from` property. That Member bears responsibility for the *fidelity* of their analysis that *extracted* the author's reasoning but the responsibility for that reasoning and evidence is attributed to the authors in a required `authors` property. Importing an Argument does *not* imply that the Member endorses the author's arguments. Note that a different Member may create their own import of the author's arguments.

The imported Argument must document the imported Artifact from which it was extracted by giving its address in an `extracted_from` property (address).

A Member who judges an existing imported Argument to be an unfaithful reconstruction publishes her own import of the same source, and may record the earlier import in `supersedes`, its `supersedes_rationale` stating what she takes the earlier rendering to have got wrong (§1). She may set out her reasons at length in a Report, or address them to the importing Member in a Message. She may also publish nothing but the better import: standing beside the first, against a source both name, it is itself the correction.

What she need not do is construct an Argument contesting the reconstruction. Fidelity of an import is a judgment about the *record* — whether an Artifact faithfully renders a source — and not a claim about the world, and this specification does not route judgments about the record through its evidential machinery. The two are contested differently, which is why keeping them apart costs nothing: a claim about the world is answered by returning to the evidence and rendering a verdict (§3), whereas a rendering is answered by producing a better one. Both remain in the record, and a reader may compare them against the source each names.

The same holds for the other judgments a Member may form about an Artifact rather than about the world — that an import was careless, that a Report overstates what its sources establish, that an Analysis was ill-chosen for its task. Such judgments may be recorded in non-groundable Artifacts, or left unrecorded; nothing here requires a Member to formalize a criticism in order to make it. Where a Member wishes a judgment of this kind to bear evidentially on some claim, the route is the one given in §4: publish groundable content and ground on that.

Required properties:
 - `extracted_from` (address): the address of the source Artifact from which the imported Argument's reasoning was extracted.
 - `import_method` (string): how the reasoning was extracted, as for any import (§8).

## 10. Non-groundable Artifact types

The following Artifact types are defined as *non-groundable* in that they *guarantee* that *none* of their content is *groundable*. They organize, communicate, or record work but are never a source of evidence in an Argument. A non-groundable Artifact may have content that can be addressed but references to that content can only be informational, not evidentiary. This is true no matter what is stated in the Artifact; its designation as a non-groundable type has precedence.

Support may flow *into* them by reference, but never *out* of them as evidence.

- **Analysis** records a procedure that was performed, the specific event of performance, not the type of procedure. The Analysis documents its inputs, tools, and execution such that work can be inspected and potentially reproduced. Its *outputs* may be Artifacts with groundable content, such as a Data Artifact, but the Analysis itself has no groundable content.

An Analysis and its outputs are the sole case of a Bundle, as defined in §1. The Analysis and output Artifacts are created at the same instant and neither addresses anything not-yet-published or still mutable. The Analysis and its outputs are two facets of one act: outputs must have been created by some Analysis.

Analysis Artifacts must specify their outputs via an `outputs` property containing a list of Entity addresses, one per output Artifact. Output Artifacts must specify the Analysis that produced them via a `produced_by` property whose value is the Entity address of the Analysis. The two declarations must agree in the sense given in §1.

`outputs` is the exception to the rule that a required list holds at least one element (§1). An Analysis may record work that produced no Artifact — a run that failed, an inspection that returned nothing usable — in which case it is published alone and is not a Bundle. Whether to publish such an Analysis is the Member's choice, as publication is for any Artifact. It is worth publishing where the failure established something a later Member would otherwise have to discover again: an input constraint no documentation recorded, a tool that silently mishandles a case. A run interrupted because the power failed establishes nothing and needs no record.

Required properties:
 - `procedure` (string): a description of the steps performed, including tools and execution, such that the work can be inspected.
 - `outputs` (list of addresses): one per output Artifact, as above. May be empty.

Defined properties:
 - `inputs` (list of addresses): the content the Analysis consumed.
 - `used_models` (list of addresses): Models (below) the Analysis used.

Output Artifact required property:
 - `produced_by` (address): the address of the Analysis that produced the Artifact.

- **Model** is a simplified, reusable representation of a target system, built to serve a purpose. Because a model is an idealization, its content embodies choices — of structure, boundary, parameterization, or curation — that a competent peer could reasonably have made differently; different models of the same target may therefore legitimately disagree. It is this dependence on choices that distinguishes a Model from Data, which represents a value or estimate of a quantity defined independently of how it was obtained. (cf. Box 1987; Giere 2004; Weisberg 2013.)

A Model records these choices in a required `modeling_choices` property (string): the structural, boundary, parameterization, or curation decisions on which its content depends and which a competent peer could have made differently. The property is required because it carries what distinguishes the type. A Model that does not record its choices fails to present itself as a Model, and a reader weighing an output produced with it would have no account of what a competent peer might have done otherwise — which is precisely what she needs, since the outputs of an Analysis using a Model are groundable while the Model itself is not. For an imported Model the property records the choices as the importing Member renders them from the source, under the same responsibility for fidelity as any import (§8).

Required property:
 - `modeling_choices` (string): the structural, boundary, parameterization, or curation decisions on which the Model's content depends and which a competent peer could have made differently.

A Model enters the record in one of two ways, the same two available to Data (§4). A **native** Model is `produced_by` an Analysis the Member performed and is published with that Analysis as a Bundle. This holds even when the generative act is not systematic: an agent that emits a Model from its trained knowledge records in the Analysis which model and version produced it, the prompt or parameters used, and that the result is not reproducible — provenance a later Member needs precisely because the Model has no systematic basis. An **imported** Model is brought in from an external source under the import rules (§8), carrying its `authors` and `import_method`. The requirement holds for a Model although its content is not groundable, because a Model shapes the outputs of any Analysis that uses it and a reader weighing those outputs needs to know where the Model came from.

An Analysis may also *use* a Model, documenting how it was used, to produce outputs with groundable content.

- **Report** communicates or synthesizes work — a summary, survey, recommendation, review, status account, or a plan or protocol not yet performed. Report is the general class for content a Member wishes to clearly mark as non-groundable. A proposal that a claim is worth investigating, previously served by a distinct Hypothesis type, is recorded as a Report.

Required properties:
 - `text` (string): the content of the report.

A Report's author is the publishing Member, or is recorded in `authors` when its content originates elsewhere.

- **Message** is a directed communication between Members. Communities may choose to capture requests, responses, and general scientific dialog between Members. For example, one agent might request that another perform a specific Analysis. Messages might refer to Artifacts such as Arguments or Data but the Messages are not evidential.

Required properties:
 - `recipients` (list of addresses): the Members to which the communication is directed.
 - `text` (string): the content of the communication.

The sender is the publishing Member (`published_by`). 

## Appendix: changes from version 4

**Grounds reduced to one type.** Version 4 defined a `grounding_type` enumeration of `test`, `element`, and `assumption`, with `address` required for the first two and `criterion` required for the first. The enumeration carried no information beyond what the presence of the other properties already carried. A Ground now has an `address` and a `rationale`, and optionally a `criterion`; a Ground carrying a `criterion` is a test, and one without is not.

**Assumptions reified as their own Object type.** The `assumption` grounding type was a category error. A Ground identifies addressable material bearing on an Assertion, whereas an assumption identifies the absence of such material, so an assumption could not supply what the Ground type exists to supply. Assumptions are now a distinct Object type, linked to an Assertion by an `assumes` relationship, holding a `rationale` and no address.

**Assumption standing is stated in prose rather than typed.** Version 4 distinguished granted background from premises posited as unestablished, and forced an Assertion resting only on the latter to a verdict of `insufficient`. Standing in fact varies continuously, and the forced verdict was inconsistent with the principle that verdicts are relative to purpose and are rendered by the author rather than computed by the structure. The `rationale` now carries the author's stance, and must state what is assumed, why no evidence is offered, and how far the Community is expected to grant it.

**Reassessment regrounds on evidence rather than on the prior conclusion.** Version 4 directed a Member reassessing a claim to ground on the prior Argument's Assertion with an `element` Ground. Where the Member disputes that conclusion, this required her to offer as evidence the very statement she rejects. A contesting Argument now addresses the material the earlier Argument rested on. Where that material is not addressable within the Community, the Member records an Assumption; no special provision is needed. Grounding on another Argument's Assertion remains correct where the author accepts the earlier conclusion and builds on it.

**`reassesses` added.** Version 4 had no way to record that one Argument responds to another without either claiming lineage it did not have or offering the earlier conclusion as evidence. `reassesses` is a defined, non-evidential Argument property that states a discourse relation only.

**Hypothesis removed.** The Hypothesis Artifact type drifted toward the structured world model the specification disclaims, and its function is served by a Report together with `derived_from` on the Assertion that takes the proposal up.

**`derived_from` generalized.** Version 4 restricted `derived_from` to a prior Assertion or a Hypothesis. It now names content in any prior Artifact from which an Assertion is drawn, including a proposal recorded in a Report. Its semantics remain narrower than citation: it asserts that the Assertion is based in some way on the content it names, and it continues to carry no evidential support.

**`specification_version` required on every Artifact.** Communities are expected to adopt revised versions of this specification over time, while Artifacts published under earlier versions remain in the record unchanged. Recording the version under which an Artifact was published allows a later Member to interpret its structure by the rules that governed its construction. The value is free text. All Artifacts within a Bundle must declare the same version.

**Grounding directly on a published finding is permitted.** Version 4 stated that an author's arguments, if used evidentially, should be represented as an imported Argument. A Ground may now address specific content in a ScientificPublication directly. Extraction into an imported Argument remains the better practice where the author's finding is presented with an argument of any complexity.

**The verdicts are defined.** Version 4 named the three verdicts and explained their relativity to purpose, but did not define them individually. `insufficient` and `falsified` are now distinguished explicitly: both report that the claim failed to be supported, and they differ in whether the record shows an absence of adequate evidence or the presence of contrary evidence. The differing sensitivity of the three verdicts to purpose is stated.

**`purpose` is required only on the primary Assessment.** Every Assertion continues to be paired with an Assessment, subsidiary Assertions and alternatives included, since a subsidiary verdict is needed in its own right. But `purpose` is now required only on the Assessment of the primary Assertion, where it is the purpose of the Argument as a whole. Elsewhere it is optional, and its absence means the primary Assessment's purpose applies. An author states it on a subsidiary Assessment only where the stakes differ.

**Multi-valued properties declared as lists.** `derived_from`, `reassesses`, `location`, and `access_methods` now take lists. `used_model` is renamed `used_models` and `recipient` is renamed `recipients`, both taking lists, matching `inputs`, `outputs`, and `authors`. A property declared as a list may hold a single element.

**`supersedes` added.** Version 4 stated that an immutable Artifact could be superseded by a later version but provided no means of recording that it had been, leaving a reader unable to tell that one Artifact stands in place of another. `supersedes` is a defined, non-evidential Artifact property taking a list of addresses. Retraction needs no separate mechanism: an Artifact that supersedes an earlier one and withdraws rather than restates its content is a retraction. Grounds addressing superseded content remain valid, since the record of what was relied upon at the time is not erased. A required `supersedes_rationale` states what the new Artifact does with respect to what it replaces — restate, correct, consolidate, or withdraw — so that a reader can tell a replacement from a withdrawal. It is prose rather than an enumerated type because no rule depends on the distinction, and one rationale covers the whole list rather than one per address, the cases worth explaining being those a per-address type would fragment. `supersedes` may name Artifacts published by other Members; it is the publisher's claim and not a judgment of the Community, and it removes nothing.

**Groundability is declared by the addressing method, not by the type.** Version 4 divided Artifacts into trust-bearing and non-trust-bearing, so that any Artifact not of a non-trust-bearing type was groundable in its entirety. This conflated two distinct capabilities. An author may wish to expose fine-grained addresses into material — a passage in a publication, say — so that it can be named and discussed precisely, while declining to offer it as evidence. An Artifact now declares its addressing methods individually, each stating whether the content it reaches is groundable or addressable only. The requirement accordingly attaches to addressing rather than to trust.

**Addressing methods are Objects rather than a free-text `schema` property.** The requirement above was first written as a `schema` property whose prose declared the methods and their groundability. That left a rule of this specification resting on prose: whether a given Ground is legal depends on whether the content it addresses was declared groundable, and two readers could disagree about what a free-text schema declared without either misreading it. Each addressing method is now an **AddressingMethod** Object with a `name`, a free-text `description`, and an enumerated `groundability`. A schema reference names the method it uses, so that resolution is checkable at the method level while the reference syntax within a method stays community-defined. The `schema` property is retired. The division reflects a general principle: prose where a judgment is called for, structure where a rule depends on the answer.

**"Trust-bearing" retired; "non-groundable" retained.** With groundability settled by the addressing method, or by being an Argument, the positive category had no work left to do and its name suggested a property of the Artifact rather than of its content. The negative category survives, renamed *non-groundable*, because a guarantee that a type carries no groundable content is worth having: a reader can rely on it from the type alone without consulting the Artifact's declared methods. Non-groundable Artifacts may not declare groundable content by any means.

**Grounding on an Assertion does not reach its dependencies.** Version 4 did not say whether a Ground addressing another Argument's Assertion also took up the `depends_on` subtree beneath it. It does not. Reaching down a subtree is a within-Argument operation, and evidential weight does not accumulate transitively across the grounding link; an author who wants material from beneath a cited Assertion must address it with a Ground of her own.

**Grounds are always external to their Argument.** A Ground may not address content in the Argument that contains it. Reliance on another Assertion in the same Argument is expressed by `depends_on`, which correspondingly may not cross between Arguments. The two mechanisms now divide the work without overlap: `depends_on` for structure within an Argument, Grounds for evidence from outside it.

**Alternatives are Assertions in full, and are not promoted in place.** An Assertion linked by `has_alternative` may carry its own dependency structure, Grounds, Assumptions, and Assessment; only its position distinguishes it. An Assertion may not be both an alternative and a dependency in one Argument. An author who comes to prefer an alternative publishes a new Argument with that account as its primary Assertion, recording the earlier Argument in `reassesses`, rather than restructuring the Argument that stands.

**`assessed_by` is one to one.** Every Assertion has exactly one Assessment and every Assessment belongs to exactly one Assertion. The rationale for keeping the Assessment a distinct Object rather than a set of properties on the Assertion is stated.

**Bundles are restricted to an Analysis and its outputs.** Version 4 described a Bundle generally, as any Artifacts published in a single atomic act, which would have permitted two Arguments to be co-published and ground on one another. The Bundle exists for one case — an Analysis and the outputs it produced, which are created in the same instant and must refer to each other — and is now confined to it. Circular evidential support is thereby excluded by construction rather than by a rule against cycles. Generalizing the Bundle later is backward compatible.

**Reference is restricted to the strictly earlier past.** Artifacts sharing an identical `created` value are not earlier than one another and cannot refer to each other. Ordering within an identical instant is left undefined, and needs no definition, because the one case requiring co-reference is the Bundle.

**Community governance stated as a non-goal.** The specification relies on Members and on publication but defines no means of admitting, governing, or removing them. This is deliberate, governance being among the things communities should decide for themselves, and it is now listed with the other exclusions rather than left silent.

**`authors` noted as required on every Argument.** This followed already from §5, an Argument's Assertions being groundable, but was not stated where a reader would look for it. §3 now records it, together with the reason the property is not redundant with `published_by`: an imported Argument carries the attribution of the authors whose reasoning it presents.

**`modeling_choices` is required on a Model.** Version 4 and early version 5 defined the property but did not require it, so a conforming Model could omit the very thing that distinguishes the type from Data. Since the outputs of an Analysis using a Model are groundable while the Model itself is not, a reader weighing those outputs has no other record of what a competent peer might have decided differently.

**Imported Arguments carry `import_method`.** §8 required `import_method` of imported content while §9 required only `extracted_from` of an imported Argument, leaving it unclear whether both applied. Both do: extraction is the method by which the content was brought in, and a second name for it would be redundant. The presence of `import_method` is now also the structural marker of imported content, so that the conditional requirements of §8 can be determined from an Artifact itself.

**Fidelity of a reconstruction is contested outside the evidential record.** Whether an imported Argument faithfully renders its source is a judgment about the record rather than a claim about the world, and this specification no longer routes such judgments through its evidential machinery. A Member who judges an import unfaithful publishes her own import, optionally recording the earlier one in `supersedes`, and may state her reasons in a Report or a Message or not at all. This generalizes: judgments about Artifacts rather than about the world may be recorded in non-groundable Artifacts, or left unrecorded. A claim about the world is answered by returning to the evidence and rendering a verdict; a rendering is answered by producing a better one.

**Provenance is stated to be an audit path rather than an evidence chain.** Version 4 left open how a concern about an Analysis — a normalization, a batch correction, a tool version — could bear on an Assessment, given that an Analysis is non-groundable. Such a concern may be weighed in an `evaluation`, which is the author's reasoning and may consider material she has inspected but cannot ground on; it enters the evidential case only by being converted into groundable content, such as an audit or validation result published as Data. Provenance tells a Member what is worth checking; what she finds must be published before it can count.

**Well-formedness rules stated where conformance depended on them.** Several rules were implied by the prose but never stated, so that conformance could not be determined reliably. The temporal-reference rule is now scoped to references *outside* the referring Artifact, intra-Artifact references such as `primary_assertion` carrying no temporal condition — as written, no Argument could conform. Entity, Object, and property names may not contain `.` or `#`, the structural delimiters of an address. Relationships and their properties are exempted from universal addressability, no address form having ever identified an edge. An Analysis's `outputs` and an output's `produced_by` must agree reciprocally, and all Artifacts in a Bundle must share an identical `created` value. Every Assertion must be reachable from the primary Assertion, so that an Argument is rooted; and the bar on being both an alternative and a dependency is read over reachability, which forbids resting on a rival while permitting two rivals to share a dependency. A Ground and an Assumption each belong to exactly one Assertion, their rationales being written for that Assertion. A required list property holds at least one element unless its definition says otherwise, which `outputs` now does: an Analysis may record work that produced nothing.

**Import generalized to any content originating outside the record.** Version 4 and early version 5 presented import as the reuse of external publications, data resources, and models. The boundary that matters is the Community's record rather than the Member's institution: a Member's own experimental results, where they were not produced by an Analysis published to the Community, enter the record by import as anything else does. The two provenance routes divide on this line. Representing external content is therefore not a third route — `location` and `access_methods` state where content resides rather than where it came from, so an Artifact representing content it declares groundable must record an `import_method` as well. `import_method` keeps its name although it now names the general case.

**Non-groundable Artifacts and Arguments may declare addressing methods, all of them addressable only.** An early formulation of the AddressingMethod change would have left fine-grained addressing unavailable in a Report, an Analysis, or a Model, since those types declare no methods and a schema reference resolves only against a declared one. Addressing and groundability being separate, there is no reason to withhold the first in order to withhold the second. Any Artifact may declare addressing methods; on a non-groundable Artifact, and on an Argument, every declared method must be `addressable_only`. What is groundable in those types is fixed by the type and cannot be enlarged by declaration.

**Groundable content must have provenance.** Content reached by an addressing method declared groundable must be either `produced_by` an Analysis published with it as a Bundle or imported under an `import_method`. Version 4 required this of Analysis outputs and stated it for Model, but left Data and other groundable content free of any provenance obligation, so that values could be published as evidence with no account of their origin. Content declared addressable only carries no such requirement, and Arguments are outside the rule, their provenance being carried by `authors` and `extracted_from`.
