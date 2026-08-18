"""Figure-mode SVG export for Symposium claim maps.

    python browse.py ../record --out dist --figures fig

Emits one standalone SVG per Argument, drawn from the SAME precomputed positions
the browser uses (`_pos_claim`), so a figure is the picture the reader saw.

Rendered here in Python rather than in the page for three reasons: the compiled
pages are offline and no Cytoscape SVG extension is vendored; a build step that
needs no browser can be re-run whenever the record changes; and the layout is
already deterministic, so nothing is gained by round-tripping through a canvas.

Figure mode differs from screen mode deliberately:

  * **Labels are not elided.** On screen a claim is truncated to ~90 characters
    because the panel holds the rest. A figure has no panel, so the full claim is
    wrapped across lines. Authors should still keep claims short — a claim that
    needs six lines is a claim that will not read as a figure.
  * **Type sizes are print-scaled**, not screen-tuned.
  * **No chrome**: no header, legend, or side panel. A caption does that work.
  * **Preset positions only.** The force layout is never used: a figure must be
    reproducible, and cose is not.
"""
from __future__ import annotations

import html
import math
import pathlib

# Print-scaled geometry. Screen mode packs nodes tightly because the reader can
# zoom; a figure cannot be zoomed, so everything is larger and further apart.
PAD = 48.0
FONT_CLAIM = 13.0
FONT_LEAF = 10.5
LINE_H = 1.28
CLAIM_W = 210.0          # wrap width for assertion labels, in px
LEAF_W = 185.0           # a citation label is an artifact title plus a cell reference
CHAR_W = 0.55            # rough advance width as a fraction of font size

# Screen positions pack tightly because the reader can zoom and hover; a figure
# can do neither, so positions are spread and long prose is capped.
SPREAD = 1.45
# A claim should read in full. A leaf label (an address) and an Assumption's
# rationale are prose that belongs in the caption or the page, not the figure —
# capped so a single verbose Assumption cannot swamp the picture.
MAX_LEAF_LINES = 4

EDGE_STYLE = {
    # rel                     colour     width  dash
    "depends_on":            ("#dc2626", 2.6,  None),
    "assumes":               ("#d97706", 2.0,  "2 4"),
    "cites":                 ("#a3a3a3", 1.4,  "1 5"),
    "grounded_by_test":      ("#16a34a", 2.4,  None),
    "grounded_by_material":  ("#64748b", 1.8,  "7 5"),
    "grounded_by_testimony": ("#7c3aed", 2.2,  "7 5"),
}


def _wrap(text, width_px, font_px):
    """Greedy word wrap to a pixel width. Returns a list of lines."""
    if not text:
        return []
    max_chars = max(8, int(width_px / (font_px * CHAR_W)))
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) <= max_chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _edge_key(d):
    rel = d.get("rel")
    if rel != "grounded_by":
        return rel
    if d.get("testimony"):
        return "grounded_by_testimony"
    return "grounded_by_test" if d.get("kind") == "test" else "grounded_by_material"


def _node_label(d):
    """Full, unelided label text for a node."""
    full = d.get("full") or {}
    if d.get("ntype") == "Assertion":
        return full.get("claim") or d.get("label") or d.get("id")
    if d.get("ntype") == "Assumption":
        return full.get("rationale") or d.get("label") or ""
    name = d.get("name") or d.get("label") or d.get("id")
    # A prose citation is navigation, never evidence. On screen the panel says so and
    # the node is labelled "cited:"; in a figure there is no panel, and an unlabelled
    # reference node is indistinguishable from the source of a Ground. Say it on the
    # node, because the alternative is a figure that shows evidence where there is none.
    if str(d.get("id", "")).startswith("cite:"):
        return f"cited in prose, not evidence: {name}"
    return name


