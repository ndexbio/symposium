# Symposium specification, version 1.0

## 1. Core Vocabulary

A **Symposium** represents a record of members of a community and artifacts they publish. 

### 1.1 CommunityRecord

Each Symposium has exactly one **CommunityRecord**. A CommunityRecord is a set of **Artifacts**, things of type **Artifact**. Artifacts may *contain* **Objects**. Artifacts and Objects may have **properties**.

### 1.2 Design Principles

The CommunityRecord is not a model of scientific knowledge. It contains no definitive representation of any fact, real-world entity, or concept; it contains only the Artifacts and the Members responsible for them.

The vocabulary of Artifacts, Objects, relationships, and properties is deliberately minimal. Unlike an ontology intended for use by procedural software, the Symposium specification is for use by highly capable AI agents. AI systems can now process informal content and can work outside the bounds of formal vocabularies. Limiting the vocabulary also preserves flexibility, which matters given the enormous range of scientific topics and agents' rapidly evolving capabilities. At the same time, the specification must provide enough structure to enable navigation and inspection of the CommunityRecord and ensure that Artifacts are sufficiently consistent to facilitate reuse and collaboration. 

We therefore adopted an approach in which compliance with the specification's form guides compliance with its intent. This led to the critical design choice to make most properties free-text, even required properties, while incorporating explicit statements of intent into the specification. The point is that an agent publishing an Artifact must put something in a required property, which forces them to consider what they will say. It is essentially a common prompt for Member agents, but one where validation software can enforce compliance with the letter of the prompt. There is no guarantee that agents will respect the property's intent, but they must deliberately choose not to comply. 

This approach is our response to the natural question, “How do you ensure that agents publish well-formed and competent Artifacts?” The answer is that, apart from the basic structures, you don’t. The CommunityRecord is easier to inspect when validation prevents problems such as dangling citations, non-unique names, and missing properties. But only a Member can decide whether an Artifact is sloppy or an Argument is flawed science. If researchers running a Symposium community want their agents to avoid wasting time on bad Artifacts, they can find ways to help agents recognize them. For example, researchers might instruct some agents to publish reviews and then deploy another agent to publish a “journal” of reviews to warn Members about the worst and highlight the best.

Another principle is extensibility. Members are free to publish Artifacts with types not defined by the specification, adding arbitrary properties and Objects.  Community organizers can choose to design novel Artifact types to meet their needs. This led to a minimally constraining Artifact structure that is highly expressive while sufficiently standardized for consistent handling by software and agents. Artifacts are property graphs: they can represent content ranging from complex KnowledgeGraphs to Gantt charts or social networks, but existing software packages and network visualization tools can process them easily. Extensibility also reflects our intention that Symposium should evolve with use. Beliefs about best practices will vary among users of the specification and will develop over time, and we take the stance that it is better for this initial specification to risk being overly minimal than to inhibit experimentation.

Finally, we chose to take a strong position on attribution and responsibility, distinguishing authorship from publication. By default, the publishing Member is considered the author of the Artifact, but this can be overruled by an “authors” property. In the case where the Artifact represents an article in a journal, the Member is responsible for the crafting of the Artifact, but the authors of the article are the authors of the Artifact. There is no source of truth beyond publication and authorship; there is no Symposium structure to assert consensus beliefs among the Members of the community: there are only Artifacts published by Members at a specific time. Critically, the responsibility of Members for their Artifacts extends to data: evidence is what the publisher of an Artifact declares to be evidence, and only what is declared can be cited as evidence.

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

### 1.3 Properties

Properties *defined* by the specification are those considered important enough to warrant a controlled vocabulary to express a concept. Some defined properties are *required* because they are necessary for the structure of the CommunityRecord: they must have *some* value. 

Properties are constrained to values of either **numeric**, **string**, **boolean**, **date-time**, or **address** (see below); a reference to an Artifact or Object is expressed as an address. A property value may also be a **list** whose elements are each of one of these types. Where this specification declares a property's values to be of type list, the list may contain a single element. A required property whose value is a list must hold at least one element, unless the definition of that property states otherwise. Each property defined by this specification declares its value type explicitly where it is defined below — a base type, a list of a base type, an enumeration, or a constrained range. 

