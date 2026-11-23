from __future__ import annotations

import re

from .entities import encode_scientific_xml, link_jats_xrefs
from .models import Manuscript, ReferenceItem, TextRun

JATS_DOCTYPE = (
    '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.3 20210610//EN" '
    '"https://jats.nlm.nih.gov/publishing/1.3/JATS-journalpublishing1-3.dtd">'
)


def _render_runs_jats(
    runs: list[TextRun],
    valid_figs: set[str],
    valid_eqs: set[str],
    valid_refs: set[int],
    link_refs: bool = True,
) -> str:
    parts: list[str] = []
    for r in runs:
        chunk = encode_scientific_xml(r.text)
        if not r.text.strip():
            parts.append(chunk)
            continue
        if link_refs:
            chunk = link_jats_xrefs(chunk, valid_figs, valid_eqs, valid_refs)
        if r.subscript:
            chunk = f"<sub>{chunk}</sub>"
        if r.superscript:
            chunk = f"<sup>{chunk}</sup>"
        if r.italic:
            chunk = f"<italic>{chunk}</italic>"
        if r.bold:
            chunk = f"<bold>{chunk}</bold>"
        parts.append(chunk)
    return "".join(parts)


def _render_citation_xml(ref: ReferenceItem) -> str:
    author_tokens = re.findall(r"([A-Za-z\-']+),\s*([A-Z](?:\.[A-Z]\.?|\.)?)", ref.authors)
    if author_tokens:
        names_xml = "".join(
            f"<name><surname>{encode_scientific_xml(sur)}</surname>"
            f"<given-names>{encode_scientific_xml(giv.replace('.', ''))}</given-names></name>"
            for sur, giv in author_tokens
        )
        person_group = f'<person-group person-group-type="author">{names_xml}</person-group>'
    else:
        person_group = (
            f'<person-group person-group-type="author">'
            f"<collab>{encode_scientific_xml(ref.authors)}</collab></person-group>"
        )

    vol_xml = f"<volume>{encode_scientific_xml(ref.volume)}</volume>" if ref.volume else ""
    issue_xml = f"<issue>{encode_scientific_xml(ref.issue)}</issue>" if ref.issue else ""
    pages_xml = ""
    if ref.pages:
        if "-" in ref.pages:
            fp, lp = ref.pages.split("-", 1)
            pages_xml = f"<fpage>{encode_scientific_xml(fp)}</fpage><lpage>{encode_scientific_xml(lp)}</lpage>"
        else:
            pages_xml = f"<elocation-id>{encode_scientific_xml(ref.pages)}</elocation-id>"
    valid_doi = ref.doi if re.match(r"^10\.\d{4,9}/\S+$", ref.doi or "") else ""
    doi_xml = f'<pub-id pub-id-type="doi">{encode_scientific_xml(valid_doi)}</pub-id>' if valid_doi else ""

    return (
        f'      <ref id="{ref.id}">\n'
        f"        <label>{ref.number}</label>\n"
        f'        <element-citation publication-type="journal">\n'
        f"          {person_group}\n"
        f"          <article-title>{encode_scientific_xml(ref.title)}</article-title>\n"
        f"          <source>{encode_scientific_xml(ref.journal)}</source>\n"
        f"          <year>{encode_scientific_xml(ref.year)}</year>\n"
        f"          {vol_xml}{issue_xml}{pages_xml}{doi_xml}\n"
        f"        </element-citation>\n"
        f"      </ref>"
    )


def _build_mathml_for_formula(tex: str, eq_id: str) -> str:
    if "\\Delta f" in tex and "f_{\\max}" in tex:
        return (
            f'<mml:math id="mml-{eq_id}" display="block">'
            "<mml:mrow>"
            "<mml:mi>&#x0394;</mml:mi><mml:mi>f</mml:mi>"
            "<mml:mo>=</mml:mo>"
            "<mml:mfrac>"
            "<mml:mrow><mml:msub><mml:mi>f</mml:mi><mml:mi>max</mml:mi></mml:msub>"
            "<mml:mo>-</mml:mo>"
            "<mml:msub><mml:mi>f</mml:mi><mml:mi>min</mml:mi></mml:msub></mml:mrow>"
            "<mml:mrow><mml:mi>N</mml:mi><mml:mo>-</mml:mo><mml:mn>1</mml:mn></mml:mrow>"
            "</mml:mfrac>"
            "</mml:mrow>"
            "</mml:math>"
        )
    return f'<mml:math id="mml-{eq_id}" display="block"><mml:mtext>{encode_scientific_xml(tex)}</mml:mtext></mml:math>'