def _shape(x, y, w, h, ntype, fill, dashed):
    """The node body. Shapes carry meaning, so they differ by Object type."""
    stroke = "#1e3a8a" if ntype == "Assertion" else "#64748b"
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    if ntype == "Assumption":
        # chevron: rests on something the author could not address
        pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in [
            (x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2 - 7, y),
            (x + w / 2, y + h / 2), (x - w / 2, y + h / 2), (x - w / 2 + 7, y)])
        return (f'<polygon points="{pts}" fill="{fill}" fill-opacity="0.85" '
                f'stroke="#b45309" stroke-width="1.5"{dash}/>')
    if ntype in ("Source", "External"):
        # hexagon: addressed content, subordinate to claims
        k = h / 2
        pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in [
            (x - w / 2, y), (x - w / 2 + k, y - h / 2), (x + w / 2 - k, y - h / 2),
            (x + w / 2, y), (x + w / 2 - k, y + h / 2), (x - w / 2 + k, y + h / 2)])
        return (f'<polygon points="{pts}" fill="{fill}" fill-opacity="0.9" '
                f'stroke="{stroke}" stroke-width="1.4"{dash}/>')
    return (f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" rx="7" fill="{fill}" fill-opacity="0.92" '
            f'stroke="{stroke}" stroke-width="2"{dash}/>')


