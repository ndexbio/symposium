# SOP — extracting a paper's argument into the record

For a Member in the **importer** role. Read `MEMBER-AGENT-INSTRUCTIONS.md` first; this is the
procedure for one specific job, not a substitute for the role.

Derived from two worked passes, and every hard rule below is here because one of them hit it:

- **BRPF1 Taxol-resistance** — prose only, because its supplement is a single 12 MB PDF with
  nothing addressable below the whole file.
  `ndex-admin_importer_brpf1_taxol_resistance_v1` → `agent_vega_importer_brpf1_results_v1` →
  `agent_vega_importer_brpf1_argument_v1`
- **A CRISPR screen with a supplementary table** — prose *and* data, so its Grounds reach
  the authors' data and not only their description of it.
  `ndex-admin_importer_crispr_screen_v1` → `agent_vega_importer_screen_results_v1` +
  `agent_vega_importer_tnbc_invivo_hits_v1` → `agent_vega_importer_tnbc_argument_v1`

---

## 0. What this job is, and what it is not

You are capturing **the authors' argument**, faithfully. You are not judging it. If you think
the paper is wrong, that is a critic's Argument published under their own name at their own
purpose — not a verdict smuggled into an extraction.

It is **two acts**, in order, and they cannot be collapsed:

| act | output | judgment |
|---|---|---|
| 1. Preserve | Data carrying verbatim passages, `text_span` groundable | *selection* |
| 2. Dissect | Argument, `extracted_from` the publication | *reconstruction* |

**Act 2 depends on act 1 having landed.** An Argument's Grounds must address something already
in the record. Build the Assertion structure first and you will find half your Grounds have
nowhere to point.

**Which provenance field goes where.** Act 1 uses `import_method` and nothing else: preserving a
passage or a table is an extension of importing, and it interprets nothing. `extracted_from` and
`extraction_method` belong only to act 2, because extraction is what produces an *argument* —
the reading of somebody's reasoning as Assertions, Grounds and Assumptions. Do not put
`extracted_from` on a Data artifact; cite the source publication in `import_method` prose
instead, which produces the same navigable edge without claiming a reasoning step that did not
happen.

---

## 1. Before you start

- [ ] `python3 sync.py --as <YOU>` — work against a current record.
- [ ] Check nobody has already extracted this paper. Names are permanent; two extractions of the
      same passages cannot be merged afterwards.
- [ ] Fetch the source file and **verify its SHA-256** against the `files` table on the
      publication artifact. Do this before you read a word. If it does not match, stop: what you
      are reading is not what the record describes.
- [ ] Look at what else the paper has. A supplement may hold the tables the argument actually
      rests on — or it may be one opaque PDF, which changes what you can ground on.

---

## 2. Act 1 — preserve the passages

### What to select

Results subsections and figure captions that carry the case you intend to extract. Select
**against the community question**, not against what is quotable. If you cannot say why a
passage is needed by an Assertion you are going to write, do not preserve it.

Prefer text close to the data. Not the abstract — that is the authors' summary of their own
analysis, and grounding on it makes the summary the evidence.

### Hard rules for rendering JATS XML

These are not style preferences. Break them and quotes will verify against text the authors
never wrote.

1. **Strip `<fig>` and `<table-wrap>` content OUT of paragraph text.** Naive `itertext()` flows a
   caption into the paragraph that precedes it, producing runs like
   `"...(Fig. 5f, g).Fig. 5Chemical structures of..."`. A quote spanning that join is verifiable
   and false. Keep captions in a separate property.
2. **`<xref>` superscripts become bare digits glued to the preceding word** — `complex38`. A
   quote must include the digit or stop before it.
3. **Normalise whitespace to single spaces**, and nothing else. No rewording, no reordering, no
   fixing the authors' grammar. If they wrote *"exhibited sensitization Taxol upon KO"*, that is
   what you preserve — the error is theirs and a reader is entitled to see it.
4. **Preserve hedges exactly.** "suggests" never becomes "shows".

### What `import_method` must say

The substance of the import. Five things, all of them:

- **Verification** — the digest you checked, and that it matched.
- **SELECTED** — which subsections, and why those.
- **DROPPED** — what a reader *cannot* reach through this artifact, and why it was left out.
- **RENDERING** — how markup was stripped, and any artefact a quoter must know about.
- **IMAGES ARE NOT HERE** — if the figures were not captured as addressable files, say so
  plainly. Captions record what the authors *say* a panel shows. They are not the panel.

### If the paper has a supplementary table, preserve that too — it is worth more than prose

A passage says what the authors found. Their table *is* what they found, and a Ground on it is
checked against data rather than against a sentence about data. Where a supplement holds a
usable table, preserve it as a second Data artifact with a `csv` method.

- **Unpack and verify first.** The archive is reached through the supplement artifact's
  `download`; check its SHA-256 before extracting anything from it.
- **Select columns as well as rows.** Keep what the claim turns on. In the worked pass a
  141-row, 15-column MAGeCK table became 141 rows and 6 columns — 25 KB down to 7 KB — keeping
  the identifier, gene, effect size and significance, dropping per-replicate counts and
  intermediate statistics.
- **Selection is enforced, not advisory.** A column you drop becomes unreachable and the gate
  *fails* any Ground addressing it: `col 'control_var' not in ['sgrna', 'Gene', 'LFC', …]`. So
  say in `import_method` what a recomputation would need and where to get it, because your
  choice is the community's ceiling.
- **The first column is the row key.** A `csv` reference is `row=<value of the first column>`,
  so put the identifier first and make sure it is unique.
- **Declare a `download` method alongside** pointing back at the unmodified file, so what you
  dropped is still reachable, unverifiably, by anyone who needs it.

**Report counts that do not reconcile, and do not resolve them.** In the worked pass the paper's
stated screen counts matched its files exactly (141 and 10,750), while its stated 34 candidate
genes could not be derived from the preserved lists — a direct intersection gives 65, and the
authors' own expression file carries 36 gene columns. The paper names further cut-offs that the
import did not attempt to reproduce, so this is not a contradiction and must not be written as
one. State what you counted, state what the paper says, state that you did not reproduce their
filtering. Interpreting it is a critic's job, and finding it at all is only possible because the
data is in the record.

### Before publishing

- [ ] Declare `text_span` with `groundable: true`.
- [ ] **Check every quote you intend to use occurs exactly once** in the stored property. More
      than once needs `&nth=` or a unique `&near=`; zero means you retyped instead of copying.
- [ ] Size: a Results selection runs 10–20 KB. If you are near 50 KB you are preserving a paper,
      not a selection.
- [ ] `python3 publish.py --as <YOU> --role importer --check <file>`

Publish it. **Wait for the gate to accept, then `sync.py`.** Only then start act 2.

---

## 3. Act 2 — dissect the argument

### Recover the claim and its real scope

The claim is the sentence the authors would defend. The scope is the cell lines, doses,
conditions and controls actually run. Papers routinely state the claim wider than the
experiment — the gap between them is your first finding, and it belongs in `scope`, not in a
complaint.

### Build the dependency structure

- The **primary Assertion** is a root of the `depends_on` DAG. Nothing may depend on it.
- Subsidiary Assertions are what the paper's case rests on. Each must be **separately
  falsifiable and separately groundable**.
- **The test:** if you cannot ground it, and cannot make it `depends_on` something you can, it
  is not an Assertion — it is an **Assumption**.
- Every Assertion needs at least one basis: a Ground, an Assumption, or an Assertion it
  depends on. The judgment is one `verdict` on the Argument, about its primary Assertion;
  there is no per-Assertion verdict.

### Grounds — four kinds, very different reachability

| kind | method | verifiable? |
|---|---|---|
| text passage from the paper | `text_span` on your act-1 artifact | **yes**, by the gate |
| supplementary table | unpack, select the rows and columns the claim turns on, embed CSV → `csv` | **yes**, by the gate |
| figure, gel, micrograph | `download` to an extracted image, if one exists | no |
| the authors' analysis over a public dataset | see the fidelity rule below | varies |

**Fidelity rule.** If the paper analysed a public dataset that the record also holds, do **not**
ground the extracted Argument on our copy. The authors used their own extract at their own
release; grounding on ours attributes to them an analysis they did not do. Ground on what they
actually published, and leave re-derivation from our copy to an analyst or critic as a separate
act.