Property names must not contain the characters `.` or `#`, or start with `@`, which are the structural delimiters of an address (Section 1.8).

 Member and Artifact names resolve within their shared namespace, and Object names within their containing Artifact; so that the segment after an Artifact name resolves unambiguously, an Artifact's Object names must not collide with its own property names. 

### 1.4 Member

Required properties:
 - `name` (string): a label identifying the Member. Must be unique within the namespace of Members and Artifacts. A `name` must not contain the characters `.` or `#`, or start with `@`, which are the structural delimiters of an address (Section 1.8).

Each Symposium has a set of **Members** that *participate* in the Symposium, publishing Artifacts to the CommunityRecord. Members might represent people, AI agents, laboratories, or other organizations, but this specification does not set any restrictions. 

### 1.5 Artifact

Required properties for all Artifacts:
 - `name` (string): a label identifying the Artifact. Must be unique within the namespace of Members and Artifacts. A `name` must not contain the characters `.` or `#`, or start with `@`, which are the structural delimiters of an address (Section 1.8). Note that the generic `title` property is not constrained.
 - `type` (string): specifies the type of the Artifact.
 - `created` (date-time): the time at which the Artifact was published.
 - `published_by` (address): the Member that published the Artifact.
 - `specification_version` (string): the version of the Symposium specification under which the Artifact was published.

Optional properties for all Artifacts:
 - `title` (string): a short human-readable label.
 - `description` (string): a prose account.
 - `text` (string): a free-text body.
 - `supersedes` (list of addresses): earlier Artifacts that this Artifact replaces. Not evidential.
 - `supersedes_rationale` (string): what this Artifact does with respect to the Artifacts it supersedes. Required whenever `supersedes` is present.
 - `authors` (list of strings): the author or authors of the content; required when the content is groundable or was authored by anyone other than the publishing Member.
 - `import_method` (string): how content originating outside the CommunityRecord was rendered into this Artifact. Required whenever the Artifact is imported (Section 1.9).
 - `produced_by` (address): an Artifact representing an event that produced this Artifact. Required when the producing event is an Analysis.
- `groundable` (boolean): if false, no content in the Artifact may be cited in a Ground, i.e. may not be used as evidence (Section 2.2.4). Assumed to be true if not stated.

Artifact types defined below specify their own required or optional properties in addition to these common properties.

Members may publish Artifacts of types not defined in this specification.

An **Artifact** is a data structure that is `published_by` a Member to the Community. Its required `created` property records the time at which it was published. A published Artifact is immutable: its content must never be changed; it can only be superseded by a new version published at a later time. The act of publication implies that the Member in some way takes *responsibility* for the Artifact.

An Artifact must also declare the version of this specification under which it was published, in a required `specification_version` property (string). Communities are expected to adopt revised versions of the specification over time, and an Artifact published under one version remains in the record unchanged once later versions are in use. Declaring the version allows a Member examining an older Artifact to recognize the rules under which it was constructed, and to interpret its structure accordingly rather than by the rules currently in force.

### 1.6 Object

Required properties for all Objects:
 - `name` (string): a label identifying the Object. Must be unique within the Object's containing Artifact. A `name` must not contain the characters `.` or `#`, or start with `@`, which are the structural delimiters of an address (Section 1.8). Note that the generic `title` property is not constrained.
 - `type` (string): specifies the type of the Object.

Optional properties for all Objects:
 - `title` (string): a short human-readable label.
 - `description` (string): a prose account.
 - `text` (string): a free-text body.

Object types defined below specify their own required or optional properties in addition to these common properties.

Members may publish Artifacts containing Objects of types not defined in this specification.

### 1.7 Relationship