def render_claim_svg(elements, meta, title=None):
    """One Argument's claim map as a standalone SVG string."""
    nodes = [n["data"] for n in elements["nodes"] if "_pos_claim" in n["data"]]
    edges = [e["data"] for e in elements["edges"]]
    if not nodes:
        return ""

    by_id, boxes = {}, {}
    for d in nodes:
        by_id[d["id"]] = d
        is_claim = d.get("ntype") == "Assertion"
        font = FONT_CLAIM if is_claim else FONT_LEAF
        wrap_w = CLAIM_W if is_claim else LEAF_W
        lines = _wrap(_node_label(d), wrap_w, font)
        if not is_claim and len(lines) > MAX_LEAF_LINES:
            lines = lines[:MAX_LEAF_LINES]
            lines[-1] = lines[-1].rstrip(" ,;") + "…"
        text_h = len(lines) * font * LINE_H
        # The body sits above the text for leaves and behind it for claims, which
        # is what the screen view does; keeping it identical keeps the figure and
        # the interactive page recognisably the same picture.
        if is_claim:
            w = wrap_w + 22
            h = max(38.0, text_h + 16)
        else:
            w, h = 46.0, 22.0
        # A leaf's body is a small hexagon and its label is a wrapped block drawn
        # BELOW it, centred, up to the wrap width — so the drawn extent of a leaf is
        # its text, not its body, and it is three times wider. Bounds taken from the
        # body clipped every long citation label off the edge of the figure.
        text_w = max((len(ln) for ln in lines), default=0) * font * CHAR_W
        boxes[d["id"]] = {"lines": lines, "font": font, "w": w, "h": h,
                          "draw_w": max(w, text_w), "text_h": text_h,
                          "is_claim": is_claim}

    pos = {d["id"]: (d["_pos_claim"]["x"] * SPREAD, d["_pos_claim"]["y"] * SPREAD)
           for d in nodes}
    # Bounds from the ACTUAL drawn extent of every node, so nothing clips.
    min_x = min(pos[d["id"]][0] - boxes[d["id"]]["draw_w"] / 2 for d in nodes)
    max_x = max(pos[d["id"]][0] + boxes[d["id"]]["draw_w"] / 2 for d in nodes)
    min_y = min(pos[d["id"]][1] - boxes[d["id"]]["h"] / 2 for d in nodes)
    max_y = max(pos[d["id"]][1] + boxes[d["id"]]["h"] / 2
                + (0 if boxes[d["id"]]["is_claim"]
                   else boxes[d["id"]]["text_h"] + 10) for d in nodes)
    w_total, h_total = (max_x - min_x) + 2 * PAD, (max_y - min_y) + 2 * PAD
    ox, oy = PAD - min_x, PAD - min_y

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_total:.0f}" '
        f'height="{h_total:.0f}" viewBox="0 0 {w_total:.0f} {h_total:.0f}" '
        f'font-family="Helvetica, Arial, sans-serif">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    if title:
        out.append(f'<title>{html.escape(str(title))}</title>')
    # arrowheads, one per edge colour
    out.append("<defs>")
    for key, (colour, _w, _d) in EDGE_STYLE.items():
        out.append(f'<marker id="a_{key}" viewBox="0 0 10 10" refX="9" refY="5" '
                   f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
                   f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{colour}"/></marker>')
    out.append("</defs>")

    # ---- edges first, so nodes sit on top ----
    for e in edges:
        s, t = by_id.get(e.get("source")), by_id.get(e.get("target"))
        if not s or not t:
            continue
        key = _edge_key(e)
        colour, width, dash = EDGE_STYLE.get(key, ("#94a3b8", 1.4, None))
        x1, y1 = pos[s["id"]][0] + ox, pos[s["id"]][1] + oy
        x2, y2 = pos[t["id"]][0] + ox, pos[t["id"]][1] + oy
        # stop short of the target body so the arrowhead is visible
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy) or 1.0
        inset = boxes[t["id"]]["w"] / 2 + 4
        x2 -= dx / dist * inset
        y2 -= dy / dist * inset
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                   f'stroke="{colour}" stroke-width="{width}"{da} '
                   f'marker-end="url(#a_{key})"/>')

    # ---- nodes ----
    for d in nodes:
        b = boxes[d["id"]]
        x = pos[d["id"]][0] + ox
        y = pos[d["id"]][1] + oy
        ntype = d.get("ntype")
        fill = d.get("owner_color", "#2563eb") if ntype == "Assertion" else (
            "#e5e7eb" if ntype == "External" else
            "#fbbf24" if ntype == "Assumption" else "#cbd5e1")
        out.append(_shape(x, y, b["w"], b["h"], ntype,
                          fill, bool(d.get("navigable"))))
        if d.get("primary"):
            out.append(f'<rect x="{x - b["w"] / 2 - 5:.1f}" y="{y - b["h"] / 2 - 5:.1f}" '
                       f'width="{b["w"] + 10:.1f}" height="{b["h"] + 10:.1f}" rx="10" '
                       f'fill="none" stroke="#1e3a8a" stroke-width="1.6" '
                       f'stroke-dasharray="3 3"/>')

        is_cite = str(d.get("id", "")).startswith("cite:")
        colour = ("#ffffff" if ntype == "Assertion"
                  else "#94a3b8" if is_cite else "#1f2937")
        weight = "600" if ntype == "Assertion" else "400"
        if b["is_claim"]:
            start = y - b["text_h"] / 2 + b["font"] * 0.9
        else:
            start = y + b["h"] / 2 + b["font"] * 1.15
        # A leaf's label is drawn outside its body, in the space edges run through.
        # A white halo under the glyphs keeps it readable where an unrelated edge
        # passes behind it, without boxing the label and cluttering the figure.
        halo = ("" if b["is_claim"] else
                ' stroke="#ffffff" stroke-width="3.2" paint-order="stroke"')
        for i, line in enumerate(b["lines"]):
            out.append(
                f'<text x="{x:.1f}" y="{start + i * b["font"] * LINE_H:.1f}" '
                f'text-anchor="middle" font-size="{b["font"]:.1f}" fill="{colour}" '
                f'font-weight="{weight}"{halo}>{html.escape(line)}</text>')

    out.append("</svg>")
    return "\n".join(out)


def write_figures(figures, out_dir):
    """figures: [(stem, svg_text)] -> files. Returns the paths written."""
    d = pathlib.Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for stem, svg in figures:
        if not svg:
            continue
        p = d / f"{stem}.svg"
        p.write_text(svg, encoding="utf-8")
        written.append(p)
    return written