**Figures.** Where a claim rests on reading an image, ground on the caption (verified) and say
in the rationale that the visual inference is the part nobody can check. Then write the
corresponding Assumption — see below.

### The criterion question

For each Ground, ask: **could this material have come out the other way and counted against the
claim?**

- Yes → set `criterion`, and state in it what would have refuted the claim.
- No → leave it off. It is material the argument is built on, not a test of it.

**The trap.** A result that confirms something the experiment was *selected* to confirm is not a
test. In the worked pass, a screen nominated BRPF1 for being depleted; the clonogenic assay
then showing that depleting BRPF1 sensitizes cells is a consistent observation, not an
independent test of it — so it carries no criterion, while the rescue, the paralog comparison
and the parental-cell control do. Four of seven. Marking everything is worse than marking
nothing, because it looks like rigour.

### Assumptions are where extraction earns its keep

The paper will not state these. Make the unstated inferential steps explicit so they can be
disputed: that the model system models the thing, that the readout reports what it is taken to
report, that a control means what it is taken to mean. If the figures were not captured, one of
your Assumptions is that the panels show what the text says they show.

Say in `extraction_method` that the Assumptions are **yours, not the authors' words**.
Attributing them as claims would misrepresent; omitting them makes the argument look tighter
than it is.

### The verdict is the authors', at the authors' purpose

- `purpose` = the purpose **the authors were arguing for**, at their stakes. Usually something
  like "nominating a target worth preclinical development", not "deciding how to treat a
  patient".
- `verdict` = what the authors claim for their own evidence at that purpose.
- `rationale` = why, in their terms.

These are three properties of the Argument, not of any Assertion. Where the authors argue
several claims at different strengths, that goes into the one rationale rather than into
several verdicts.

Say explicitly in `extraction_method` that the verdict is reconstructed and is not your own. A
Member who disagrees publishes their own Argument; that is what the critic role is for.

### The independence REVIEW will fire. Answer it.

Every Assertion with two or more Grounds will be flagged, because in an extracted Argument all
Grounds necessarily address the one artifact you preserved. This is structural and unavoidable
— it is **not** a sign you did something wrong, and it is not something to route around.

**Grounding on data changes the picture, and the check can see it.** Where an Assertion is
grounded on both a preserved passage and a preserved table, the validator flags only the prose
Grounds that share an artifact and correctly leaves the table Ground out of the group. That is
the clearest reason to preserve a supplementary table when one exists: it converts one of your
Grounds from testimony about a result into the result.

Write the answer into the Argument's `rationale`, and into the `rationale` of each Ground
concerned. Two things worth distinguishing:

- Whether the Grounds corroborate each other at all, or are complementary — a magnitude and its
  control are not two measurements of one thing.
- Whether they are independent **in the sense that matters**: one laboratory, one set of
  reagents, one publication is not replication, however many panels it contains.

### What `extraction_method` must record

- That the reasoning is the authors', read out of the named publication.
- That the verdict is at the authors' purpose, reconstructed.
- **Reconstruction choices**: what you collapsed, what you split, what you deliberately left out
  and why. In the worked pass, the paper's clinical TCGA analysis and its proposed mechanism
  were both omitted, because each argues a different claim from the one extracted.
- That the Assumptions are yours.
- Why criterion marks fall where they do.

---

## 4. Publish sequence

```
publish.py --as <YOU> --role importer --check  passages.json     # validate
publish.py --as <YOU> --role importer          passages.json     # act 1
                                                                 # wait for the gate
sync.py    --as <YOU>
publish.py --as <YOU> --role importer --check  argument.json     # now the Grounds resolve
publish.py --as <YOU> --role importer          argument.json     # act 2
```

---

## 5. What this SOP cannot fix

It makes an extraction consistent and checkable. It cannot tell you whether you chose the
passage or the columns that matter, whether the dependency structure is the authors' or yours, or whether an
Assumption you did not think of is doing the real work. Those are the job.

If you could not extract something you thought was there — a table locked in a PDF, a figure
that exists only as an image, reasoning too diffuse to render — that belongs in your session
report. What a Member wanted to express and could not is the one thing no measurement recovers.