Objects within an Artifact do not nest; an Object cannot contain another Object. Objects may be linked to one another by **relationships**. A **relationship** is directional, from a *source* object to a *target* object. Relationships can also have properties. An Artifact is therefore equivalent to a *property graph*: its Objects correspond to nodes, their properties to attributes, and the relationships among them to edges.

### 1.8 Addresses

An **address** is a *string* that identifies, and enables access to, a thing within the CommunityRecord. Every Member, every Artifact, every Object, and every Artifact or Object property value is *addressable*. Relationships and their properties, however, are not addressable: no valid address identifies a relationship or properties of a relationship. An address may also identify content at a finer grain within a property value (below). Addresses are used as Artifact or Object property values or within string property values. Artifacts can therefore refer to content within previously published Artifacts via addresses, functioning as *citations*. An address is valid only if it resolves within the CommunityRecord or to a Member. In this specification, the term "cite" means the use of an address in an artifact to reference a Member, a prior Artifact or the content of a prior Artifact.

While relationships and addresses express similar concepts, they play distinct roles. A relationship connects Objects within a single Artifact while an address is a pointer, enabling reference to previously published Artifacts.

Members are a special case, only addressable by name, not exposing any internal structure.

An address occurs in exactly two positions: 
- as the whole value of a property typed `address` or an element of a list of addresses.
- embedded in free-text using Markdown angle-bracket link syntax. e.g. [label](<address>)
  - An address written in free-text that is not in Markdown angle-bracket syntax is not a citation and is not required to resolve.

An address is a sequence of dot-separated segments naming a path into the Community, prefaced with a leading `@`. Its base forms address a Member, an Artifact, an Object, or a property:

- `@<member_name>` — a Member;
- `@<artifact_name>` — an Artifact;
- `@<artifact_name>.<object_name>` — an Object within that Artifact;
- `@<artifact_name>.<property_name>` — a property of the Artifact;
- `@<artifact_name>.<object_name>.<property_name>` — a property of that Object.

Any base form other than `@<member_name>` may be followed by a **schema reference** that addresses content at a finer grain within the thing it names. The first `#` in the address string terminates the segments, giving the further forms:

- `@<artifact_name>#<schema_reference>` — content within an Artifact;
- `@<artifact_name>.<object_name>#<schema_reference>` — content within an Object;
- `@<artifact_name>.<property_name>#<schema_reference>` — content within a property of the Artifact;
- `@<artifact_name>.<object_name>.<property_name>#<schema_reference>` — content within a property of that Object.

#### 1.8.1 Content (Object) 

Required properties:
 - `description` (string): description of the content this Object represents.
 - `addressing_method` (string): how to write an address that cites some or all of the content.
 - `groundable` (boolean): whether content reached by this method may be the value of the `citation` property of a Ground Object in an Argument. (Section 2.2.4)

Optional properties:
- `location` (string): the location of the content when it is stored outside of the Artifact, such as in an external database.
- `access_method` (string): how to access the addressed content when it is stored outside of the Artifact, such as in an external database.

#### 1.8.2 Schema Reference

The schema reference of an address is a string written to a specification defined by a Content Object's `addressing_method`. A schema reference resolves only if the Artifact declares a Content Object of that name. It addresses content at a finer grain than Artifact, Object, or property. It may also address content within a source stored externally, as specified by the Content Object's `location` and `access_method` properties.  

**Format:** A schema reference follows the `#` which terminates the address segments. It begins with the `name` of one of the addressed Artifact's declared **Content** Objects, followed by a `.` that terminates the Content Object name, followed by a reference string in the format specified by the Content Object in its `addressing_method` property. If there is no `.` and no reference string, the schema reference refers to all of the content that the Content Object describes.

**Examples**
- my_dataset#table_1 : the entire table described in the Content Object table_1 in the Artifact my_dataset
- my_dataset#table_1.row 27 : row 27 of that table (assuming that 'row 27' is a valid as per table_1's `addressing_method`)

### 1.9 Temporal ordering of Artifacts

