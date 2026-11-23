from __future__ import annotations

import html
import re
from xml.sax.saxutils import escape

SCIENTIFIC_ENTITY_MAP = {
    "\u00b0": "&#x00B0;",
    "\u00b5": "&#x00B5;",
    "\u03bc": "&#x03BC;",
    "\u03a9": "&#x03A9;",
    "\u00b1": "&#x00B1;",
    "\u00a9": "&#x00A9;",
    "\u00b7": "&#x00B7;",
    "\u03b1": "&#x03B1;",
    "\u03b2": "&#x03B2;",
    "\u03b3": "&#x03B3;",
    "\u2212": "&#x2212;",
    "\u2013": "&#x2013;",
}

FIG_REF_RE = re.compile(r"\bFigure\s+(\d+)\b")
EQ_REF_RE = re.compile(r"\bEquation\s+(\d+)\b")
BIBR_REF_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def encode_scientific_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    for ch, ent in SCIENTIFIC_ENTITY_MAP.items():
        escaped = escaped.replace(ch, ent)
    return escaped


def encode_scientific_xml(text: str) -> str:
    escaped = escape(text)
    for ch, ent in SCIENTIFIC_ENTITY_MAP.items():
        escaped = escaped.replace(ch, ent)
    return escaped


def link_html_refs(encoded_html: str) -> str:
    encoded_html = FIG_REF_RE.sub(r'<a class="jove-xref" href="#fig\1">Figure \1</a>', encoded_html)
    encoded_html = EQ_REF_RE.sub(r'<a class="jove-xref" href="#eq\1">Equation \1</a>', encoded_html)

    def _replace_cite(m: re.Match[str]) -> str:
        nums = [n.strip() for n in m.group(1).split(",")]
        links = ", ".join(f'<a class="jove-cite" href="#ref-{n}">{n}</a>' for n in nums)
        return f"[{links}]"

    return BIBR_REF_RE.sub(_replace_cite, encoded_html)


def link_jats_xrefs(
    xml_fragment: str,
    valid_figs: set[str],
    valid_eqs: set[str],
    valid_refs: set[int],
) -> str:
    def _fig_sub(m: re.Match[str]) -> str:
        fid = f"fig{m.group(1)}"
        return f'<xref ref-type="fig" rid="{fid}">Figure {m.group(1)}</xref>' if fid in valid_figs else m.group(0)

    def _eq_sub(m: re.Match[str]) -> str:
        eid = f"eq{m.group(1)}"
        return (
            f'<xref ref-type="disp-formula" rid="{eid}">Equation {m.group(1)}</xref>'
            if eid in valid_eqs
            else m.group(0)
        )

    def _ref_sub(m: re.Match[str]) -> str:
        nums = [int(n.strip()) for n in m.group(1).split(",")]
        if all(n in valid_refs for n in nums):
            xrefs = ", ".join(f'<xref ref-type="bibr" rid="B{n}">{n}</xref>' for n in nums)
            return f"[{xrefs}]"
        return m.group(0)

    xml_fragment = FIG_REF_RE.sub(_fig_sub, xml_fragment)
    xml_fragment = EQ_REF_RE.sub(_eq_sub, xml_fragment)
    return BIBR_REF_RE.sub(_ref_sub, xml_fragment)
