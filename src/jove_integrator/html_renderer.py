from __future__ import annotations

import html
import re

from .entities import encode_scientific_html, link_html_refs
from .models import Manuscript, TextRun


def render_runs_html(runs: list[TextRun], link_refs: bool = True) -> str:
    parts: list[str] = []
    for r in runs:
        chunk = encode_scientific_html(r.text)
        if not r.text.strip():
            parts.append(chunk)
            continue
        if link_refs:
            chunk = link_html_refs(chunk)
        if r.subscript:
            chunk = f"<sub>{chunk}</sub>"
        if r.superscript:
            chunk = f"<sup>{chunk}</sup>"
        if r.italic:
            chunk = f"<em>{chunk}</em>"
        if r.bold:
            chunk = f"<strong>{chunk}</strong>"
        parts.append(chunk)
    return "".join(parts)


def _strip_place_figure_markers(runs: list[TextRun]) -> list[TextRun]:
    return [
        TextRun(
            text=re.sub(r"\s*\[Place Figure \d+ here\]", "", r.text),
            bold=r.bold,
            italic=r.italic,
            subscript=r.subscript,
            superscript=r.superscript,
        )
        for r in runs
    ]


def render_article_html(ms: Manuscript, asset_prefix: str = "") -> str:
    """Render a semantic HTML5 + CSS JoVE-style article page."""
    aff_label_by_id = {aff.id: aff.label for aff in ms.affiliations}
    authors_html_parts: list[str] = []
    for a in ms.authors:
        name = encode_scientific_html(f"{a.given_names} {a.surname}".strip())
        sup_tags = [encode_scientific_html(aff_label_by_id[aid]) for aid in a.affiliation_ids if aid in aff_label_by_id]
        if a.is_corresponding:
            sup_tags.append("*")
        sup_html = f"<sup>{','.join(sup_tags)}</sup>" if sup_tags else ""
        authors_html_parts.append(f'<span class="jove-author">{name}{sup_html}</span>')

    affs_html = "\n".join(
        f'<li data-qa-loc="Affiliation {html.escape(aff.label)}"><sup>{encode_scientific_html(aff.label)}</sup> {encode_scientific_html(aff.institution)}</li>'
        for aff in ms.affiliations
    )

    corr_authors = [a for a in ms.authors if a.is_corresponding and a.email]
    corr_html = ""
    if corr_authors:
        corr_items = "; ".join(
            f"{encode_scientific_html(a.given_names + ' ' + a.surname)} "
            f'(<a href="mailto:{html.escape(a.email or "")}">{html.escape(a.email or "")}</a>)'
            for a in corr_authors
        )
        corr_html = f'<p class="jove-corresp"><strong>Correspondence:</strong> {corr_items}</p>'

    keywords_html = ""
    if ms.keywords:
        kw_tags = " ".join(f'<span class="jove-kw">{encode_scientific_html(k)}</span>' for k in ms.keywords)
        keywords_html = f'<div class="jove-keywords"><strong>Keywords:</strong> {kw_tags}</div>'

    intro_html = "\n".join(
        f'<p data-qa-loc="Introduction ¶{idx}">{render_runs_html(p)}</p>'
        for idx, p in enumerate(ms.introduction, start=1)
    )

    proto_sections_html: list[str] = []
    for sec in ms.protocol_sections:
        steps_li: list[str] = []
        for step in sec.steps:
            notes_html = "".join(
                f'<div class="jove-callout jove-callout-{kind.lower()}" data-qa-loc="Protocol {html.escape(step.number)} {kind}">'
                f"<strong>{kind}:</strong> {render_runs_html(nruns)}</div>"
                for kind, nruns in step.notes
            )
            sub_html = ""
            if step.substeps:
                sub_items: list[str] = []
                for sub in step.substeps:
                    sub_notes = "".join(
                        f'<div class="jove-callout jove-callout-{kind.lower()}" data-qa-loc="Protocol {html.escape(sub.number)} {kind}">'
                        f"<strong>{kind}:</strong> {render_runs_html(nruns)}</div>"
                        for kind, nruns in sub.notes
                    )
                    sub_items.append(
                        f'<li data-step="{html.escape(sub.number)}" data-qa-loc="Protocol {html.escape(sub.number)}">'
                        f'<span class="step-num">{html.escape(sub.number)}</span> '
                        f"{render_runs_html(sub.runs)}{sub_notes}</li>"
                    )
                sub_html = f'<ol class="jove-substeps">{"".join(sub_items)}</ol>'
            steps_li.append(
                f'<li data-step="{html.escape(step.number)}" data-qa-loc="Protocol {html.escape(step.number)}">'
                f'<span class="step-num">{html.escape(step.number)}</span> '
                f"{render_runs_html(step.runs)}{notes_html}{sub_html}</li>"
            )
        proto_sections_html.append(
            f'<section class="jove-proto-sec" id="proto-{html.escape(sec.number)}" data-qa-loc="Protocol {html.escape(sec.number)}">'
            f"<h3>{html.escape(sec.number)}. {encode_scientific_html(sec.title)}</h3>"
            f'<ol class="jove-steps">{"".join(steps_li)}</ol>'
            f"</section>"
        )

    formulas_html = ""
    if ms.formulas:
        eq_blocks = [
            f'<div class="jove-equation" id="{html.escape(eq.id)}">'
            f'<div class="eq-body"><code>{encode_scientific_html(eq.tex)}</code></div>'
            f'<div class="eq-label">{encode_scientific_html(eq.label)} - {encode_scientific_html(eq.description)}</div>'
            f"</div>"
            for eq in ms.formulas
        ]
        formulas_html = f'<section id="equations"><h2>Equations</h2>{"".join(eq_blocks)}</section>'

    results_paras = [
        f'<p data-qa-loc="Representative Results ¶{idx}">{render_runs_html(_strip_place_figure_markers(p)).strip()}</p>'
        for idx, p in enumerate(ms.representative_results, start=1)
    ]

    figures_html = ""
    if ms.figures:
        fig_blocks = []
        for fig in ms.figures:
            img_src = f"{asset_prefix}{fig.web_filename or fig.source_filename}"
            large_href = f"{asset_prefix}{fig.large_filename or fig.web_filename or fig.source_filename}"
            fig_blocks.append(
                f'<figure class="jove-figure" id="{html.escape(fig.id)}" data-qa-loc="{html.escape(fig.label)} Legend">'
                f'<img src="{html.escape(img_src)}" alt="{html.escape(fig.alt_text)}" />'
                f"<figcaption><strong>{encode_scientific_html(fig.label)}: {encode_scientific_html(fig.title)}.</strong> "
                f"{render_runs_html(fig.caption_runs)} "
                f'<a class="jove-large-link" href="{html.escape(large_href)}" target="_blank" rel="noopener">View high-res</a>'
                f"</figcaption></figure>"
            )
        figures_html = "\n".join(fig_blocks)

    materials_html = ""
    if ms.materials:
        rows = "\n".join(
            "<tr>"
            f"<td>{encode_scientific_html(m.name)}</td>"
            f"<td>{encode_scientific_html(m.company)}</td>"
            f"<td><code>{encode_scientific_html(m.catalog_number)}</code></td>"
            f"<td>{encode_scientific_html(m.comments)}</td>"
            "</tr>"
            for m in ms.materials
        )
        materials_html = (
            '<section id="materials" data-qa-loc="Table of Materials"><h2>Table of Materials</h2>'
            '<table class="jove-materials-table">'
            "<thead><tr><th>Name</th><th>Company</th><th>Catalog Number</th><th>Comments</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></section>"
        )

    if ms.tables:
        tbl_blocks = []
        for tbl in ms.tables:
            cols = max(len(tbl.headers), max((len(r) for r in tbl.rows), default=1))
            ths = "".join(f"<th>{encode_scientific_html(h)}</th>" for h in (tbl.headers + [""] * cols)[:cols])
            trs = "\n".join(
                "<tr>" + "".join(f"<td>{encode_scientific_html(c)}</td>" for c in (row + [""] * cols)[:cols]) + "</tr>"
                for row in tbl.rows
            )
            tbl_blocks.append(
                f'<section id="{html.escape(tbl.id)}"><h3>{encode_scientific_html(tbl.label)}: {encode_scientific_html(tbl.title)}</h3>'
                f'<table class="jove-materials-table"><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></section>'
            )
        materials_html += "\n" + "\n".join(tbl_blocks)

    discussion_html = "\n".join(
        f'<p data-qa-loc="Discussion ¶{idx}">{render_runs_html(p)}</p>'
        for idx, p in enumerate(ms.discussion, start=1)
    )

    refs_html = ""
    if ms.references:
        ref_items = []
        for ref in ms.references:
            doi_link = (
                f' <a href="https://doi.org/{html.escape(ref.doi)}" target="_blank" rel="noopener">doi:{html.escape(ref.doi)}</a>'
                if ref.doi
                else ""
            )
            ref_items.append(
                f'<li id="ref-{ref.number}">'
                f"{encode_scientific_html(ref.authors)}. {encode_scientific_html(ref.title)}. "
                f"<em>{encode_scientific_html(ref.journal)}</em>. "
                f"{encode_scientific_html(ref.volume)}"
                f"{f' ({encode_scientific_html(ref.issue)})' if ref.issue else ''}"
                f"{f', {encode_scientific_html(ref.pages)}' if ref.pages else ''} "
                f"({encode_scientific_html(ref.year)}).{doi_link}</li>"
            )
        refs_html = f'<section id="references" data-qa-loc="References"><h2>References</h2><ol class="jove-references">{"".join(ref_items)}</ol></section>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{encode_scientific_html(ms.title)} | JoVE Protocol Preview</title>
  <style>
    :root {{
      --jove-ink: #0f172a;
      --jove-muted: #475569;
      --jove-accent: #1e40af;
      --jove-border: #cbd5e1;
      --jove-surface: #ffffff;
      --jove-bg: #f6f7f9;
      --jove-note-bg: #eff6ff;
      --jove-note-border: #1e40af;
      --jove-caution-bg: #fef2f2;
      --jove-caution-border: #991b1b;
    }}
    body {{
      margin: 0;
      padding: 1.75rem 1.25rem;
      background: var(--jove-bg);
      color: var(--jove-ink);
      font-family: Georgia, "Times New Roman", serif;
      line-height: 1.68;
    }}
    .jove-article {{
      max-width: 840px;
      margin: 0 auto;
      background: var(--jove-surface);
      border: 1px solid var(--jove-border);
      border-radius: 6px;
      padding: 2.25rem 2.75rem;
    }}
    .jove-meta-bar {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.78rem;
      color: var(--jove-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 0.65rem;
    }}
    h1 {{
      font-size: 1.75rem;
      line-height: 1.25;
      margin: 0 0 0.9rem;
    }}
    h2 {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 1.12rem;
      border-bottom: 1px solid var(--jove-border);
      padding-bottom: 0.3rem;
      margin-top: 1.85rem;
    }}
    h3 {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.98rem;
      color: var(--jove-accent);
      margin: 1.15rem 0 0.45rem;
    }}
    .jove-authors {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.92rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 0.45rem;
    }}
    .jove-affiliations {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.84rem;
      color: var(--jove-muted);
      list-style: none;
      padding: 0;
      margin: 0.25rem 0 0.7rem;
    }}
    .jove-corresp, .jove-keywords {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.84rem;
      color: var(--jove-muted);
    }}
    .jove-kw {{
      display: inline-block;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      color: var(--jove-ink);
      padding: 0.1rem 0.45rem;
      border-radius: 4px;
      margin: 0.15rem 0.25rem 0.15rem 0;
      font-size: 0.76rem;
    }}
    ol.jove-steps, ol.jove-substeps {{
      list-style: none;
      padding-left: 0;
    }}
    ol.jove-substeps {{
      padding-left: 1.4rem;
      margin-top: 0.45rem;
      border-left: 2px solid #e2e8f0;
    }}
    ol.jove-steps > li, ol.jove-substeps > li {{
      margin-bottom: 0.7rem;
    }}
    .step-num {{
      font-family: system-ui, -apple-system, sans-serif;
      font-weight: 700;
      color: var(--jove-accent);
      margin-right: 0.35rem;
    }}
    .jove-callout {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.88rem;
      padding: 0.6rem 0.85rem;
      margin: 0.45rem 0 0.45rem 1.15rem;
      border-left: 3px solid;
      border-radius: 0 4px 4px 0;
    }}
    .jove-callout-note {{
      background: var(--jove-note-bg);
      border-color: var(--jove-note-border);
    }}
    .jove-callout-caution {{
      background: var(--jove-caution-bg);
      border-color: var(--jove-caution-border);
    }}
    .jove-equation {{
      background: #f8fafc;
      border: 1px solid var(--jove-border);
      border-radius: 4px;
      padding: 0.8rem 1rem;
      margin: 0.9rem 0;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
    }}
    .jove-figure {{
      margin: 1.35rem 0;
      padding: 0.9rem;
      border: 1px solid var(--jove-border);
      border-radius: 4px;
      background: #ffffff;
    }}
    .jove-figure img {{
      max-width: 100%;
      height: auto;
      display: block;
      margin: 0 auto 0.7rem;
    }}
    .jove-figure figcaption {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.86rem;
      color: var(--jove-muted);
    }}
    .jove-materials-table {{
      width: 100%;
      border-collapse: collapse;
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 0.86rem;
      margin-top: 0.7rem;
    }}
    .jove-materials-table th, .jove-materials-table td {{
      border: 1px solid var(--jove-border);
      padding: 0.5rem 0.65rem;
      text-align: left;
    }}
    .jove-materials-table th {{
      background: #f1f5f9;
      font-weight: 600;
    }}
    .jove-xref, .jove-cite {{
      color: var(--jove-accent);
      text-decoration: none;
      font-weight: 600;
    }}
    .jove-xref:hover, .jove-cite:hover {{
      text-decoration: underline;
    }}
    .jove-references {{
      font-size: 0.88rem;
      padding-left: 1.35rem;
    }}
    .jove-references li {{
      margin-bottom: 0.45rem;
    }}
    .qa-tracked-target {{
      outline: 2px solid #1e40af;
      outline-offset: 4px;
      background: #eff6ff;
      border-radius: 4px;
    }}
    mark.qa-tracked-hit {{
      background: #fde68a;
      color: #0f172a;
      padding: 0.05rem 0.2rem;
      border-radius: 3px;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <article class="jove-article">
    <div class="jove-meta-bar">Journal of Visualized Experiments &middot; {encode_scientific_html(ms.subject_area)} &middot; DOI: {encode_scientific_html(ms.doi)}</div>
    <h1 data-qa-loc="Title">{encode_scientific_html(ms.title)}</h1>
    <div class="jove-authors" data-qa-loc="Authors &amp; Affiliations">{"".join(authors_html_parts)}</div>
    <ul class="jove-affiliations">{affs_html}</ul>
    {corr_html}
    {keywords_html}

    <section id="summary" data-qa-loc="Summary"><h2>Summary</h2><p>{render_runs_html(ms.summary)}</p></section>
    <section id="abstract" data-qa-loc="Abstract"><h2>Abstract</h2><p>{render_runs_html(ms.abstract)}</p></section>
    <section id="introduction"><h2>Introduction</h2>{intro_html}</section>
    <section id="protocol"><h2>Protocol</h2>{"".join(proto_sections_html)}</section>
    {formulas_html}
    <section id="results"><h2>Representative Results</h2>{"".join(results_paras)}{figures_html}</section>
    {materials_html}
    <section id="discussion"><h2>Discussion</h2>{discussion_html}</section>
    <section id="acknowledgments" data-qa-loc="Acknowledgments"><h2>Acknowledgments</h2><p>{render_runs_html(ms.acknowledgments)}</p></section>
    <section id="disclosures" data-qa-loc="Disclosures"><h2>Disclosures</h2><p>{render_runs_html(ms.disclosures)}</p></section>
    {refs_html}
  </article>
</body>
</html>
"""