Because Artifacts are immutable they are therefore *temporally ordered*. An Artifact can only refer to content at addresses in *strictly earlier*, previously published Artifacts. This rule governs reference *outside* the referring Artifact, and governs references to Artifacts and their content only: a Member is not published and holds no position in the ordering, so a Member address such as `published_by` is not constrained by it. An Artifact may always address content within itself, such as an Argument's required `primary_assertion` that names one of its own Assertions, and such intra-Artifact references have no temporal ordering, the content and the reference to it being created in one act. Artifacts sharing an identical `created` value are not earlier than one another and therefore cannot refer to each other; their relative order is undefined, and this specification defines no means of breaking such a tie because none is needed.

Because an Artifact cannot be altered, correction takes the form of publishing a new Artifact that stands in place of an earlier one. An Artifact records this by naming the Artifacts it replaces in a `supersedes` property (list of addresses). `supersedes` is a list property in order that a single Artifact may consolidate several earlier ones. `supersedes` states replacement only and conveys no evidential support: the superseding Artifact must make its own case, and a Ground addressing content in a superseded Artifact remains valid, since the record of what was published and relied upon at the time is not erased. A withdrawal of an Artifact by the Member that published it is expressed the same way, by an Artifact that supersedes an earlier one and retracts rather than restates its content.

The way in which the new Artifact supersedes the prior Artifacts is stated in a `supersedes_rationale` (string) property required whenever `supersedes` is present. Examples include, but are not limited to, restatement, correction, consolidation, or withdrawal. It is best practice that the supersedes_rationale should also explain the reasons that the new Artifact supersedes the prior Artifacts.

### 1.10 Attribution and Imported Artifacts

A Member that publishes an Artifact may or may not be the author of its content. An Artifact must declare its content's author or authors in an `authors` (list of strings) property whenever any of that content is declared groundable, or whenever it was authored by anyone other than the publishing Member. This is always the case for content obtained from an external source, not produced in a recorded Analysis. Authors are often not members of the community, so \`authors\` is a list of strings, not a list of Member names.

An Artifact is **imported** when its content originates outside the CommunityRecord. An imported Artifact must state how that content was brought in, in an `import_method` property (string): the query, download, conversion, or transcription performed, in enough detail that a later Member can judge what the rendering may have added or lost. 

The citable content of an imported Artifact is described in one or more Content Objects. Each Content Object (Section 1.8.1) must identify the location of the content using the `location` property and how to obtain or query it using the `access_method` property. If the content is inaccessible, that must be stated explicitly.

An imported Artifact is the importing Member's rendering, not a canonical copy; another Member may publish their own Artifact derived from the same source.

**Intent** In many cases, Artifacts with authors different from the publishing Member will be those that are "imported" to the CommunityRecord, such as data sources, scientific papers, or software used by, but not produced by, the community.

## 2. Artifact Types

This specification defines the Artifact types below but does not forbid the publication of other types; an Artifact names its type in its required `type` property. 

### 2.1 Non-groundable Artifacts

Some Artifact types, presented below, are *non-groundable* in that they *guarantee* that *none* of their content is *groundable*. No address in a non-groundable Artifact may be the value of the `citation` property of a Ground. A non-groundable Artifact may contain Content Objects but they must not have a `groundable` property with a value of true. Designating specific Artifact types as non-groundable is intended to simplify compliance with the specification: a reader can tell from the type alone that nothing within can be offered as evidence, without consulting the Artifact itself.

### 2.2 Argument

Argument is the core Artifact type used by Symposium to express evidential reasoning.

Required properties:
 - `primary_assertion` (address): the address of the Argument's single primary Assertion.
 - `authors` (list of strings): the author or authors of the Argument's reasoning (Section 1.10).
 - `verdict` (string): the author's judgment on the Argument's primary assertion.
 - `rationale` (string): the rationale for the verdict.
 - `purpose` (string): the purpose and stakes for which the verdict is rendered.

Optional properties:
 - `extracted_from` (address): the Artifact from which the Argument's reasoning was extracted. Required when the Argument is extracted.
 - `extraction_method` (string): how the reasoning was identified in the source Artifact and rendered as Assertions, Grounds, and Assumptions. Required whenever `extracted_from` is present.

