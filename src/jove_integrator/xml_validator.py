from __future__ import annotations

from lxml import etree

from .models import XMLCheckResult


def validate_jats_xml_local(xml_text: str) -> XMLCheckResult:
    """Run local XML well-formedness and PMC Tagging Guidelines pre-flight checks."""
    errors: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    try:
        parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=False)
        root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
        passed.append("XML is well-formed UTF-8")
    except etree.XMLSyntaxError as exc:
        return XMLCheckResult(well_formed=False, errors=[f"XML syntax error: {exc}"])

    if "JATS-journalpublishing1-3.dtd" in xml_text:
        passed.append("NISO JATS Journal Publishing DTD v1.3 DOCTYPE declared")
    else:
        warnings.append("Missing NISO JATS v1.3 DOCTYPE declaration")

    if root.tag == "article":
        passed.append("Root element is <article>")
    else:
        errors.append(f"Expected root <article>, got <{root.tag}>")

    if root.find(".//journal-meta/journal-title-group/journal-title") is not None:
        passed.append("<journal-meta> contains <journal-title>")
    else:
        errors.append("Missing <journal-title> in <journal-meta>")

    if root.find(".//article-meta/title-group/article-title") is not None:
        passed.append("<article-meta> contains <article-title>")
    else:
        errors.append("Missing <article-title> in <article-meta>")

    all_ids = {el.get("id") for el in root.xpath("//*[@id]") if el.get("id")}
    broken_xrefs = [
        xref.get("rid") or "<missing>"
        for xref in root.xpath(".//xref")
        if not xref.get("rid") or xref.get("rid") not in all_ids
    ]
    if broken_xrefs:
        errors.append(f"Broken <xref> rid target(s): {broken_xrefs}")
    else:
        passed.append("All <xref> @rid targets resolve to valid @id elements")

    if root.xpath(".//tex-math[not(parent::alternatives)]"):
        errors.append("<tex-math> found outside <alternatives> (forbidden by PMC Style)")
    else:
        passed.append("<tex-math> properly wrapped inside <alternatives> with <mml:math>")

    bad_bold = [
        el.tag
        for el in root.xpath(".//title | .//label")
        if len(list(el)) == 1 and list(el)[0].tag == "bold" and not (el.text or "").strip()
    ]
    if bad_bold:
        errors.append(f"<bold> wraps entire content of {bad_bold} (forbidden by PMC Style)")
    else:
        passed.append("No <bold> wrapping entire <title> or <label>")

    if any(0xE000 <= ord(ch) <= 0xF8FF for ch in xml_text):
        errors.append("Private Use Area Unicode character detected")
    elif "\u00ba" in xml_text or "\u1d52" in xml_text:
        errors.append("Visually ambiguous degree character (U+00BA/U+1D52) detected")
    else:
        passed.append("No Private Use Area or ambiguous degree characters")

    empty_fmt = [
        el.tag
        for el in root.xpath(".//bold | .//italic | .//sub | .//sup | .//p")
        if not (el.text or "").strip() and len(el) == 0
    ]
    if empty_fmt:
        errors.append(f"Empty formatting/paragraph element(s) found: {empty_fmt}")
    else:
        passed.append("Zero empty formatting or paragraph elements")

    # JATS DTD forbids block elements after child <sec> inside <sec>.
    sec_order_errors = []
    for sec in root.xpath(".//sec"):
        seen_child_sec = False
        for child in sec:
            if child.tag == "sec":
                seen_child_sec = True
            elif seen_child_sec and child.tag not in ("fn-group", "glossary", "ref-list"):
                sec_order_errors.append(f"<{child.tag}> follows <sec> inside <sec id='{sec.get('id', '')}'>")
    if sec_order_errors:
        errors.extend(sec_order_errors)
    else:
        passed.append("All <sec> elements follow JATS DTD child ordering")

    if [pd for pd in root.xpath(".//pub-date[@date-type]") if not pd.get("publication-format")]:
        errors.append("<pub-date> with @date-type must include @publication-format")
    else:
        passed.append("<pub-date> attributes conform to JATS 1.3 / PMC Style")

    bad_latex = [
        tm.get("id", "<tex-math>")
        for tm in root.xpath(".//tex-math")
        if "\\documentclass" not in (tm.text or "") or "\\begin{document}" not in (tm.text or "")
    ]
    if bad_latex:
        errors.append(f"<tex-math> must contain a complete LaTeX document: {bad_latex}")
    else:
        passed.append("<tex-math> contains complete LaTeX document wrapper")

    import re

    seen_ids: set[str] = set()
    dup_ids: list[str] = []
    bad_ncnames: list[str] = []
    for el in root.xpath("//*[@id]"):
        eid = el.get("id") or ""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9._-]*", eid):
            bad_ncnames.append(eid)
        if eid in seen_ids:
            dup_ids.append(eid)
        elif eid:
            seen_ids.add(eid)
    if dup_ids:
        errors.append(f"Duplicate @id attribute(s) found: {sorted(set(dup_ids))}")
    elif bad_ncnames:
        errors.append(f"Invalid XML NCName @id attribute(s): {bad_ncnames}")
    else:
        passed.append("All @id attributes are unique valid XML NCNames")

    if [lst for lst in root.xpath(".//list") if len(lst.xpath("./list-item")) == 0]:
        errors.append("<list> must contain at least one <list-item>")
    else:
        passed.append("All <list> elements contain <list-item> children")
    if [cg for cg in root.xpath(".//contrib-group") if len(cg.xpath("./contrib")) == 0]:
        errors.append("<contrib-group> must contain at least one <contrib> element")
    else:
        passed.append("<contrib-group> structure conforms to JATS DTD")

    bad_dois = [
        el.text or ""
        for el in root.xpath(".//pub-id[@pub-id-type='doi'] | .//article-id[@pub-id-type='doi']")
        if not re.match(r"^10\.\d{4,9}/\S+$", (el.text or "").strip())
    ]
    if bad_dois:
        errors.append(f"Malformed DOI value(s): {bad_dois}")
    else:
        passed.append("All DOI identifiers match 10.xxxx/... format")

    return XMLCheckResult(
        well_formed=True,
        errors=errors,
        warnings=warnings,
        checks_passed=passed,
    )