def build_jats_xml(ms: Manuscript) -> str:
    """Build a NISO JATS 1.3 Journal Publishing XML document compliant with PMC Tagging Guidelines."""
    valid_figs = {f.id for f in ms.figures}
    valid_eqs = {e.id for e in ms.formulas}
    valid_refs = {r.number for r in ms.references}

    date_parts = ms.pub_date.split("-")
    year = date_parts[0] if len(date_parts) >= 1 and date_parts[0].isdigit() else "2026"
    month = date_parts[1] if len(date_parts) >= 2 and date_parts[1].isdigit() else "11"
    day = date_parts[2] if len(date_parts) >= 3 and date_parts[2].isdigit() else "23"
    aff_label_by_id = {aff.id: aff.label for aff in ms.affiliations}
    valid_aff_ids = set(aff_label_by_id.keys())
    contrib_lines: list[str] = []
    corresp_lines: list[str] = []
    for idx, a in enumerate(ms.authors, start=1):
        xrefs = "".join(
            f'<xref ref-type="aff" rid="{aid}">{encode_scientific_xml(aff_label_by_id[aid])}</xref>'
            for aid in a.affiliation_ids
            if aid in valid_aff_ids
        )
        corr_attr = ' corresp="yes"' if a.is_corresponding else ""
        if a.is_corresponding:
            cor_id = f"cor{idx}"
            xrefs += f'<xref ref-type="corresp" rid="{cor_id}">*</xref>'
            email_xml = f"<email>{encode_scientific_xml(a.email)}</email>" if a.email else ""
            corresp_lines.append(
                f'        <corresp id="{cor_id}"><label>*</label>Correspondence to: '
                f"{encode_scientific_xml(a.given_names)} {encode_scientific_xml(a.surname)} {email_xml}</corresp>"
            )
        given_xml = f"<given-names>{encode_scientific_xml(a.given_names)}</given-names>" if a.given_names.strip() else ""
        contrib_lines.append(
            f'        <contrib contrib-type="author"{corr_attr}>\n'
            f"          <name><surname>{encode_scientific_xml(a.surname or 'Author')}</surname>"
            f"{given_xml}</name>\n"
            + (f"          {xrefs}\n" if xrefs else "")
            + "        </contrib>"
        )

    aff_lines = [
        f'        <aff id="{aff.id}"><label>{encode_scientific_xml(aff.label)}</label>{encode_scientific_xml(aff.institution)}</aff>'
        for aff in ms.affiliations
    ]

    if contrib_lines:
        contrib_group_xml = (
            "      <contrib-group>\n"
            + "\n".join(contrib_lines)
            + ("\n" + "\n".join(aff_lines) if aff_lines else "")
            + "\n      </contrib-group>\n"
        )
    elif aff_lines:
        contrib_group_xml = "\n".join(aff_lines) + "\n"
    else:
        contrib_group_xml = ""

    author_notes_xml = (
        "      <author-notes>\n" + "\n".join(corresp_lines) + "\n      </author-notes>\n"
        if corresp_lines
        else ""
    )

    kwd_xml = ""
    if ms.keywords:
        kwds = "\n".join(f"        <kwd>{encode_scientific_xml(k)}</kwd>" for k in ms.keywords if k.strip())
        if kwds:
            kwd_xml = f'      <kwd-group kwd-group-type="author">\n{kwds}\n      </kwd-group>\n'

    abs_paras: list[str] = []
    if ms.summary:
        s_txt = _render_runs_jats(ms.summary, valid_figs, valid_eqs, valid_refs, link_refs=False).strip()
        if s_txt:
            abs_paras.append(f"        <p>{s_txt}</p>")
    if ms.abstract:
        a_txt = _render_runs_jats(ms.abstract, valid_figs, valid_eqs, valid_refs, link_refs=False).strip()
        if a_txt:
            abs_paras.append(f"        <p>{a_txt}</p>")
    abstract_xml = "      <abstract>\n" + "\n".join(abs_paras) + "\n      </abstract>\n" if abs_paras else ""

    body_sections: list[str] = []

    if ms.introduction:
        intro_ps = [
            f"      <p>{txt}</p>"
            for p in ms.introduction
            if (txt := _render_runs_jats(p, valid_figs, valid_eqs, valid_refs).strip())
        ]
        if intro_ps:
            body_sections.append(
                '    <sec id="sec-intro" sec-type="intro">\n'
                "      <title>Introduction</title>\n"
                + "\n".join(intro_ps)
                + "\n    </sec>"
            )

    if ms.protocol_sections:
        proto_subsecs: list[str] = []
        for sec in ms.protocol_sections:
            step_items: list[str] = []
            for step in sec.steps:
                notes_xml = "".join(
                    f"\n            <p><bold>{kind}:</bold> "
                    f"{_render_runs_jats(nruns, valid_figs, valid_eqs, valid_refs)}</p>"
                    for kind, nruns in step.notes
                )
                sub_xml = ""
                if step.substeps:
                    sub_items = []
                    for sub in step.substeps:
                        sub_notes = "".join(
                            f"\n                <p><bold>{kind}:</bold> "
                            f"{_render_runs_jats(nruns, valid_figs, valid_eqs, valid_refs)}</p>"
                            for kind, nruns in sub.notes
                        )
                        sub_items.append(
                            "              <list-item>\n"
                            f"                <label>{encode_scientific_xml(sub.number)}</label>\n"
                            f"                <p>{_render_runs_jats(sub.runs, valid_figs, valid_eqs, valid_refs)}</p>"
                            f"{sub_notes}\n"
                            "              </list-item>"
                        )
                    sub_xml = '\n            <list list-type="order">\n' + "\n".join(sub_items) + "\n            </list>"
                step_items.append(
                    "          <list-item>\n"
                    f"            <label>{encode_scientific_xml(step.number)}</label>\n"
                    f"            <p>{_render_runs_jats(step.runs, valid_figs, valid_eqs, valid_refs)}</p>"
                    f"{notes_xml}{sub_xml}\n"
                    "          </list-item>"
                )
            list_xml = (
                '        <list list-type="order">\n' + "\n".join(step_items) + "\n        </list>\n"
                if step_items
                else ""
            )
            proto_subsecs.append(
                f'      <sec id="sec-proto-{sec.number}">\n'
                f"        <title>{encode_scientific_xml(sec.number)}. {encode_scientific_xml(sec.title)}</title>\n"
                + list_xml
                + "      </sec>"
            )

        # JATS DTD forbids block elements after child <sec>; wrap formulas in a child <sec>.
        eq_xml = ""
        if ms.formulas:
            eq_blocks = []
            for eq in ms.formulas:
                mml = _build_mathml_for_formula(eq.tex, eq.id)
                # PMC StyleChecker requires a complete LaTeX document inside <tex-math>.
                full_latex = (
                    "\\documentclass{article}\n"
                    "\\usepackage{amsmath}\n"
                    "\\begin{document}\n"
                    f"$${eq.tex}$$\n"
                    "\\end{document}"
                )
                eq_blocks.append(
                    f"        <p>{encode_scientific_xml(eq.description)}:\n"
                    f'          <disp-formula id="{eq.id}">\n'
                    f"            <label>{encode_scientific_xml(eq.label)}</label>\n"
                    "            <alternatives>\n"
                    f"              {mml}\n"
                    f'              <tex-math id="tex-{eq.id}"><![CDATA[{full_latex}]]></tex-math>\n'
                    "            </alternatives>\n"
                    "          </disp-formula>\n"
                    "        </p>"
                )
            eq_xml = (
                '\n      <sec id="sec-equations">\n'
                "        <title>Equations</title>\n"
                + "\n".join(eq_blocks)
                + "\n      </sec>"
            )

        body_sections.append(
            '    <sec id="sec-protocol" sec-type="methods">\n'
            "      <title>Protocol</title>\n"
            + "\n".join(proto_subsecs)
            + eq_xml
            + "\n    </sec>"
        )

    if ms.representative_results or ms.figures or ms.materials or ms.tables:
        res_parts: list[str] = []
        for p in ms.representative_results:
            cleaned_runs = [
                TextRun(
                    text=re.sub(r"\s*\[Place Figure \d+ here\]", "", r.text),
                    bold=r.bold,
                    italic=r.italic,
                    subscript=r.subscript,
                    superscript=r.superscript,
                )
                for r in p
            ]
            txt = _render_runs_jats(cleaned_runs, valid_figs, valid_eqs, valid_refs).strip()
            if txt:
                res_parts.append(f"      <p>{txt}</p>")

        for fig in ms.figures:
            href = fig.web_filename or fig.source_filename or f"{fig.id}.jpg"
            cap_xml = _render_runs_jats(fig.caption_runs, valid_figs, valid_eqs, valid_refs).strip()
            cap_p = f"<p>{cap_xml}</p>" if cap_xml else ""
            alt_xml = f"<alt-text>{encode_scientific_xml(fig.alt_text)}</alt-text>" if fig.alt_text else ""
            res_parts.append(
                f'      <fig id="{fig.id}" position="float">\n'
                f"        <label>{encode_scientific_xml(fig.label)}</label>\n"
                f"        <caption><title>{encode_scientific_xml(fig.title)}</title>{cap_p}</caption>\n"
                f'        <graphic xlink:href="{encode_scientific_xml(href)}">{alt_xml}</graphic>\n'
                "      </fig>"
            )

        if ms.materials:
            mat_rows = "\n".join(
                "            <tr>"
                f"<td>{encode_scientific_xml(m.name)}</td>"
                f"<td>{encode_scientific_xml(m.company)}</td>"
                f"<td>{encode_scientific_xml(m.catalog_number)}</td>"
                f"<td>{encode_scientific_xml(m.comments)}</td>"
                "</tr>"
                for m in ms.materials
            )
            res_parts.append(
                '      <table-wrap id="tbl1" position="float">\n'
                "        <label>Table of Materials</label>\n"
                "        <caption><title>Materials and Reagents</title></caption>\n"
                "        <table>\n"
                "          <thead>\n"
                "            <tr><th>Name</th><th>Company</th><th>Catalog Number</th><th>Comments</th></tr>\n"
                "          </thead>\n"
                "          <tbody>\n"
                f"{mat_rows}\n"
                "          </tbody>\n"
                "        </table>\n"
                "      </table-wrap>"
            )

        for tbl in ms.tables:
            cols = max(len(tbl.headers), max((len(r) for r in tbl.rows), default=1))
            th_cells = "".join(f"<th>{encode_scientific_xml(h)}</th>" for h in (tbl.headers + [""] * cols)[:cols])
            tb_rows = "\n".join(
                "            <tr>"
                + "".join(f"<td>{encode_scientific_xml(c)}</td>" for c in (row + [""] * cols)[:cols])
                + "</tr>"
                for row in tbl.rows
            )
            res_parts.append(
                f'      <table-wrap id="{encode_scientific_xml(tbl.id)}" position="float">\n'
                f"        <label>{encode_scientific_xml(tbl.label)}</label>\n"
                f"        <caption><title>{encode_scientific_xml(tbl.title)}</title></caption>\n"
                "        <table>\n"
                f"          <thead><tr>{th_cells}</tr></thead>\n"
                f"          <tbody>\n{tb_rows}\n          </tbody>\n"
                "        </table>\n"
                "      </table-wrap>"
            )

        if res_parts:
            body_sections.append(
                '    <sec id="sec-results" sec-type="results">\n'
                "      <title>Representative Results</title>\n"
                + "\n".join(res_parts)
                + "\n    </sec>"
            )

    if ms.discussion:
        disc_ps = [
            f"      <p>{txt}</p>"
            for p in ms.discussion
            if (txt := _render_runs_jats(p, valid_figs, valid_eqs, valid_refs).strip())
        ]
        if disc_ps:
            body_sections.append(
                '    <sec id="sec-discussion" sec-type="discussion">\n'
                "      <title>Discussion</title>\n"
                + "\n".join(disc_ps)
                + "\n    </sec>"
            )

    back_parts: list[str] = []
    if ms.acknowledgments:
        ack_txt = _render_runs_jats(ms.acknowledgments, valid_figs, valid_eqs, valid_refs, link_refs=False).strip()
        if ack_txt:
            back_parts.append(
                "    <ack>\n"
                "      <title>Acknowledgments</title>\n"
                f"      <p>{ack_txt}</p>\n"
                "    </ack>"
            )
    if ms.disclosures:
        dis_txt = _render_runs_jats(ms.disclosures, valid_figs, valid_eqs, valid_refs, link_refs=False).strip()
        if dis_txt:
            back_parts.append(
                '    <notes notes-type="COI-statement">\n'
                "      <title>Disclosures</title>\n"
                f"      <p>{dis_txt}</p>\n"
                "    </notes>"
            )
    if ms.references:
        refs_xml = "\n".join(_render_citation_xml(r) for r in ms.references)
        back_parts.append(
            "    <ref-list>\n"
            "      <title>References</title>\n"
            f"{refs_xml}\n"
            "    </ref-list>"
        )
    if ms.footnotes:
        fn_items = "\n".join(
            f'      <fn id="fn{idx}"><label>{idx}</label><p>{encode_scientific_xml(fn)}</p></fn>'
            for idx, fn in enumerate(ms.footnotes, start=1)
            if fn.strip()
        )
        if fn_items:
            back_parts.append(f"    <fn-group>\n{fn_items}\n    </fn-group>")

    back_xml = "  <back>\n" + "\n".join(back_parts) + "\n  </back>\n" if back_parts else ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"{JATS_DOCTYPE}\n"
        '<article article-type="methods-article" xml:lang="en" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:mml="http://www.w3.org/1998/Math/MathML">\n'
        "  <front>\n"
        "    <journal-meta>\n"
        '      <journal-id journal-id-type="nlm-ta">J Vis Exp</journal-id>\n'
        '      <journal-id journal-id-type="iso-abbrev">J Vis Exp</journal-id>\n'
        '      <journal-id journal-id-type="publisher-id">JoVE</journal-id>\n'
        "      <journal-title-group>\n"
        "        <journal-title>Journal of Visualized Experiments</journal-title>\n"
        "      </journal-title-group>\n"
        '      <issn pub-type="epub">1940-087X</issn>\n'
        "      <publisher>\n"
        "        <publisher-name>MyJoVE Corporation</publisher-name>\n"
        "      </publisher>\n"
        "    </journal-meta>\n"
        "    <article-meta>\n"
        f'      <article-id pub-id-type="publisher-id">{encode_scientific_xml(ms.publisher_id)}</article-id>\n'
        f'      <article-id pub-id-type="doi">{encode_scientific_xml(ms.doi)}</article-id>\n'
        "      <article-categories>\n"
        '        <subj-group subj-group-type="heading">\n'
        f"          <subject>{encode_scientific_xml(ms.subject_area)}</subject>\n"
        "        </subj-group>\n"
        "      </article-categories>\n"
        "      <title-group>\n"
        f"        <article-title>{encode_scientific_xml(ms.title)}</article-title>\n"
        "      </title-group>\n"
        + contrib_group_xml
        + author_notes_xml
        + f'      <pub-date date-type="pub" publication-format="electronic" iso-8601-date="{encode_scientific_xml(ms.pub_date)}">\n'
        f"        <day>{day}</day>\n"
        f"        <month>{month}</month>\n"
        f"        <year>{year}</year>\n"
        "      </pub-date>\n"
        f"      <elocation-id>e{encode_scientific_xml(ms.publisher_id.split('-')[0])}</elocation-id>\n"
        "      <permissions>\n"
        f"        <copyright-statement>Copyright &#x00A9; {year}, Journal of Visualized Experiments</copyright-statement>\n"
        f"        <copyright-year>{year}</copyright-year>\n"
        "      </permissions>\n"
        + abstract_xml
        + kwd_xml
        + "    </article-meta>\n"
        "  </front>\n"
        "  <body>\n"
        + "\n".join(body_sections)
        + "\n  </body>\n"
        + back_xml
        + "</article>\n"
    )