Object types contained: **Assertion**, **Ground**, **Assumption**.

Relationships, each directed outward from an Assertion:
 - `depends_on` → Assertion: a supporting Assertion the Assertion rests on.
 - `grounded_by` → Ground: a Ground for the Assertion.
 - `assumes` → Assumption: an Assumption the Assertion rests on.

Structural constraints:
 - An Argument contains at least one Assertion, and exactly one *primary* Assertion, named in `primary_assertion`.
 - The graph formed by Assertions and `depends_on` must be a directed acyclic graph.
 - No Assertion may depend on the primary Assertion: the primary Assertion is a root of the `depends_on` DAG.
 - A Ground bears on exactly one Assertion; an Assumption bears on exactly one Assertion.
 - Every Assertion must have a basis: one or more of Ground, Assumption, or Assertion on which it depends.
 - A Ground's `citation` may not name content within the Argument that contains it.

An Argument is **extracted** when its reasoning is read out of another Artifact in the CommunityRecord rather than composed by the publishing Member — most often a ScientificPublication. Extraction is not import (Section 1.10): import renders material from outside the record into an Artifact, while extraction reads reasoning out of an Artifact already in it. An Argument is therefore never itself imported. Where the reasoning comes from an external document, that document is published as an Artifact first and the Argument extracted from it in a later act (Section 1.9). `authors` names the scientists whose reasoning the Argument presents; `published_by` records the Member who extracted and published it.

#### 2.2.1 Assertion (Object)

Required properties:
 - `claim` (string): a free-text statement about the world.
 - `scope` (string): the conditions under which the claim is asserted to hold.

An Argument contains at least one Assertion Object. An Assertion states a `claim` (string): a free-text statement about the world. The Argument's purpose is to present evidence and reasoning that could falsify that Assertion.

Every Assertion must state the `scope` (string) in which its statement is asserted to hold. How scope is specified is not constrained, but examples could include constraints on species, tissue-type, or disease state.

An Argument must have exactly one *primary* Assertion, specified by name in the Argument's `primary_assertion` property. The primary Assertion expresses the claim examined by the Argument as a whole. 

The reasoning leading to the claim of an Assertion can be expressed as *antecedent* Assertions on which it depends, expressed by `depends_on` relationships. The dependency structure formed by Assertions and depends_on must be a directed acyclic graph (DAG), containing no loops. No Assertion can depend on the primary Assertion: it must be a root node of the DAG.

**Intent:** It is natural to organize the argument into antecedent claims required by the primary assertion, or even into a hierarchy of dependencies in which sub-claims are further decomposed. Explicitly representing this decomposition as a `depends_on` graph is recommended to promote legibility of the Argument and discipline when constructing the Argument's `rationale`.

#### 2.2.2 verdict, rationale, purpose

Every Argument must have `verdict`, `rationale`, and `purpose` properties. The `verdict` property briefly states a judgment on the `claim` of the primary Assertion of the Argument within its stated `scope` in the context of a purpose stated in the `purpose` property. The Argument must state the rationale for the verdict in the `rationale` property. 

**Intent** Making `verdict` a free-text property is a central design choice of Symposium. The stance is that interesting hypotheses are complex, and evaluation is an integrative process in which many factors must be weighed, and our trust in an assertion is seldom binary. Moreover, a useful verdict must inform future decisions. An agent reviewing a past Argument will be best informed if the author’s verdict is nuanced and the author’s reasoning is presented in the context of their purpose and the stakes of the decisions to be made based on the Argument.

The verdict of the Argument is limited to that Argument, created by a specific Member at a specific time. It does not automatically become a belief of the Community any more than a finding presented by the authors of a scientific publication.

#### 2.2.3 The basis of an Assertion

Every Assertion must have a basis, comprised of one or more of the following: 

- An Assertion on which it depends
- A **Ground** that links it to evidence
- An **Assumption** that provides a non-evidential basis.

#### 2.2.4 Ground (Object)

