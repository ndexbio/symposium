"""Page templates for the Symposium browser: layout, interaction, detail panel, legend.

What the presentation commits to, and why:

  * A Ground sits directly on an Assertion, so the "full graph" is three layers and
    little is folded away.
  * Grounding kind is not an enum. A Ground either carries a `criterion` — the author
    claiming the material as a test that could have counted against the claim — or it
    does not. The renderer keys off its presence, because that is the only thing the
    record says structurally about what a Ground is doing.
  * Assumption is an Object in its own right, and it is exactly the weak joint a reader
    is looking for, so it is never folded away.
  * There is no verdict vocabulary: one free-text verdict per Argument, shown in the page
    header rather than encoded on Assertion nodes.
  * A cross-artifact citation is a markdown link in prose, so the markdown-lite renderer
    permits exactly one link form and no other markup.
  * Validator findings — independence, unverifiable grounding, bare citations — are
    rendered on the page rather than recomputed, so the page and the gate cannot disagree.
"""

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #f6f7f9; --panel: #ffffff; --ink: #1a1f2b; --muted: #6b7280;
    --line: #d9dee6; --accent: #2563eb;
    --assertion: #2563eb; --assessment: #7c3aed; --ground: #0d9488; --assumption: #d97706;
    --external: #9ca3af;
    --g-test: #16a34a; --g-accept: #d97706; --requires: #dc2626;
    --assesses: #7c3aed; --contains: #94a3b8; --bears: #0d9488; --derived: #db2777;
    /* There is no verdict vocabulary, so no verdict palette: the judgment is
       free text on the Argument and is read, not colour-coded. */
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: var(--ink); background: var(--bg); }}
  header {{ padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }}
  header h1 {{ font-size: 15px; margin: 0 0 2px; font-weight: 650; }}
  header .sub {{ font-size: 12px; color: var(--muted); }}
  header .sub .genre {{ color: var(--ink); font-weight: 600; }}
  #app {{ display: flex; height: calc(100% - 52px); }}
  body.has-intro #app {{ height: calc(100% - 52px - var(--introh, 60px)); }}
  #graphwrap {{ position: relative; flex: 1 1 62%; min-width: 0; }}
  #cy {{ position: absolute; inset: 0; }}
  #side {{ flex: 0 0 38%; max-width: 460px; border-left: 1px solid var(--line); background: var(--panel); display: flex; flex-direction: column; }}
  #legend {{ padding: 10px 14px; border-bottom: 1px solid var(--line); font-size: 11px; }}
  #legend b {{ display:block; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 6px 0 4px; }}
  .lg {{ display: inline-flex; align-items: center; gap: 5px; margin: 0 10px 4px 0; }}
  .sw {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
  .swl {{ width: 20px; height: 0; border-top-width: 3px; border-top-style: solid; display: inline-block; }}
  #detail {{ flex: 1; overflow: auto; padding: 12px 14px; font-size: 13px; }}
  #detail .placeholder {{ color: var(--muted); font-style: italic; }}
  #detail h2 {{ font-size: 13px; margin: 0 0 2px; }}
  #detail .pill {{ display:inline-block; font-size: 11px; padding: 1px 7px; border-radius: 10px; color:#fff; margin-bottom: 8px; }}
  #detail dl {{ margin: 0; }}
  #detail dt {{ font-weight: 650; font-size: 11px; text-transform: uppercase; letter-spacing:.03em; color: var(--muted); margin-top: 10px; }}
  #detail dd {{ margin: 2px 0 0; word-break: break-word; line-height: 1.4; }}
  #detail ul {{ margin: 4px 0 0; padding-left: 18px; }}
  #detail li {{ margin: 3px 0; }}
  /* markdown-lite blocks inside a field: tight paragraph/list spacing */
  #detail dd p {{ margin: 0 0 6px; }}
  #detail dd p:last-child {{ margin-bottom: 0; }}
  #detail dd ul.md, #detail dd ol.md {{ margin: 4px 0 6px; padding-left: 20px; }}
  #detail dd ul.md:last-child, #detail dd ol.md:last-child {{ margin-bottom: 0; }}
  #detail dd li {{ margin: 2px 0; }}
  #detail .edgelist dd p {{ display: inline; }}
  /* single-paragraph markdown inline after a "criterion:"/"rationale:" label */
  #detail ul.edgelist li > p:only-of-type {{ display: inline; margin: 0; }}
  #detail ul.edgelist li p {{ margin: 4px 0 0; }}
  #detail ul.edgelist li ul.md, #detail ul.edgelist li ol.md {{ margin: 2px 0; }}
  code {{ background:#eef1f5; padding: 1px 4px; border-radius: 4px; font-size: 12px; }}
  /* The Argument's single judgment, stated once at the top of the page. */
  #verdictpanel {{ background: var(--panel); border: 1px solid var(--line);
    border-left: 4px solid var(--accent); border-radius: 6px;
    padding: 10px 14px; margin: 0 0 10px; }}
  #verdictpanel .vlabel {{ font-size: 10px; letter-spacing: .08em; text-transform: uppercase;
    color: var(--muted); font-weight: 700; }}
  #verdictpanel .vtext {{ font-size: 14px; font-weight: 600; margin: 2px 0 6px; }}
  #verdictpanel dl {{ margin: 0; }}
  #verdictpanel dt {{ font-size: 10px; letter-spacing: .06em; text-transform: uppercase;
    color: var(--muted); font-weight: 700; margin-top: 6px; }}
  #verdictpanel dd {{ margin: 2px 0 0; font-size: 12.5px; line-height: 1.5; white-space: pre-wrap; }}
  /* claim sections in the detail panel */
  #detail .section {{ margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--line); }}
  #detail .section:first-of-type {{ border-top: none; margin-top: 6px; padding-top: 0; }}
  #detail .sechd {{ font-size: 10px; text-transform: uppercase; letter-spacing:.06em; font-weight: 700; color: var(--muted); margin-bottom: 4px; }}
  #detail .verdict {{ display:inline-block; font-size:11px; font-weight:700; padding:2px 8px; border-radius:10px; color:#fff; margin: 2px 0 4px; }}
  #detail .asmt-card {{ margin-top: 8px; padding-left: 10px; border-left: 3px solid var(--line); }}
  #detail .asmt-card + .asmt-card {{ margin-top: 12px; }}
  #detail ul.edgelist {{ list-style: none; padding-left: 0; margin: 4px 0 0; }}
  #detail ul.edgelist li {{ margin: 8px 0; padding-left: 10px; border-left: 2px solid var(--line); line-height: 1.4; }}
  .etag {{ display:inline-block; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 8px; color:#fff; vertical-align: middle; }}
  .etag.test {{ background:#16a34a; }} .etag.evidential {{ background:#64748b; }}
  .etag.testimony {{ background:#7c3aed; }} .etag.alt {{ background:#4338ca; }}
  .etag.unverified {{ background:#b45309; }}
  .finding {{ margin-top:6px; padding:6px 9px; border-radius:6px; font-size:12px; line-height:1.35;
             background:#fff7ed; border-left:3px solid #d97706; color:#7c2d12; }}
  .finding.fail {{ background:#fef2f2; border-left-color:#dc2626; color:#7f1d1d; }}
  #detail a {{ color: var(--accent); }}
  /* a prose citation whose target has no page in this build: shown, not linked */
  .cite-dead {{ border-bottom: 1px dotted var(--muted); color: var(--muted); cursor: help; }}
  .tip {{ position: absolute; pointer-events: none; background: #111827; color: #f9fafb; font-size: 12px;
         padding: 6px 9px; border-radius: 6px; max-width: 320px; line-height: 1.35; z-index: 20;
         box-shadow: 0 4px 14px rgba(0,0,0,.25); opacity: 0; transition: opacity .08s; }}
  .hint {{ font-size: 11px; color: var(--muted); }}
  .mbadge {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:4px; vertical-align:middle; border:1px solid rgba(0,0,0,.15); }}
  .uplink {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  .uplink:hover {{ text-decoration: underline; }}
  .navbtn {{ display:inline-flex; align-items:center; gap:5px; margin: 8px 0 2px; padding: 5px 11px;
            font-size: 12px; font-weight: 600; border:1px solid var(--accent); color:#fff;
            background: var(--accent); border-radius: 6px; cursor: pointer; }}
  .navbtn:hover {{ filter: brightness(1.08); }}
  .owner-line {{ font-size: 11px; color: var(--muted); margin: 4px 0 2px; }}
  .ext-tag {{ display:inline-block; font-size:10px; font-weight:700; padding:1px 6px; border-radius:8px;
             background:#eef1f5; color:#475569; margin-left:6px; vertical-align:middle; }}
  .toolbar {{ position:absolute; top:8px; left:8px; z-index:10; display:flex; gap:6px; align-items:center; }}
  .toolbar button {{ font-size:12px; padding:4px 9px; border:1px solid var(--line); background:#fff; border-radius:6px; cursor:pointer; }}
  .toolbar button:hover {{ background:#eef1f5; }}
  .toolbar button.active {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
  .toolbar .flowkey {{ font-size:11px; color:var(--muted); margin-left:6px; user-select:none; }}
  .toolbar .flowkey b {{ color:var(--ink); }}
  /* The Argument's own framing prose. It carries the author's citations, and a
     citation is the one place nuance goes into prose rather than into vocabulary —
     so it has to be readable and its links have to work. */
  #intro {{ padding:8px 16px; background:#fbfcfd; border-bottom:1px solid var(--line);
            font-size:13px; line-height:1.5; max-height:96px; overflow-y:auto; }}
  #intro p {{ margin:0 0 6px; }} #intro p:last-child {{ margin-bottom:0; }}
  #intro a {{ color:var(--accent); }}
  #intro .cite-dead {{ border-bottom:1px dotted var(--muted); color:var(--muted); cursor:help; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="sub">{arg_label} <code>{review_id}</code> &middot; <span class="mbadge" style="background:{member_color}"></span><b>{member}</b> &middot; {created}{genre_html} &middot; <a href="index.html" class="uplink">&uarr; community overview</a> &middot; <span class="hint">reading runs left &rarr; right into the claim being made &middot; hover = brief &middot; click = full detail &middot; dashed border = has a page of its own</span></div>
</header>
{intro_html}
<div id="app">
  <div id="graphwrap">
    <div class="toolbar">
      <button id="btn-fit">Fit</button>
      <button id="btn-export">Export PNG</button>
      <button id="btn-hide">Hide node</button>
      <button id="btn-showall">Show all</button>
      <button id="btn-claim" class="active">Claim map</button>
      <button id="btn-full">Full graph</button>
      <button id="btn-force">Force (cose)</button>
      <span class="flowkey" id="claimkey">evidence, sub-claims &amp; assumptions <b>&larr;</b> &nbsp;ground / depend / assume into&nbsp; <b>&rarr;</b> primary assertion</span>
      <span class="flowkey" id="fullkey" style="display:none">every Object as authored: addressed content <b>&larr;</b> Ground &middot; Assumption <b>&rarr;</b> Assertion</span>
    </div>
    <div id="cy"></div>
    <div id="tip" class="tip"></div>
  </div>
  <div id="side">
    <div id="legend"></div>
    <div id="detail"><p class="placeholder">Click an <b>assertion</b> for its claim and everything it rests on. Click an <b>assumption</b> for what is being granted and why. Click a <b>grounding</b> edge for its rationale and, where the author claimed a test, the criterion that could have refuted it.</p></div>
  </div>
</div>

<script src="{cyto_src}"></script>
<script id="graph-data" type="application/json">{graph_json}</script>
<script>
(function () {{
  var DATA = JSON.parse(document.getElementById('graph-data').textContent);

  var NODE_COLORS = {{
    Assertion: '#2563eb', Source: '#64748b',
    Ground: '#0d9488', Assumption: '#d97706', External: '#9ca3af'
  }};

  // The COLLAPSED view = Assertions + what they rest on. The uncollapsed graph (every
  // Object as authored) lives in DATA.meta.full_elements, shown by the "Full graph" mode.
  var COLLAPSED = DATA.elements;
  var FULL = (DATA.meta && DATA.meta.full_elements) || {{ nodes: [], edges: [] }};

  // Three complementary modes (defined BEFORE cy so the constructor sees the right one).
  //
  // Default = "Claim map": the dependency backbone (`requires` + `accepts`) among
  // claims is the primary axis. The culminating claim sits on the RIGHT; sub-claims
  // and Sources cascade LEFT. Positions are precomputed (data._pos_claim), handed to
  // Cytoscape as a deterministic `preset` — draggable, no runtime layout dependency.
  //
  // "Full graph": every Object as authored (Assertion / Ground / Assumption
  // + addressed content), for a reader who wants the uncollapsed structure. Only the
  // Ground hop is folded. Its own element set + layered layout (data._pos_full).
  //
  // "Force (cose)": force-directed alternative over the collapsed set. Nodes stay
  // draggable after any layout.
  var _layoutMode = 'claim';
  function layoutOpts() {{
    if (_layoutMode === 'claim') {{
      return {{ name: 'preset', padding: 40, fit: true,
        positions: function (n) {{ return n.data('_pos_claim'); }} }};
    }}
    if (_layoutMode === 'full') {{
      return {{ name: 'preset', padding: 40, fit: true,
        positions: function (n) {{ return n.data('_pos_full'); }} }};
    }}
    return {{
      name: 'cose', padding: 30, animate: false,
      nodeDimensionsIncludeLabels: true,
      idealEdgeLength: function () {{ return 90; }},
      nodeRepulsion: function () {{ return 12000; }},
      edgeElasticity: function () {{ return 60; }},
      gravity: 0.3, numIter: 1500, componentSpacing: 120,
      randomize: true
    }};
  }}

  var cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: DATA.elements,
    wheelSensitivity: 0.2,
    style: [
      {{ selector: 'node', style: {{
          'label': 'data(label)', 'font-size': 9, 'color': '#111827',
          'text-wrap': 'wrap', 'text-max-width': 110, 'text-valign': 'bottom',
          'text-margin-y': 3, 'width': 22, 'height': 22,
          'border-width': 1, 'border-color': 'rgba(0,0,0,0.25)'
      }} }},
      // Assertion = the claim node. It is the PRIMARY backbone,
      // so it is the largest/boldest. A colored border encodes the folded verdict.
      {{ selector: 'node[ntype="Assertion"]', style: {{
          'shape': 'round-rectangle', 'background-color': 'data(owner_color)',
          'width': 46, 'height': 30, 'font-weight': 600, 'font-size': 10,
          'text-max-width': 150, 'border-width': 4, 'border-color': '#9ca3af' }} }},
      // A claim that lives in ANOTHER artifact (cross-artifact assess / accept):
      // faded owner-colored fill so it reads as "not authored here".
      {{ selector: 'node[ntype="Assertion"][?external]', style: {{
          'background-opacity': 0.32 }} }},
      // A node whose target compiles to its own page: dashed border = clickable to
      // navigate there. (External evidence with no page stays solid, not dashed.)
      {{ selector: 'node[?navigable]', style: {{ 'border-style': 'dashed' }} }},
      // No per-claim verdict encoding: one judgment covers the Argument and
      // is stated in the header. Colouring claims here would imply the author
      // judged each one separately, which the record no longer says.
      // Source = an evidence element (a figure panel, excerpt, or object). Kept
      // lighter / subordinate to claims: a small slate cut-rectangle, its intuitive
      // name (e.g. "Fig 1C") drawn beside it.
      {{ selector: 'node[ntype="Source"]', style: {{
          'shape': 'cut-rectangle', 'background-color': '#e2e8f0', 'background-opacity': 0.95,
          'border-color': '#94a3b8', 'border-style': 'solid', 'border-width': 1.2,
          'color': '#475569', 'width': 30, 'height': 18, 'font-size': 8,
          'text-max-width': 120 }} }},
      // Content the author could NOT address, and asks the community to grant. It is
      // shown in BOTH modes and never folded: an Assumption is the joint a reader is
      // looking for, and hiding it to tidy the picture would defeat the whole exercise.
      {{ selector: 'node[ntype="Assumption"]', style: {{
          'shape': 'vee', 'background-color': '#d97706', 'background-opacity': 0.85,
          'border-color': '#b45309', 'border-width': 1.5,
          'width': 24, 'height': 22, 'font-size': 8, 'color': '#7c2d12',
          'text-max-width': 130 }} }},
      // (Full-graph mode) the Ground gets its own encoding.
      {{ selector: 'node[ntype="Ground"]', style: {{
          'shape': 'ellipse', 'background-color': '#0d9488', 'width': 14, 'height': 14,
          'background-opacity': 0.8, 'font-size': 7, 'color': '#6b7280' }} }},
      // An Assertion in ANOTHER Argument, reached by a Ground address: grounding on a
      // peer's conclusion is testimony, and it should not look like a measurement.
      {{ selector: 'node[ntype="External"]', style: {{
          'shape': 'round-rectangle', 'background-color': '#e5e7eb', 'background-opacity': 0.9,
          'border-color': '#9ca3af', 'border-style': 'dashed', 'border-width': 1.5,
          'color': '#4b5563', 'width': 40, 'height': 26, 'text-max-width': 140 }} }},
      // Addressed content the gate could not machine-verify (a `rest` or `download`
      // method): the exact point where verification becomes trust, marked as such.
      {{ selector: 'node[?unverifiable]', style: {{
          'border-color': '#b45309', 'border-width': 2.5, 'border-style': 'dotted' }} }},

      {{ selector: 'edge', style: {{
          'width': 1.4, 'curve-style': 'bezier', 'line-color': '#94a3b8',
          'target-arrow-color': '#94a3b8', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.8,
          'font-size': 7, 'color': '#6b7280', 'text-rotation': 'autorotate' }} }},
      // (Full-graph mode) the Ground hop that the claim map folds away.
      {{ selector: 'edge[rel="addresses"]', style: {{
          'line-color': '#0d9488', 'target-arrow-color': '#0d9488', 'line-style': 'dashed' }} }},
      // `depends_on` is the claim-map BACKBONE: bold red, prominent.
      {{ selector: 'edge[rel="depends_on"]', style: {{
          'line-color': '#dc2626', 'target-arrow-color': '#dc2626', 'width': 2.6,
          'target-arrow-shape': 'triangle-tee', 'arrow-scale': 1.0 }} }},
      // `assumes`: the claim rests on something the author could not address.
      {{ selector: 'edge[rel="assumes"]', style: {{
          'line-color': '#d97706', 'target-arrow-color': '#d97706', 'width': 2,
          'line-style': 'dotted', 'target-arrow-shape': 'diamond', 'arrow-scale': 0.9 }} }},
      // a prose citation (markdown link) — reference, never evidence.
      {{ selector: 'edge[rel="cites"]', style: {{
          'line-color': '#a3a3a3', 'target-arrow-color': '#a3a3a3', 'line-style': 'dotted' }} }},
      // Per-mode de-emphasis: whichever edges are NOT the current mode's organizing
      // structure get dimmed so they don't fight the reading. Applied generically to
      // any edge tagged .nonflow-dim (the JS decides which rels get tagged per mode).
      // Hover/click still highlights a dimmed edge at full strength.
      {{ selector: 'edge.nonflow-dim', style: {{ 'opacity': 0.14, 'width': 1 }} }},
      // Grounding, split by the ONE thing the record says structurally about it: whether the
      // author claimed the material as a TEST (a `criterion` — it could have counted
      // against the claim and did not) or offered it as material they build on.
      {{ selector: 'edge[rel="grounded_by"][kind="test"]', style: {{
          'line-color': '#16a34a', 'target-arrow-color': '#16a34a', 'width': 2,
          'label': 'test', 'target-arrow-shape': 'triangle' }} }},
      {{ selector: 'edge[rel="grounded_by"][kind="evidential"]', style: {{
          'line-color': '#64748b', 'target-arrow-color': '#64748b', 'line-style': 'dashed',
          'target-arrow-shape': 'circle' }} }},
      // grounding on another Argument's Assertion: testimony, not measurement.
      {{ selector: 'edge[rel="grounded_by"][?testimony]', style: {{
          'line-color': '#7c3aed', 'target-arrow-color': '#7c3aed',
          'label': 'testimony', 'line-style': 'dashed' }} }},

      {{ selector: '.faded', style: {{ 'opacity': 0.15 }} }},
      {{ selector: '.hi', style: {{ 'border-width': 3, 'border-color': '#111827' }} }},
      // a highlighted edge wins over the flow-mode dimming (listed last)
      {{ selector: 'edge.hi', style: {{ 'width': 3.2, 'opacity': 1 }} }}
    ],
    layout: layoutOpts()
  }});

  // ---- tooltips (hover) ----
  var tip = document.getElementById('tip');
  function showTip(evt, text) {{
    tip.textContent = text; tip.style.opacity = 1;
    var rp = evt.renderedPosition || evt.position;
    tip.style.left = (rp.x + 14) + 'px';
    tip.style.top  = (rp.y + 10) + 'px';
  }}
  function hideTip() {{ tip.style.opacity = 0; }}
  cy.on('mouseover', 'node,edge', function (e) {{ showTip(e, e.target.data('tooltip') || ''); }});
  cy.on('mousemove', 'node,edge', function (e) {{ if (tip.style.opacity == 1) showTip(e, tip.textContent); }});
  cy.on('mouseout', 'node,edge', hideTip);
  cy.on('drag pan zoom', hideTip);

  // ---- detail panel (click) ----
  var detail = document.getElementById('detail');
  function esc(s) {{ return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

  // authorship line + cross-artifact "Go to" button (shared by all detail renderers)
  function ownerLine(data) {{
    if (!data || !data.owner) return '';
    var col = data.owner_color || '#9ca3af';
    return '<div class="owner-line">produced by <span class="mbadge" style="background:'
      + col + '"></span><b>' + esc(data.owner) + '</b></div>';
  }}
  function navBtn(d) {{
    if (!d || !d.nav_file) return '';
    var art = String(d.nav_file).replace(/-v1\.html$/, '');
    return '<button class="navbtn" data-file="' + esc(d.nav_file) + '" data-frag="'
      + esc(d.nav_frag || '') + '">Go to ' + esc(art) + ' ↗</button>';
  }}

  // ---- Markdown-lite (CLICK PANEL ONLY) ----------------------------------
  // A minimal, dependency-free, XSS-safe renderer for authored prose fields
  // (evaluation / rationale / advisory_notes / purpose / claim_text / scope /
  // criterion). Supported subset ONLY: blank-line paragraphs, bullet lists
  // (- / *), numbered lists (1.), **bold**, *italic*, `inline code`.
  //
  // SAFETY: we ESCAPE HTML FIRST (esc()), then apply formatting to the escaped
  // text. No raw HTML from the data ever reaches innerHTML: a literal "<script>"
  // in the source becomes "&lt;script&gt;" before any markup runs, and inline
  // markup is added only via our own fixed tags. No links, images, or raw HTML.
  //
  // Plain prose (today's evaluations: one block, or \n / \n\n separated) renders
  // cleanly — blank lines become <p> breaks, a single block stays one <p>.
  // Scientific notation (p<0.05), arrows (→), %, gene names etc. pass through
  // untouched: esc() only rewrites & < >, and the inline rules key off * ` only.
  // Address -> page filename, for turning a prose citation into live navigation.
  // Supplied by the compiler; an address whose artifact has no page renders as
  // styled text rather than a dead link.
  var ADDR_PAGES = (DATA.meta && DATA.meta.addr_pages) || {{}};

  function mdInline(escaped) {{
    // `code` first so * and _ inside code are not treated as emphasis.
    escaped = escaped.replace(/`([^`]+)`/g, function (_, c) {{ return '<code>' + c + '</code>'; }});
    // ---- the ONE link form this renderer permits (profile 3.1) -----------------
    // A prose citation is an address inside a markdown link, which is what keeps a
    // record navigable rather than merely stored — so exactly [text](@address) and
    // [text](<@address with spaces>) are
    // rendered, and nothing else. The href is NOT taken from the document: the
    // address is looked up in a compiler-supplied table, so an arbitrary URL in
    // the source cannot become a live link, and javascript: can never appear.
    escaped = escaped.replace(
      /\[([^\]]+)\]\(\s*(?:&lt;(@[^&]+?)&gt;|(@[^)\s]+))\s*\)/g,
      function (_, text, bracketed, bare) {{
        var addr = bracketed || bare;
        var a = addr.replace(/^@/, '');
        var root = a.split(/[.#]/)[0];
        var page = ADDR_PAGES[root];
        if (!page) return '<span class="cite-dead" title="' + addr + '">' + text + '</span>';
        // The fragment must survive verbatim: artifact-page anchors are literally
        // `csv.row=X&col=Y`, so percent-encoding the = and & would miss the cell.
        var frag = a.indexOf('#') > -1 ? a.split('#')[1]
                 : (a.indexOf('.') > -1 ? a.slice(a.indexOf('.') + 1) : '');
        return '<a href="' + page + (frag ? '#' + frag.replace(/ /g, '%20') : '')
             + '" title="' + addr + '">' + text + '</a>';
      }});
    // **bold** (greedy-safe, non-empty, no spanning across the delimiters' content start/end)
    escaped = escaped.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
    // *italic* — single asterisks not adjacent to another * (bold already consumed)
    escaped = escaped.replace(/\*([^*\n]+?)\*/g, '<em>$1</em>');
    return escaped;
  }}
  function mdlite(text) {{
    var src = String(text == null ? '' : text);
    // normalize CRLF, split into blocks on blank lines
    var blocks = src.replace(/\r\n?/g, '\n').split(/\n\s*\n/);
    var out = [];
    blocks.forEach(function (block) {{
      var lines = block.split('\n');
      // is this block a list? (every non-blank line starts with a marker)
      var nonblank = lines.filter(function (l) {{ return l.trim() !== ''; }});
      if (nonblank.length === 0) return;
      var allBullet = nonblank.every(function (l) {{ return /^\s*[-*]\s+/.test(l); }});
      var allNumber = nonblank.every(function (l) {{ return /^\s*\d+\.\s+/.test(l); }});
      if (allBullet || allNumber) {{
        var tag = allNumber ? 'ol' : 'ul';
        var items = nonblank.map(function (l) {{
          var item = l.replace(/^\s*(?:[-*]|\d+\.)\s+/, '');
          return '<li>' + mdInline(esc(item)) + '</li>';
        }});
        out.push('<' + tag + ' class="md">' + items.join('') + '</' + tag + '>');
      }} else {{
        // a plain paragraph: join wrapped lines with <br> to preserve single \n
        var html = nonblank.map(function (l) {{ return mdInline(esc(l)); }}).join('<br>');
        out.push('<p>' + html + '</p>');
      }}
    }});
    return out.join('') || '<p></p>';
  }}

  // Detail for a COLLAPSED claim node. A claim carries no judgment of its
  // own: the Argument's single verdict is in the page header, not here.
  function renderClaim(data) {{
    var full = data.full || {{}};
    var html = '<h2>Claim' + (data.external ? '<span class="ext-tag">external ↗</span>' : '') + '</h2>';
    var pillText = data.external ? (data.nav_frag || data.id) : data.id;
    html += '<span class="pill" style="background:' + (data.owner_color || '#2563eb') + '">' + esc(pillText) + '</span>';
    html += ownerLine(data);
    html += navBtn(data);
    // --- claim section (top) ---
    html += '<div class="section"><div class="sechd">Claim</div><dl>';
    ['claim','scope'].forEach(function (k) {{
      if (k in full && full[k] != null && full[k] !== '')
        html += '<dt>' + esc(k) + '</dt><dd>' + fmt(full[k]) + '</dd>';
    }});
    html += '</dl></div>';
    // --- Grounds (spec 2.2.4) -------------------------------------------------
    // Ordered test-first. The `criterion` is what makes a Ground a test rather than
    // material the author builds on, so it is shown before the rationale: it is the
    // strongest thing an author can assert here and the easiest to assert falsely.
    var grd = data.groundings || [];
    if (grd.length) {{
      var nTest = grd.filter(function (g) {{ return g.kind === 'test'; }}).length;
      html += '<div class="section"><div class="sechd">Grounded on ' + grd.length
            + ' &middot; ' + nTest + ' as a test</div><ul class="edgelist">';
      grd.forEach(function (g) {{
        html += '<li><b>' + esc(g.source) + '</b>'
              + ' <span class="etag ' + (g.kind === 'test' ? 'test">test' : 'evidential">evidential')
              + '</span>';
        if (g.testimony) html += ' <span class="etag testimony">testimony</span>';
        if (g.unverifiable) html += ' <span class="etag unverified">unverified</span>';
        if (g.criterion)
          html += '<br><span class="hint">would have counted against:</span> ' + fmt(g.criterion);
        if (g.rationale) html += '<br><span class="hint">rationale:</span> ' + fmt(g.rationale);
        if (g.address) html += '<br><code>' + esc(g.address) + '</code>';
        html += '</li>';
      }});
      html += '</ul></div>';
    }}
    // --- Assumptions ------------------------------------------------------------
    // Never folded, never abbreviated. This is the part of an argument that a reader
    // is entitled to refuse, and burying it is how arguments become unfalsifiable.
    var asm = data.assumptions || [];
    if (asm.length) {{
      html += '<div class="section"><div class="sechd">Rests on ' + asm.length
            + ' assumption' + (asm.length > 1 ? 's' : '') + '</div><ul class="edgelist">';
      asm.forEach(function (u) {{
        html += '<li style="border-left-color:#d97706">' + fmt(u.rationale || '(no rationale)') + '</li>';
      }});
      html += '</ul></div>';
    }}
    // --- alternatives -----------------------------------------------------------
    var alt = data.alternatives || [];
    if (alt.length) {{
      html += '<div class="section"><div class="sechd">Named alternative'
            + (alt.length > 1 ? 's' : '') + '</div><ul class="edgelist">';
      alt.forEach(function (a) {{
        html += '<li><span class="etag alt">alternative</span> ' + esc(a.claim || a.id) + '</li>';
      }});
      html += '</ul></div>';
    }}
    // --- what the validator saw -------------------------------------------------
    var fnd = data.findings || [];
    if (fnd.length) {{
      html += '<div class="section"><div class="sechd">Noted by the checker</div>';
      fnd.forEach(function (f) {{
        html += '<div class="finding' + (f.level === 'FAIL' ? ' fail' : '') + '"><b>'
              + esc(f.check) + '</b> — ' + esc(f.msg) + '</div>';
      }});
      html += '</div>';
    }}
    html += '</div>';
    detail.innerHTML = html;
  }}

  function claimLabelFor(id) {{
    var n = cy.getElementById(id);
    if (n && n.length) {{
      var f = n.data('full') || {{}};
      return f.claim ? (id + ' — ' + f.claim) : id;
    }}
    return id;
  }}

  // Detail for a GROUNDING edge — the folded Ground Object, shown whole.
  function renderGroundingEdge(data) {{
    var full = data.full || {{}};
    var srcName = (cy.getElementById(data.target).data('name')) || data.target;
    var isTest = (data.kind === 'test');
    var html = '<h2>Ground</h2>';
    html += '<span class="pill" style="background:' + (isTest ? '#16a34a' : '#64748b') + '">'
          + (isTest ? 'test' : 'evidential') + '</span>';
    if (data.testimony) html += ' <span class="etag testimony">testimony</span>';
    if (data.unverifiable) html += ' <span class="etag unverified">unverified</span>';
    html += '<div class="section"><dl>';
    html += '<dt>bears on</dt><dd>' + esc(claimLabelFor(data.source)) + '</dd>';
    html += '<dt>addresses</dt><dd><b>' + esc(srcName) + '</b>'
          + (full.address ? '<br><code>' + esc(full.address) + '</code>' : '') + '</dd>';
    if (full.criterion) {{
      html += '<dt>criterion — what would have counted against the claim</dt><dd>'
            + fmt(full.criterion) + '</dd>';
    }} else {{
      html += '<dt>no criterion</dt><dd class="hint">Offered as material the author builds '
            + 'on, not as a test the claim survived.</dd>';
    }}
    if (full.rationale) html += '<dt>rationale</dt><dd>' + fmt(full.rationale) + '</dd>';
    if (data.testimony) {{
      html += '<dt></dt><dd class="hint">Grounding on another Argument\'s Assertion takes that '
            + 'author\'s conclusion as evidential testimony.</dd>';
    }}
    if (data.unverifiable) {{
      html += '<dt></dt><dd class="hint">The gate could not machine-verify this reference — the '
            + 'addressing method reaches content held outside the record. This is exactly where '
            + 'verification becomes trust.</dd>';
    }}
    html += '</dl></div>';
    detail.innerHTML = html;
  }}

  function renderDetail(kind, data) {{
    if (kind === 'node' && data.ntype === 'Assertion') {{ renderClaim(data); return; }}
    if (kind === 'edge' && data.rel === 'grounded_by') {{ renderGroundingEdge(data); return; }}
    var full = data.full || {{}};
    var color = kind === 'edge' ? '#334155' : (NODE_COLORS[data.ntype] || '#334155');
    var heading = kind === 'edge' ? ('Edge: ' + esc(data.rel))
                 : (data.ntype === 'Source' ? 'Source (evidence)' : esc(data.ntype));
    var html = '<h2>' + heading + '</h2>';
    if (kind === 'node') {{
      var pillText = data.ntype === 'Source' ? (data.name || data.id) : data.id;
      html += '<span class="pill" style="background:' + color + '">' + esc(pillText) + '</span>';
      html += ownerLine(data);
      html += navBtn(data);
    }}
    html += '<dl>';
    var order = {{
      Assertion: ['claim','scope'],
      Source: ['name','address','artifact','property','method','reference','description'],
      Assumption: ['rationale'],
      Ground: ['address','criterion','rationale'],
      grounded_by: ['kind','criterion','rationale','target'],
      edge: ['rel','source','target','kind','criterion','rationale']
    }};
    var pref = kind === 'edge' ? (order[full.rel] || order.edge) : (order[data.ntype] || []);
    var seen = {{}};
    function emit(key) {{
      if (!(key in full) || seen[key]) return; seen[key] = 1;
      html += '<dt>' + esc(key) + '</dt><dd>' + fmt(full[key]) + '</dd>';
    }}
    pref.forEach(emit);
    Object.keys(full).forEach(function (k) {{ if (k !== 'full' && k !== 'label' && k !== 'tooltip') emit(k); }});
    html += '</dl>';
    detail.innerHTML = html;
  }}

  function fmt(v) {{
    if (Array.isArray(v)) {{
      if (v.length === 0) return '<span class="hint">(empty)</span>';
      return '<ul>' + v.map(function (x) {{ return '<li>' + fmt(x) + '</li>'; }}).join('') + '</ul>';
    }}
    if (v && typeof v === 'object') {{
      return '<code>' + esc(JSON.stringify(v)) + '</code>';
    }}
    // Prose strings in the CLICK PANEL get markdown-lite (escape-first, XSS-safe).
    // fmt() is used only here, never in tooltips, so authored structure becomes
    // legible without any raw-HTML passthrough.
    return mdlite(v);
  }}

  function highlight(ele) {{
    cy.elements().removeClass('hi faded');
    if (!ele) return;
    var nb = ele.isNode() ? ele.closedNeighborhood() : ele.connectedNodes().union(ele);
    cy.elements().not(nb).addClass('faded');
    ele.addClass('hi');
  }}

  // ---- figure mode: hide nodes so a subset can be exported -----------------
  var figHidden = [], lastTapped = null;
  function updateHideUI() {{
    var b = document.getElementById('btn-showall');
    if (!b) return;
    b.textContent = figHidden.length ? ('Show all (' + figHidden.length + ')') : 'Show all';
    b.disabled = !figHidden.length;
  }}
  function figHide(n) {{
    if (!n) return;
    n.style('display', 'none');
    figHidden.push(n);
    if (lastTapped && lastTapped.id() === n.id()) lastTapped = null;
    cy.elements().removeClass('hi faded');
    updateHideUI();
  }}
  function figShowAll() {{
    figHidden.forEach(function (n) {{
      try {{ if (!n.removed()) n.removeStyle('display'); }} catch (err) {{}}
    }});
    figHidden = []; updateHideUI();
  }}
  cy.on('tap', 'node', function (e) {{
    var oe = e.originalEvent || {{}};
    if (oe.altKey) {{ figHide(e.target); return; }}
    lastTapped = e.target; renderDetail('node', e.target.data()); highlight(e.target); }});
  cy.on('tap', 'edge', function (e) {{ renderDetail('edge', e.target.data()); highlight(e.target); }});
  cy.on('tap', function (e) {{ if (e.target === cy) {{ cy.elements().removeClass('hi faded'); }} }});

  document.getElementById('btn-fit').onclick = function () {{ cy.fit(undefined, 30); }};
  document.getElementById('btn-export').onclick = function () {{
    var uri = cy.png({{ full: true, bg: '#ffffff', maxWidth: 2400 }});
    var a = document.createElement('a');
    a.href = uri;
    a.download = (document.title || 'symposium').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') + '.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }};
  document.getElementById('btn-hide').onclick = function () {{ if (lastTapped) figHide(lastTapped); }};
  document.getElementById('btn-showall').onclick = figShowAll;
  updateHideUI();
  var btnClaim = document.getElementById('btn-claim');
  var btnFull = document.getElementById('btn-full');
  var btnForce = document.getElementById('btn-force');
  var fullKey = document.getElementById('fullkey');
  var claimKey = document.getElementById('claimkey');

  // Per-mode edge de-emphasis so the mode's organizing structure reads as primary:
  //  * Claim map -> the `requires`+`accepts` backbone is prominent; the subordinate
  //    grounding + provenance edges (grounds/derived_from/reference) dim.
  //  * Full graph / Force -> nothing dimmed.
  function applyDimming(mode) {{
    cy.edges().removeClass('nonflow-dim');
    if (mode === 'claim') {{
      cy.edges('[rel="cites"]').addClass('nonflow-dim');
    }}
  }}

  var _elementsMode = 'collapsed';   // which element set is currently loaded
  function ensureElements(mode) {{
    var wantFull = (mode === 'full');
    var haveFull = (_elementsMode === 'full');
    if (wantFull === haveFull) return;
    cy.elements().remove();
    cy.add(wantFull ? FULL : COLLAPSED);
    _elementsMode = wantFull ? 'full' : 'collapsed';
  }}

  function runLayout(mode) {{
    _layoutMode = mode;
    figShowAll();                            // mode switch rebuilds elements; drop stale hides
    ensureElements(mode);
    cy.elements().removeClass('hi faded');   // clear any prior click-highlight
    btnClaim.classList.toggle('active', mode === 'claim');
    btnFull.classList.toggle('active', mode === 'full');
    btnForce.classList.toggle('active', mode === 'cose');
    claimKey.style.display = (mode === 'claim') ? '' : 'none';
    fullKey.style.display = (mode === 'full') ? '' : 'none';
    applyDimming(mode);
    buildLegend(mode);
    var lay = cy.layout(layoutOpts());
    lay.one('layoutstop', function () {{ cy.fit(undefined, 30); }});
    lay.run();
  }}
  btnClaim.onclick = function () {{ runLayout('claim'); }};
  btnFull.onclick = function () {{ runLayout('full'); }};
  btnForce.onclick = function () {{ runLayout('cose'); }};

  // ---- legend (rebuilt per mode so it never describes a mode you're not in) ----
  var c = DATA.meta.counts;
  var legend = document.getElementById('legend');

  function liveTypeCounts() {{
    var m = {{}};
    cy.nodes().forEach(function (n) {{ var t = n.data('ntype'); if (t) m[t] = (m[t] || 0) + 1; }});
    return m;
  }}
  function markersLegend() {{
    var s = '<b>Markers</b>'
      + '<span class="lg"><span class="sw" style="background:#e2e8f0;border:2.5px dotted #b45309"></span>not machine-verifiable (' + (c.unverifiable||0) + ')</span>';
    if (c.findings) {{
      s += '<span class="lg"><span class="sw" style="background:#fff7ed;border-left:3px solid #d97706"></span>'
        + c.findings + ' checker finding' + (c.findings > 1 ? 's' : '') + ' &mdash; click a claim to read</span>';
    }}
    return s;
  }}
  function claimLegend() {{
    return '<b>Nodes (' + c.nodes_total + ')</b>'
      + lgNode('#2563eb','round-rectangle','Assertion — a claim (' + (c.nodes_by_type.Assertion||0) + ')')
      + lgNode('#94a3b8','source','Addressed content — what a Ground points at (' + (c.source_nodes||0) + ')')
      + lgNode('#d97706','vee','Assumption — granted, not addressed (' + (c.nodes_by_type.Assumption||0) + ')')
      + lgNode('#9ca3af','round-rectangle','External — an assertion in another Argument (' + (c.nodes_by_type.External||0) + ')')
      + '<b>Edges (' + c.edges_total + ')</b>'
      + lgLine('#dc2626','solid','depends_on — assertion dependency (backbone)')
      + lgLine('#16a34a','solid','grounded_by, with a criterion — offered as a TEST')
      + lgLine('#64748b','dashed','grounded_by, no criterion — material built on')
      + lgLine('#7c3aed','dashed','grounded_by another Argument\'s assertion — testimony')
      + lgLine('#d97706','dotted','assumes — rests on something not addressable')
      + lgLine('#a3a3a3','dotted','cites — prose citation, never evidence (dimmed)')
      + markersLegend()
      + memberLegend()
      + '<div class="hint" style="margin-top:6px">'
        + (c.folded_grounds||0)
        + ' Ground(s) are folded into the claim and its edges. '
        + (c.shared_source_count||0) + ' address(es) carry &ge;2 Grounds &mdash; agreement '
        + 'between them is not independent corroboration. '
        + ((DATA.meta.navigable_nodes||0) > 0
            ? (DATA.meta.navigable_nodes + ' node(s) have a page of their own (dashed) &mdash; click to navigate. ')
            : '')
        + 'Use <i>Full graph</i> to see the Grounds uncollapsed.</div>';
  }}
  function fullLegend() {{
    var tc = liveTypeCounts();
    return '<b>Nodes — every Object as authored (' + cy.nodes().length + ')</b>'
      + lgNode('#9ca3af','round-rectangle','Assertion — a claim (' + (tc.Assertion||0) + ')')
      + lgNode('#0d9488','ellipse','Ground — material offered as bearing on a claim (' + (tc.Ground||0) + ')')
      + lgNode('#d97706','vee','Assumption — granted, not addressed (' + (tc.Assumption||0) + ')')
      + lgNode('#94a3b8','source','Addressed content (' + (tc.Source||0) + ')')
      + lgNode('#9ca3af','round-rectangle','External — an assertion elsewhere (' + (tc.External||0) + ')')
      + '<b>Edges (' + cy.edges().length + ')</b>'
      + lgLine('#16a34a','solid','grounded_by — assertion &rarr; Ground')
      + lgLine('#0d9488','dashed','addresses — Ground &rarr; the content it names')
      + lgLine('#d97706','dotted','assumes — assertion &rarr; assumption')
      + lgLine('#dc2626','solid','depends_on')
      + lgLine('#a3a3a3','dotted','cites')
      + markersLegend()
      + memberLegend()
      + '<div class="hint" style="margin-top:6px">Nothing is folded. Little is hidden: '
        + 'there is no Bearing layer, and a Ground sits directly on the assertion it bears on. '
        + 'Use <i>Claim map</i> to fold the Grounds back in.</div>';
  }}
  function buildLegend(mode) {{ legend.innerHTML = (mode === 'full') ? fullLegend() : claimLegend(); }}
  buildLegend('claim');

  // Members present on this page: the review's author + owners of any external node.
  function memberLegend() {{
    var mem = DATA.meta.members || {{}};
    var keys = Object.keys(mem);
    if (!keys.length) return '';
    var s = '<b>Members (' + keys.length + ')</b>';
    keys.sort().forEach(function (h) {{
      s += '<span class="lg"><span class="sw" style="border-radius:50%;background:' + mem[h] + '"></span>' + h + '</span>';
    }});
    return s;
  }}

  function lgNode(color, shape, text) {{
    var br = shape === 'ellipse' ? '50%' : '3px';
    var extra = shape === 'source' ? 'border:1.2px solid #94a3b8;background:#e2e8f0;' : '';
    return '<span class="lg"><span class="sw" style="background:' + color + ';border-radius:' + br + ';' + extra + '"></span>' + text + '</span>';
  }}
  function lgBorder(color, text) {{
    return '<span class="lg"><span class="sw" style="background:#2563eb;border:3px solid ' + color + '"></span>' + text + '</span>';
  }}
  function lgLine(color, style, text) {{
    return '<span class="lg"><span class="swl" style="border-top-color:' + color + ';border-top-style:' + style + '"></span>' + text + '</span>';
  }}

  // ---- cross-artifact navigation ----
  // A "Go to" button (in the detail panel) deep-links to the target artifact's
  // page, carrying the object id as the URL #fragment. On arrival the target page
  // reads that fragment, maps it to the claim node it lives in (DATA.meta.frag_map),
  // and centers + highlights it.
  detail.addEventListener('click', function (e) {{
    var b = e.target.closest ? e.target.closest('.navbtn') : null;
    if (!b) return;
    var f = b.getAttribute('data-file');
    var fr = b.getAttribute('data-frag');
    if (f) window.location.href = f + (fr ? '#' + String(fr).replace(/ /g, '%20') : '');
  }});
  var fragMap = DATA.meta.frag_map || {{}};
  function deepLink() {{
    var h = (location.hash || '').replace(/^#/, '');
    try {{ h = decodeURIComponent(h); }} catch (_e) {{}}
    if (!h) return;
    var node = cy.getElementById(fragMap[h] || h);
    if (node && node.length) {{
      cy.animate({{ center: {{ eles: node }}, zoom: 1.1 }}, {{ duration: 350 }});
      renderDetail('node', node.data());
      highlight(node);
    }}
  }}
  window.addEventListener('hashchange', deepLink);
  window.addEventListener('load', function () {{ setTimeout(deepLink, 0); }});

  cy.ready(function () {{
    // Claim map is the default: dim the subordinate (non-requires) edges, frame graph.
    applyDimming('claim');
    cy.fit(undefined, 30);
    // re-fit once the container has its final size (avoids an off-frame first paint)
    requestAnimationFrame(function () {{ cy.resize(); cy.fit(undefined, 30); deepLink(); }});
  }});
  window.__cy = cy; // expose for headless/console verification
}})();
</script>
<script>
/* Live reload while the record is growing. serve.py answers /__build with the current
   build number; a static host does not, and the fetch simply fails and stops. Nothing
   about the page depends on this — the compiled HTML is complete on its own. */
(function () {{
  var seen = null;
  function poll() {{
    fetch('__build', {{cache: 'no-store'}}).then(function (r) {{ return r.json(); }})
      .then(function (b) {{
        if (seen !== null && b.build !== seen) {{ location.reload(); return; }}
        seen = b.build; setTimeout(poll, 3000);
      }}).catch(function () {{ /* not served by serve.py; stop polling */ }});
  }}
  setTimeout(poll, 3000);
}})();
</script>
</body>
</html>
"""


OVERVIEW_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Symposium community — {corpus_title}</title>
<style>
  :root {{ --bg:#f6f7f9; --panel:#fff; --ink:#1a1f2b; --muted:#6b7280; --line:#d9dee6; --accent:#2563eb; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; height:100%; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:var(--bg); }}
  header {{ padding:10px 16px; background:var(--panel); border-bottom:1px solid var(--line); }}
  header h1 {{ font-size:15px; margin:0 0 2px; font-weight:650; }}
  header .sub {{ font-size:12px; color:var(--muted); }}
  .uplink {{ color:var(--accent); text-decoration:none; font-weight:600; }}
  .uplink:hover {{ text-decoration:underline; }}
  #app {{ display:flex; height:calc(100% - 50px); }}
  #graphwrap {{ position:relative; flex:1 1 66%; min-width:0; }}
  #cy {{ position:absolute; inset:0; }}
  #side {{ flex:0 0 34%; max-width:440px; border-left:1px solid var(--line); background:var(--panel); display:flex; flex-direction:column; }}
  #legend {{ padding:10px 14px; border-bottom:1px solid var(--line); font-size:11px; }}
  #legend b {{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:8px 0 4px; }}
  .lg {{ display:inline-flex; align-items:center; gap:5px; margin:0 10px 5px 0; cursor:default; }}
  .lg.filter {{ cursor:pointer; user-select:none; padding:2px 6px; border-radius:6px; }}
  .lg.filter.off {{ opacity:.35; text-decoration:line-through; }}
  .lg.filter:hover {{ background:#eef1f5; }}
  .sw {{ width:12px; height:12px; border-radius:3px; display:inline-block; border:1px solid rgba(0,0,0,.15); }}
  .swl {{ width:20px; height:0; border-top-width:3px; border-top-style:solid; display:inline-block; }}
  #detail {{ flex:1; overflow:auto; padding:12px 14px; font-size:13px; }}
  #detail .placeholder {{ color:var(--muted); font-style:italic; }}
  #detail h2 {{ font-size:14px; margin:0 0 4px; }}
  #detail .pill {{ display:inline-block; font-size:11px; padding:1px 8px; border-radius:10px; color:#fff; margin-bottom:6px; }}
  #detail dt {{ font-weight:650; font-size:11px; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); margin-top:10px; }}
  #detail dd {{ margin:2px 0 0; word-break:break-word; line-height:1.4; }}
  .mbadge {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:4px; vertical-align:middle; border:1px solid rgba(0,0,0,.15); }}
  .navbtn {{ display:inline-flex; align-items:center; gap:5px; margin:8px 0 2px; padding:6px 12px; font-size:12px; font-weight:600;
            border:1px solid var(--accent); color:#fff; background:var(--accent); border-radius:6px; cursor:pointer; }}
  .navbtn:hover {{ filter:brightness(1.08); }}
  .hint {{ font-size:11px; color:var(--muted); }}
  .tip {{ position:absolute; pointer-events:none; background:#111827; color:#f9fafb; font-size:12px; padding:6px 9px; border-radius:6px;
         max-width:320px; line-height:1.35; z-index:20; box-shadow:0 4px 14px rgba(0,0,0,.25); opacity:0; transition:opacity .08s; }}
  .toolbar {{ position:absolute; top:8px; left:8px; z-index:10; display:flex; gap:6px; }}
  .toolbar button {{ font-size:12px; padding:4px 9px; border:1px solid var(--line); background:#fff; border-radius:6px; cursor:pointer; }}
  .toolbar button:hover {{ background:#eef1f5; }}
</style>
</head>
<body>
<header>
  <h1>Symposium community &middot; {corpus_title}</h1>
  <div class="sub">{uplink}{exlink}Every artifact is a node (coloured by Member, shaped by type); every edge is a cross-artifact reference, derived from an <b>address</b> held in a property &mdash; a Ground's address, a provenance field, or a citation in prose. Columns run left&rarr;right in <b>publication order</b> (<b>earlier&nbsp;&larr;</b> left), so reference edges point <i>back</i> in time and the record is only ever built on what already existed. Rows group artifacts by type. Click an artifact for detail; open an <b>Argument</b> for its claim map, or any other artifact for the content a claim finally rests on.</div>
</header>
<div id="app">
  <div id="graphwrap">
    <div class="toolbar"><button id="btn-fit">Fit</button><button id="btn-export">Export PNG</button><button id="btn-hide">Hide node</button><button id="btn-showall">Show all</button><span style="font-size:11px;color:var(--muted);align-self:center;user-select:none">alt-click a node to hide it &middot; hidden nodes are left out of the export</span></div>
    <div id="cy"></div>
    <div id="tip" class="tip"></div>
  </div>
  <div id="side">
    <div id="legend"></div>
    <div id="detail"><p class="placeholder">Click an artifact node to see its type, Member, and title. Arguments open a claim map; every other artifact opens the content itself &mdash; the data table, the preserved passage, the model's commitments.</p></div>
  </div>
</div>
<script src="{cyto_src}"></script>
<script id="graph-data" type="application/json">{graph_json}</script>
<script>
(function () {{
  var DATA = JSON.parse(document.getElementById('graph-data').textContent);
  // Cross-artifact reference kinds. A relationship is always INTERNAL to an
  // artifact, so every edge here is derived from an ADDRESS held in a property value:
  // a Ground's `address`, a provenance field, or a markdown link in prose.
  var REL_COLORS = {{
    grounded_by:'#16a34a', testimony:'#7c3aed', cites:'#a3a3a3',
    produced_by:'#0d9488', outputs:'#0d9488', inputs:'#0284c7', used_models:'#6366f1',
    extracted_from:'#db2777', supersedes:'#b45309', recipients:'#94a3b8'
  }};
  function esc(s) {{ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

  var cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: DATA.elements,
    wheelSensitivity: 0.2,
    style: [
      {{ selector:'node', style: {{
        'label':'data(label)', 'font-size':10, 'color':'#111827', 'text-wrap':'wrap', 'text-max-width':120,
        'text-valign':'bottom', 'text-margin-y':3, 'width':30, 'height':24,
        'background-color':'data(owner_color)', 'shape':'data(shape)',
        'border-width':1.5, 'border-color':'rgba(0,0,0,0.28)' }} }},
      {{ selector:'node[ntype="Argument"]', style: {{ 'width':46, 'height':30, 'font-weight':600, 'font-size':11 }} }},
      {{ selector:'node[ntype="Review"]', style: {{ 'width':46, 'height':30, 'font-weight':600, 'font-size':11 }} }},
      {{ selector:'node[ntype="Report"]', style: {{ 'width':40, 'height':28 }} }},
      // time-ruler tick: text only, no marker, sits on the baseline under its column
      {{ selector:'node[ntype="TimeTick"]', style: {{
        'background-opacity':0, 'border-width':0, 'shape':'round-rectangle',
        'text-valign':'center', 'text-margin-y':0, 'font-size':11, 'font-weight':700,
        'color':'#94a3b8', 'width':1, 'height':1, 'text-max-width':120,
        'events':'no', 'z-index':0 }} }},
      {{ selector:'edge', style: {{
        'width':'mapData(count, 1, 12, 1.4, 5)', 'curve-style':'unbundled-bezier',
        'control-point-distances':'data(cpd)', 'control-point-weights':0.5,
        'line-color':'data(_col)',
        'target-arrow-color':'data(_col)', 'target-arrow-shape':'triangle', 'arrow-scale':0.85,
        'font-size':7, 'color':'#6b7280', 'text-rotation':'autorotate', 'label':'data(label)',
        'text-background-color':'#f6f7f9', 'text-background-opacity':0.85, 'text-background-padding':1 }} }},
      {{ selector:'.faded', style: {{ 'opacity':0.12 }} }},
      {{ selector:'.hi', style: {{ 'border-width':3, 'border-color':'#111827' }} }},
      {{ selector:'.hidden', style: {{ 'display':'none' }} }}
    ],
    layout: {{ name:'preset', padding:50, fit:true, positions:function(n){{ return n.data('_pos'); }} }}
  }});

  var tip = document.getElementById('tip');
  function showTip(evt,t){{ tip.textContent=t; tip.style.opacity=1; var r=evt.renderedPosition||evt.position;
    tip.style.left=(r.x+14)+'px'; tip.style.top=(r.y+10)+'px'; }}
  cy.on('mouseover','node,edge',function(e){{ showTip(e, e.target.data('tooltip')||''); }});
  cy.on('mousemove','node,edge',function(e){{ if(tip.style.opacity==1) showTip(e, tip.textContent); }});
  cy.on('mouseout','node,edge',function(){{ tip.style.opacity=0; }});
  cy.on('drag pan zoom',function(){{ tip.style.opacity=0; }});

  var detail = document.getElementById('detail');
  function highlight(ele){{ cy.elements().removeClass('hi faded');
    if(!ele) return; var nb=ele.closedNeighborhood(); cy.elements().not(nb).addClass('faded'); ele.addClass('hi'); }}
  function renderNode(d){{
    var f=d.full||{{}};
    var html='<h2>'+esc(f.name||d.id)+'</h2>';
    html+='<span class="pill" style="background:'+(d.owner_color||'#334155')+'">'+esc(f.type||d.ntype)+'</span>';
    html+='<div class="hint" style="margin:2px 0 6px">produced by <span class="mbadge" style="background:'+(d.owner_color||'#9ca3af')+'"></span><b>'+esc(d.member)+'</b></div>';
    if(d.nav_file){{ var lbl=(d.page_kind==='evidence')?'Open evidence ↗':'Open claim map ↗';
      html+='<button class="navbtn" data-file="'+esc(d.nav_file)+'">'+esc(lbl)+'</button>'; }}
    html+='<dl>';
    if(f.title) html+='<dt>title</dt><dd>'+esc(f.title)+'</dd>';
    html+='<dt>address</dt><dd><code>@'+esc(d.id)+'</code></dd>';
    if(f.created) html+='<dt>created</dt><dd>'+esc(f.created)+'</dd>';
    html+='<dt>objects</dt><dd>'+esc(f.object_count)+'</dd>';
    if(f.import_method) html+='<dt>import method</dt><dd>'+esc(f.import_method)+'</dd>';
    if(f.modeling_choices) html+='<dt>modeling choices</dt><dd>'+esc(f.modeling_choices)+'</dd>';
    if(f.procedure) html+='<dt>procedure</dt><dd>'+esc(f.procedure)+'</dd>';
    if(f.groundable===false) html+='<dt></dt><dd class="hint">Non-groundable by type (spec 2.1): citable in prose, never usable as evidence.</dd>';
    if(d.page_kind==='evidence') html+='<dt></dt><dd class="hint">The content itself — the data table, preserved passage, or model commitments where a claim\'s support finally resolves.</dd>';
    html+='</dl>';
    detail.innerHTML=html;
  }}
  function renderEdge(d){{
    detail.innerHTML='<h2>'+esc(d.rel)+'</h2><dl><dt>from</dt><dd>'+esc(d.source)+'</dd>'
      +'<dt>to</dt><dd>'+esc(d.target)+'</dd><dt>edges of this kind</dt><dd>'+esc(d.count)+'</dd></dl>'
      +'<p class="hint">Every relationship is internal to one artifact, so this edge is not a relationship — it is derived from an <b>address</b> held in a property value.</p>';
  }}
  // ---- figure mode: hide nodes so a subset can be exported -----------------
  // Inline `display` (not the `hidden` class) so this never fights the member filter.
  var figHidden=[], lastTapped=null;
  function updateHideUI(){{
    var b=document.getElementById('btn-showall');
    if(!b) return;
    b.textContent = figHidden.length ? ('Show all ('+figHidden.length+')') : 'Show all';
    b.disabled = !figHidden.length;
  }}
  function figHide(n){{
    if(!n) return;
    n.style('display','none');
    figHidden.push(n);
    if(lastTapped && lastTapped.id()===n.id()) lastTapped=null;
    cy.elements().removeClass('hi faded');
    updateHideUI();
  }}
  cy.on('tap','node',function(e){{ if(e.target.data('ntype')==='TimeTick') return;
    var oe=e.originalEvent||{{}};
    if(oe.altKey){{ figHide(e.target); return; }}
    lastTapped=e.target; renderNode(e.target.data()); highlight(e.target); }});
  cy.on('tap','edge',function(e){{ renderEdge(e.target.data()); highlight(e.target); }});
  cy.on('tap',function(e){{ if(e.target===cy) cy.elements().removeClass('hi faded'); }});
  cy.on('dbltap','node',function(e){{ var f=e.target.data('nav_file'); if(f) window.location.href=f; }});
  detail.addEventListener('click',function(e){{ var b=e.target.closest?e.target.closest('.navbtn'):null;
    if(b){{ var f=b.getAttribute('data-file'); if(f) window.location.href=f; }} }});
  document.getElementById('btn-fit').onclick=function(){{ cy.fit(undefined,40); }};
  document.getElementById('btn-export').onclick=function(){{
    var uri = cy.png({{ full: true, bg: '#ffffff', maxWidth: 2400 }});
    var a = document.createElement('a');
    a.href = uri;
    a.download = (document.title || 'symposium').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') + '.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }};
  document.getElementById('btn-hide').onclick=function(){{ if(lastTapped) figHide(lastTapped); }};
  document.getElementById('btn-showall').onclick=function(){{
    figHidden.forEach(function(n){{ n.removeStyle('display'); }});
    figHidden=[]; updateHideUI(); }};
  updateHideUI();

  // ---- legend + member filter ----
  var mem=DATA.meta.members||{{}}, c=DATA.meta.counts;
  var hidden={{}};
  function applyFilter(){{
    cy.nodes().forEach(function(n){{ n.toggleClass('hidden', !!hidden[n.data('member')]); }});
    cy.edges().forEach(function(e){{
      e.toggleClass('hidden', e.source().hasClass('hidden')||e.target().hasClass('hidden')); }});
  }}
  var legend=document.getElementById('legend');
  var relsPresent={{}}; cy.edges().forEach(function(e){{ relsPresent[e.data('rel')]=1; }});
  var html='<b>Members ('+Object.keys(mem).length+') — click to filter</b>';
  Object.keys(mem).sort().forEach(function(h){{
    html+='<span class="lg filter" data-mem="'+esc(h)+'"><span class="sw" style="border-radius:50%;background:'+mem[h]+'"></span>'
      +esc(h)+' ('+((c.by_member||{{}})[h]||0)+')</span>';
  }});
  html+='<b>Publication order</b>';
  html+='<div class="hint" style="margin:0 0 4px">'+esc(c.time_span||'')+' &middot; '+c.sessions+(c.sessions==1?' session':' sessions')+' (earlier &larr; left) &middot; rows = type</div>';
  html+='<b>Artifact types ('+c.artifacts+')</b>';
  Object.keys(c.by_type||{{}}).sort().forEach(function(cl){{
    html+='<span class="lg">'+esc(cl)+' <b style="display:inline;color:var(--ink)">'+c.by_type[cl]+'</b></span>';
  }});
  html+='<b>Cross-artifact edges ('+c.cross_edges+')</b>';
  Object.keys(relsPresent).sort().forEach(function(r){{
    html+='<span class="lg"><span class="swl" style="border-top-color:'+(REL_COLORS[r]||'#94a3b8')+'"></span>'+esc(r)+'</span>';
  }});
  legend.innerHTML=html;
  legend.addEventListener('click',function(e){{
    var el=e.target.closest?e.target.closest('.filter'):null; if(!el) return;
    var m=el.getAttribute('data-mem'); hidden[m]=!hidden[m]; el.classList.toggle('off',!!hidden[m]); applyFilter();
  }});

  cy.ready(function(){{ cy.fit(undefined,40);
    // re-fit once the container has its final size (avoids an off-frame first paint)
    requestAnimationFrame(function(){{ cy.resize(); cy.fit(undefined,40); }}); }});
  window.__cy=cy;
}})();
</script>
<script>
/* Live reload while the record is growing. serve.py answers /__build with the current
   build number; a static host does not, and the fetch simply fails and stops. Nothing
   about the page depends on this — the compiled HTML is complete on its own. */
(function () {{
  var seen = null;
  function poll() {{
    fetch('__build', {{cache: 'no-store'}}).then(function (r) {{ return r.json(); }})
      .then(function (b) {{
        if (seen !== null && b.build !== seen) {{ location.reload(); return; }}
        seen = b.build; setTimeout(poll, 3000);
      }}).catch(function () {{ /* not served by serve.py; stop polling */ }});
  }}
  setTimeout(poll, 3000);
}})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

import html as _html          # noqa: E402
import json as _json          # noqa: E402
import re as _re              # noqa: E402

#: Colours for the DERIVED cross-artifact edges on the overview. The record stores no
#: cross-artifact relationship, so each of these names a way an address got into a
#: property value, not an edge anyone authored.
OVERVIEW_REL_COLORS = {
    "grounded_by": "#16a34a", "testimony": "#7c3aed", "cites": "#a3a3a3",
    "produced_by": "#0d9488", "outputs": "#0d9488", "inputs": "#0284c7",
    "used_models": "#6366f1", "extracted_from": "#db2777", "supersedes": "#b45309",
    "recipients": "#94a3b8",
}


def _verdict_panel(meta):
    """The Argument's judgment, rendered once at the top of its page.

    A verdict drawn from a closed set could be a colour on a node. The specification
    states one free-text judgment per Argument instead, for a stated
    purpose, with its rationale — text that has to be READ. Putting it in the
    header rather than in a click-to-open panel reflects that: a reader should not
    be able to look at an Argument without seeing what its author concluded, and
    for what purpose.
    """
    verdict = (meta.get("verdict") or "").strip()
    purpose = (meta.get("purpose") or "").strip()
    rationale = (meta.get("rationale") or "").strip()
    if not (verdict or purpose or rationale):
        return ""
    out = ['<div id="verdictpanel">']
    out.append('<div class="vlabel">Verdict</div>')
    out.append('<div class="vtext">' + (_html.escape(verdict) or
               '<span style="color:#9ca3af">(none stated)</span>') + '</div>')
    out.append('<dl>')
    if purpose:
        out.append('<dt>Purpose and stakes</dt><dd>' + md_to_html(purpose, meta.get('addr_pages', {})) + '</dd>')
    if rationale:
        out.append('<dt>Rationale</dt><dd>' + md_to_html(rationale, meta.get('addr_pages', {})) + '</dd>')
    sup = meta.get("supersedes") or []
    if sup:
        out.append('<dt>Supersedes</dt><dd>' + _html.escape("; ".join(str(x) for x in sup))
                   + (' — ' + _html.escape(meta.get("supersedes_rationale", ""))
                      if meta.get("supersedes_rationale") else "") + '</dd>')
    out.append('</dl></div>')
    return "".join(out)


def render_claim_html(elements, meta, cytoscape_rel_path, intro_html=""):
    payload = {"elements": elements, "meta": meta}
    genre = meta.get("genre_line", "")
    intro_html = _verdict_panel(meta) + (intro_html or "")
    return HTML_TEMPLATE.format(
        title=_html.escape(meta["title"]),
        review_id=_html.escape(meta["review_id"]),
        arg_label="Argument",
        genre_html=(f' &middot; <span class="genre">{_html.escape(genre)}</span>' if genre else ""),
        member=_html.escape(meta["member"]),
        member_color=_html.escape(meta.get("member_color", "#9ca3af")),
        created=_html.escape(meta["created"]),
        cyto_src=_html.escape(cytoscape_rel_path),
        graph_json=_json.dumps(payload, ensure_ascii=False),
        intro_html=(f'<div id="intro">{intro_html}</div>' if intro_html else ''),
    )


def render_overview_html(elements, meta, cytoscape_rel_path, corpus_title="community record"):
    return OVERVIEW_TEMPLATE.format(
        cyto_src=_html.escape(cytoscape_rel_path),
        corpus_title=_html.escape(corpus_title),
        uplink="", exlink="",
        graph_json=_json.dumps({"elements": elements, "meta": meta}, ensure_ascii=False),
    )


# --------------------------------------------------------------------------- #
# Server-side markdown-lite — the same subset as the client renderer, including
# the one link form (CANONICAL.md 3.1). Escape-first, so no authored markup ever
# reaches the page; the href comes from the compiler's page table, never from the
# document, so an arbitrary URL in a property cannot become a live link.
# --------------------------------------------------------------------------- #

_LINK_RE = _re.compile(r"\[([^\]]+)\]\(\s*(?:&lt;(@[^&]+?)&gt;|(@[^)\s]+))\s*\)")


def _address_parts(addr):
    """(root, fragment) — the same anchor scheme the artifact pages emit."""
    a = addr.lstrip("@")
    root = _re.split(r"[.#]", a)[0]
    frag = ""
    if "#" in a:
        rest = a.split("#", 1)[1]
        frag = rest if "." in rest else ""
        if not frag:
            frag = rest
    elif "." in a:
        frag = a.split(".", 1)[1].split("#")[0]
    return root, frag


def _md_inline(escaped, pages):
    escaped = _re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = _re.sub(r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = _re.sub(r"\*([^*\n]+?)\*", r"<em>\1</em>", escaped)

    def link(m):
        text = m.group(1)
        addr = m.group(2) or m.group(3)
        root, frag = _address_parts(addr)
        page = (pages or {}).get(root)
        if not page:
            return f'<span class="cite-dead" title="{_html.escape(addr)}">{text}</span>'
        href = _html.escape(page) + (("#" + _html.escape(frag)) if frag else "")
        return f'<a href="{href}" title="{_html.escape(addr)}">{text}</a>'

    return _LINK_RE.sub(link, escaped)


def _mark_grounded(escaped, spans):
    """Wrap the passages this record has grounded on, and give each the id its
    `text_span` address resolves to. Two things fall out of this that are worth
    having: a Ground deep-links to the exact sentence, and an imported source shows
    at a glance which of it is load-bearing and which was never used."""
    for quote, citer in spans or []:
        needle = _html.escape(quote)
        if needle and needle in escaped:
            anchor = _html.escape(f'text_span.quote="{quote}"')
            escaped = escaped.replace(
                needle,
                f'<mark id="{anchor}" title="grounded on by {_html.escape(citer)}">'
                f'{needle}</mark>', 1)
    return escaped


def md_to_html(md, pages=None, spans=None):
    out = []
    for block in _re.split(r"\n\s*\n", (md or "").replace("\r\n", "\n").strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if all(_re.match(r"^\s*[-*]\s+", ln) for ln in lines):
            items = "".join("<li>" + _md_inline(_html.escape(_re.sub(r"^\s*[-*]\s+", "", ln)), pages)
                            + "</li>" for ln in lines)
            out.append("<ul>" + items + "</ul>")
        else:
            out.append("<p>" + "<br>".join(
                _md_inline(_mark_grounded(_html.escape(ln), spans), pages) for ln in lines)
                + "</p>")
    return "".join(out)


def csv_table(text, max_rows=200):
    """Render an embedded CSV property as a table, with each cell carrying the id a
    `csv` address resolves to — so a Ground's reference deep-links straight to the cell
    it names, and a reader can check the quote against the number."""
    rows = [r for r in (text or "").replace("\r\n", "\n").split("\n") if r.strip()]
    if not rows:
        return "<p class='hint'>(empty)</p>"
    hdr = [c.strip() for c in rows[0].split(",")]
    key = hdr[0] if hdr else "row"
    body = []
    for r in rows[1:max_rows + 1]:
        cells = [c.strip() for c in r.split(",")]
        rk = cells[0] if cells else ""
        tds = "".join(
            '<td id="{}">{}</td>'.format(
                _html.escape(f"csv.row={rk}&col={hdr[i]}" if i < len(hdr) else ""),
                _html.escape(c))
            for i, c in enumerate(cells))
        body.append(f"<tr>{tds}</tr>")
    more = ("<tr><td colspan='%d' class='hint'>… %d further row(s) not shown</td></tr>"
            % (len(hdr), len(rows) - 1 - max_rows)) if len(rows) - 1 > max_rows else ""
    head = "".join(f"<th>{_html.escape(c)}</th>" for c in hdr)
    return (f"<p class='hint'>Addressed as <code>#csv.row=&lt;{_html.escape(key)}&gt;"
            f"&amp;col=&lt;column&gt;</code></p>"
            f"<div class='tablewrap'><table class='data'><tr>{head}</tr>"
            + "".join(body) + more + "</table></div>")


ARTIFACT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#f6f7f9; --panel:#fff; --ink:#1a1f2b; --muted:#6b7280; --line:#d9dee6; --accent:#2563eb; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
               color:var(--ink); background:var(--bg); }}
  header {{ padding:10px 16px; background:var(--panel); border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }}
  header h1 {{ font-size:15px; margin:0 0 2px; font-weight:650; }}
  header .sub {{ font-size:12px; color:var(--muted); }}
  .uplink {{ color:var(--accent); text-decoration:none; font-weight:600; }}
  .mbadge {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:4px; vertical-align:middle; }}
  main {{ max-width:940px; margin:0 auto; padding:18px 20px 60px; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
        margin:26px 0 6px; padding-bottom:4px; border-bottom:1px solid var(--line); }}
  .prose {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px; line-height:1.5; font-size:14px; }}
  .prose p {{ margin:0 0 10px; }} .prose p:last-child {{ margin-bottom:0; }}
  .prose a, main a {{ color:var(--accent); }}
  .cite-dead {{ border-bottom:1px dotted var(--muted); color:var(--muted); cursor:help; }}
  code {{ background:#eef1f5; padding:1px 4px; border-radius:4px; font-size:12px; }}
  .tablewrap {{ overflow-x:auto; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
  table.data {{ border-collapse:collapse; font-size:13px; width:100%; }}
  table.data th, table.data td {{ padding:5px 10px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }}
  table.data th {{ background:#f1f5f9; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
  table.data td:target {{ background:#fef3c7; outline:2px solid #d97706; }}
  table.methods {{ border-collapse:collapse; font-size:13px; background:var(--panel);
                   border:1px solid var(--line); border-radius:8px; width:100%; }}
  table.methods th, table.methods td {{ padding:6px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
  /* A reference form often contains an example address, and an address is one unbroken token
     — a file path, a quote, a row key. Without this it runs off the right edge and is clipped,
     which loses exactly the part that says HOW to reach the content. Scoped to the LAST cell
     only: the method name and the groundable marker are short words in narrow columns, and
     break-anywhere turns "groundable" into a vertical stack of letters. */
  table.methods td:last-child {{ overflow-wrap:anywhere; word-break:break-word; }}
  table.methods td:first-child, table.methods td:nth-child(2) {{ white-space:nowrap; }}
  .yes {{ color:#15803d; font-weight:650; }} .no {{ color:#b45309; font-weight:650; }}
  .hint {{ font-size:12px; color:var(--muted); }}
  .banner {{ background:#fff7ed; border-left:3px solid #d97706; color:#7c2d12; padding:8px 12px;
             border-radius:6px; font-size:13px; margin-bottom:8px; }}
  .finding {{ margin-top:6px; padding:6px 9px; border-radius:6px; font-size:13px;
              background:#fff7ed; border-left:3px solid #d97706; color:#7c2d12; }}
  .finding.fail {{ background:#fef2f2; border-left-color:#dc2626; color:#7f1d1d; }}
  mark {{ background:#dcfce7; border-bottom:2px solid #16a34a; padding:1px 0; }}
  mark:target {{ background:#fef08a; border-bottom-color:#d97706; }}
  ul {{ padding-left:20px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="sub"><b>{atype}</b> <code>{name}</code> &middot;
    <span class="mbadge" style="background:{member_color}"></span><b>{member}</b> &middot; {created}
    &middot; <a href="index.html" class="uplink">&uarr; community record</a></div>
</header>
<main>{body}</main>
<script>
/* Live reload while the record is growing. serve.py answers /__build with the current
   build number; a static host does not, and the fetch simply fails and stops. Nothing
   about the page depends on this — the compiled HTML is complete on its own. */
(function () {{
  var seen = null;
  function poll() {{
    fetch('__build', {{cache: 'no-store'}}).then(function (r) {{ return r.json(); }})
      .then(function (b) {{
        if (seen !== null && b.build !== seen) {{ location.reload(); return; }}
        seen = b.build; setTimeout(poll, 3000);
      }}).catch(function () {{ /* not served by serve.py; stop polling */ }});
  }}
  setTimeout(poll, 3000);
}})();
</script>
</body>
</html>
"""