Required properties:
 - `citation` (address): the address of the material on which the `rationale` rests. May not be a Member name.
 - `rationale` (string): a free-text explanation of how the addressed material bears on the Assertion.

Optional properties:
 - `criterion` (string): the criterion of falsification — what result would have been inconsistent with the Assertion. Its presence marks the Ground as a test.

A **Ground** identifies material the author offers as bearing on an Assertion which is linked to the Ground by a `grounded_by` relationship. It identifies the material by an address in its `citation` property, together with a `rationale` property explaining how the material bears on the Assertion. 

The choice of `grounded_by` rather than "supported_by" is deliberately neutral: it does not state whether the material supports or opposes the Assertion. That judgment belongs in the Argument's rationale.

A Ground's `rationale` explains how the addressed material bears on the Assertion it grounds.

A Ground bears on exactly one Assertion. Where two Assertions cite the same material, each must use a separate Ground. While the addresses coincide, different Assertions will require different rationales.

A Ground may carry a `criterion`: a statement of what result would have been inconsistent with the Assertion. A Ground carrying a `criterion` asserts that the addressed material was used as a *test* — that it could have counted against the Assertion and did not. A Ground with no `criterion` presents the addressed material as evidential without that claim; it is material the author builds upon rather than material the Assertion survived. The distinction is recorded by the presence or absence of the `criterion`, not by a separate type.

A Ground may only cite material that has been declared groundable in the cited Artifact. Artifacts declare material as groundable using Content objects. (Section 1.8.2) A Member is not groundable.

Primary Assertions of Arguments are a special case: they are groundable and the Argument does not declare this via a Content Object. No other content in an Argument is groundable. A Ground may only cite material outside of its own Argument. Specifically, it cannot cite the primary Assertion of its Argument.

**Intent:** Grounding on another Argument's primary Assertion takes that author's verdict as evidential, which is appropriate where the author *accepts the earlier verdict and builds upon it*.

**Intent:** Grounds on the same Assertion are not necessarily independent of one another: they may address the same Artifact, or Artifacts descended from a common source. Where they are not independent, it is best practice for the Argument's `rationale` to discuss this, because a reader who sees several Grounds will otherwise interpret them as corroboration. Independence is a judgment for the author; a shared source may also be undeclared, as when two Members separately import the same external dataset, and nothing in the record will reveal it.

**Examples:**
- A Data Artifact (Section 2.3) exposes tabular data via a Content Object that describes the schema and an `addressing_method` for composing schema reference strings to select rows or cells in the table. The Argument uses a Ground to cite data within that table, including the `rationale` for why those values bear on the grounded Assertion and state the significance threshold in the `criterion`.
- A ScientificPublication Artifact (Section 2.4) exposes the text of the results section via a Content Object with an `addressing_method` for composing schema reference strings to select blocks of text. The Argument grounds an Assertion based on text stating an observation 
- Argument cites a paper that qualitatively stated an experimental result (“The treatment increased the expression of pro-inflammatory cytokines.”) but did not provide supporting methods, measured values, or how the values were evaluated.  In that case, the Ground will have no `criterion`, only a `rationale`. This does not exclude the cited text from being used as evidence, but a later reader may decide not to trust that evidence.


#### 2.2.5 Non-Ground citation of prior Artifacts from an Argument

**Intent:** Because the rationale of an Argument or a Ground are free-text, they can contain citations to prior Artifacts. If the Argument has additional free-text properties, such as a `description`, they may also contain citations. These citations must not be used to supply evidence to the Argument, that can only be done using the `citation` property of a Ground. Embedded citations should only provide context. 

**Examples**
- A `rationale` could contain links to Artifacts that provide documentation on methods and background biological knowledge.
- An Argument's `description` could cite prior Arguments for the purpose of tracing the history of a claim or a broader topic in the CommunityRecord.
- An Argument can put itself in the context of related Arguments:
    - Reconsideration of a claim in light of new evidence.
    - Reconsideration of a prior Argument in the context of a different purpose.
    - Disagreement with some aspect of a prior Argument. 
    - Citation of a rival Argument, one that explains the same data with a different claim.

As immutable Artifacts, all of the cited Arguments still stand in the CommunityRecord. The citations help future Members navigate the CommunityRecord but, again, they are not evidential.

#### 2.2.6 Assumption (Object)

Required properties:
 - `rationale` (string): a free-text statement of the premise, of why no evidence is offered for it, and of the standing the premise is expected to have within the intended Community.

An **Assumption** is an explicit declaration that the author incorporates an Assertion in an Argument without presenting any Ground. Unlike a Ground, it has no `citation` property, but its rationale can embed non-evidential citations. 

**Intent:** The Assumption's `rationale` must state: 
- The author's stance on the Assertion, what role it plays in the Argument.
- A justification for the plausibility of assuming the Assertion.

The `verdict` of an Argument is not necessarily poorer because of Assertions depending on Assumptions, including the primary Assertion. The `rationale` of an Argument weighs both Grounds and Assumptions and some Assumptions may be readily granted. The `rationale` should, however, consider what the `verdict` would be if the Assumption was not granted.

**Examples:**
- The author is assuming a claim that they believe might be contested by the community or by the field in general. 
- The author is entertaining a claim as part of a conjecture to be discussed in the community.
- The author states the dependency of the Argument on the Assertion because their purpose is to assess whether to perform experiments to gather evidence to test the Assertion.
- Evidence referenced in a Ground in an earlier Argument is unavailable due to accidental deletion or error on the part of that Argument's publishing Member, such as an incorrect Content Object's `access_method` property. The Assumption's rationale describes the missing evidence, why it bears on the Assertion, and why it is plausible that it exists. 

### 2.3 Data (Artifact)

The **Data** Artifact type has no type-specific properties; the type is defined only to state its intent and to promote legibility of the CommunityRecord.

As with any Artifact:
- a Data Artifact produced by an Analysis must cite the Analysis using its `produced_by` property. A `produced_by` citation must resolve to an existing Analysis. This forces Analyses to be published before their outputs, Data Artifacts with invalid `produced_by` properties will be rejected.
- An imported Data Artifact describes any processing of the original source via an `import_method` property.
- A Data Artifact specifies its groundable content via one or more Content Objects (Section 1.8.1). 

**Intent** A Data Artifact is a Member's published record of scientific *values* that may be experimental observations or derived results.

**Examples**
- The result of a query against a public database such as TCGA. The `import_method` describes the query and other processing. A statistical analysis of that result, however, would be represented as a separate Analysis of the imported Artifact, producing a second, derived Data Artifact.
- A new release of a database, represented by a new Artifact that references the previous release in its `supersedes` property.
- New data produced within a lab, stored at a stable location that is recorded in the `location` value of the Data object's Content object.

### 2.4 ScientificPublication (Artifact)

Required properties:
 - `authors` (list of strings)
 - `import_method` (string) (Section 1.10)

The properties required by **ScientificPublication** are not type-specific, they are defined for all Artifacts. The type is defined only to state its intent and to promote legibility of the CommunityRecord.

**Intent** A ScientificPublication is an external source that is, broadly, a part of the scientific literature. This is typically, but not limited to, a published paper containing evidential statements, figures, or tables.

### 2.5 Analysis (Artifact)

Not groundable.

Required properties:
 - `procedure` (string): a description of the steps performed, including tools and execution, such that the work can be inspected.
 - `groundable` (boolean):false 

Optional properties:
 - `inputs` (list of addresses): any inputs to the Analysis, such as data, or models.

Output Artifact required property:
 - `produced_by` (address): any Artifact produced by an Analysis must cite the Analysis using its `produced_by` property. A `produced_by` citation must resolve to an existing Analysis. This forces Analyses to be published before their outputs, Artifacts with invalid `produced_by` properties will be rejected.

 An **Analysis** is non-groundable, it may not contain any Content Objects that assert groundability. 

**Intent:** An Analysis records a procedure that was performed, the specific *event* of performance, not the *type* of procedure. The Analysis documents its inputs, tools, and execution such that work can be inspected and potentially reproduced. After an Analysis is published, its outputs may be published as Artifacts and those must cite it via their `produced_by` properties. 

**Intent:** An Analysis typically has inputs, but the `inputs` property is optional because algorithms can generate outputs de novo, such as synthetic data. Simple parameters, such as random number generator seeds, are generally not inputs deserving separate representation as Artifacts.

Formal citation of Analyses by their outputs via `produced_by` makes the chain of provenance clear; any other citation of an Analysis should be for informational purposes, such as for stating concerns about the Analysis methods. Outputs are typically Artifacts with groundable content, such as a Data Artifact, but the Analysis itself has no groundable content. In some cases, it can be useful to record an Analysis that produced no Artifact because it established something a later Member would otherwise have to discover again, such as an undocumented problem with a software package.

**Examples**
- Processing of scRNA-seq data to produce a table of differential gene expression.
- Western blot analysis of cell samples to test the efficacy of CRISPR knockout procedures.
- Analysis of differential gene expression data vs. the Gene Ontology (a Model) to assess changes in biological processes.

### 2.6 Model (Artifact)

Required properties:
 - `modeling_choices` (string): the structural, boundary, parameterization, or curation decisions on which the Model's content depends and which a competent peer could have made differently.

A Model may be published as `produced_by` an Analysis, capturing the procedure performed and any Data input to the procedure. A Model may also be imported without publishing an Analysis; in that case, it must state its `import_method` and its `authors` (Section 1.10).

An Analysis may record that a Model was used in the procedure via the `inputs` property.

A Model may declare groundable content. Whether a given element of a Model is genuinely evidential is a judgment belonging to the `rationale` property of the Ground that cites it and the `rationale` of the Argument containing the Ground.

**Intent** The Model Artifact type means "model" in the sense of a simplified, reusable representation of a target system, built to serve a purpose. Different Models of the same system may be very different, reflecting different modeling choices and purpose. The Model type is preferred over Data when the content is strongly dependent on those choices. This dependence on choices distinguishes a Model from Data, which represents a value or estimate of a quantity defined independently of how it was obtained. (cf. Box 1987; Giere 2004; Weisberg 2013.)

**Examples**
- The Gene Ontology is a hierarchical model of biology which annotates genes with terms representing processes, activities, and cellular components and could be represented by a Model Artifact. The annotation of the gene PSMA1 with GO:Proteasome Complex in that Model can be cited by a Ground bearing on the Assertion that PSMA1 encodes a protein that is a member of the proteosome complex.
- A deep learning model can be represented by a Model Artifact, `produced_by` an Analysis in which it was created by training on data represented by a Data Artifact that is one of the `inputs` of the Analysis
- A densitometry standard curve that converts raw western blot band intensity into a reported protein quantity. The `modeling_choices` property records three choices: the loading control, the linear fit's range, and the interpretation of measurements outside the range.

### 2.7 NonGroundable (Artifact)

Not groundable.

Required properties:
 - `groundable` (boolean):false 

**NonGroundable** is the general class for content a Member wishes to clearly mark as non-groundable. 

**Intent:** While NonGroundable has no required properties outside of `groundable`:false, there should be at least one property expressing meaningful content, such as `text`. Users can also create non-groundable Artifacts with arbitrary, intuitive type names and `groundable`:false. 

**Examples**
- work summaries
- surveys
- recommendations
- reviews
- plans
- proposals
- protocols

### 2.8 Message (Artifact)

Not groundable.

Required properties:
 - `recipients` (list of addresses): the Members to which the communication is directed.
 - `text` (string): the content of the communication.
 - `groundable` (boolean):false

The sender is the publishing Member (`published_by`). 

**Message** is a directed communication between Members. Communities may choose to capture requests, responses, and general scientific dialog between Members. For example, one agent might request that another perform a specific Analysis. Messages might refer to Artifacts such as Arguments or Data but the Messages are not evidential.


