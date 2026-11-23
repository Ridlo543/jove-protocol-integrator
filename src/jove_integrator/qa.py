from __future__ import annotations

import re
from typing import Callable

from .models import Manuscript, QAFinding, SectionReadiness, TextRun

LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}
INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00ad]")
PLUSMINUS_RE = re.compile(r"(\d+(?:\.\d+)?(?:\s*[a-zA-Z°µΩ%]+)?)\s*\+/-\s*(\d+(?:\.\d+)?)")
LATIN_MICRO_RE = re.compile(r"(\d+(?:\.\d+)?)\s*u([LMgms])\b")
GREEK_MU_UNIT_RE = re.compile(r"\u03bc([LMgms])\b")
NO_SPACE_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)(°C|µL|µM|µg|µm|µs|mL|mM|mg|kg|cm|mm|nm|GHz|MHz|kHz|Hz|min)\b"
)
CARET_SUP_RE = re.compile(r"\b(10)\^(-?\d+)\b")

RPM_RE = re.compile(r"\b([\d,]+)\s*rpm\b", re.IGNORECASE)
LOST_SUP_RE = re.compile(r"\b(\d+(?:\.\d+)?\s*[x×]\s*10)([4-9])\s+(cells|CFU|copies|pfu|particles)\b", re.IGNORECASE)
PERCENT_BASIS_RE = re.compile(r"\b(\d+(?:\.\d+)?%)\s+(?!\((?:w/v|v/v|w/w)\))([A-Za-z][A-Za-z0-9\-]+)")
PERCENT_REAGENT_TERMS = {
    "triton", "tween", "bsa", "fbs", "fcs", "sds", "pfa", "dmso", "pbs", "tbs", "tbst", "pbst",
    "edta", "egta", "ethanol", "methanol", "isopropanol", "propanol", "acetone", "glycerol",
    "sucrose", "glucose", "agarose", "acrylamide", "bisacrylamide", "formalin", "paraformaldehyde",
    "glutaraldehyde", "milk", "serum", "albumin", "buffer", "solution", "gel", "peroxide",
    "bleach", "acetic", "formic", "trichloroacetic", "hydrochloric", "sulfuric", "nitric",
    "sodium", "potassium", "calcium", "magnesium", "ammonium", "urea", "dextran", "ficoll",
    "percoll", "matrigel", "collagen", "gelatin", "casein", "peptone", "tryptone", "yeast",
}
CHEM_FORMULA_TOKEN_RE = re.compile(r"^(?:[A-Z][a-z]?\d+)+[A-Za-z0-9]*$")
VAGUE_COND_RE = re.compile(r"\b(room temperature|overnight)\b", re.IGNORECASE)
GREEK_HOMOGLYPH_RE = re.compile(r"\b(a-MEM|b-actin|b-mercaptoethanol|TNF-a|g-globulin)\b")
AFFIL_ABBREV_RE = re.compile(r"\b(Dept\.|Univ\.|Inst\.|Lab\.|Med\.|Ctr\.)")

SPECIES_RE = re.compile(
    r"\b([A-Z]\.\s+(?:coli|elegans|aureus|cerevisiae|subtilis)|Escherichia coli|Caenorhabditis elegans)\b"
)
CHEM_SUB_RE = re.compile(r"\b(H2O2|CO2|H2O|CaCl2|MgCl2|Na2HPO4|NH4Cl|S11|S21|S12|S22)\b")


def _split_run(
    run: TextRun,
    pattern: re.Pattern[str],
    builder: Callable[[re.Match[str], TextRun], list[TextRun]],
) -> list[TextRun]:
    if not run.text:
        return []
    out: list[TextRun] = []
    pos = 0
    for m in pattern.finditer(run.text):
        if m.start() > pos:
            out.append(
                TextRun(
                    text=run.text[pos : m.start()],
                    bold=run.bold,
                    italic=run.italic,
                    subscript=run.subscript,
                    superscript=run.superscript,
                )
            )
        out.extend(builder(m, run))
        pos = m.end()
    if pos < len(run.text):
        out.append(
            TextRun(
                text=run.text[pos:],
                bold=run.bold,
                italic=run.italic,
                subscript=run.subscript,
                superscript=run.superscript,
            )
        )
    return out or [run]


def _apply_deterministic_text_fixes(text: str, location: str, findings: list[QAFinding]) -> str:
    def _record(rule_id: str, category: str, msg: str, before: str, after: str, ref: str, strip_vals: bool = True) -> None:
        findings.append(
            QAFinding(
                rule_id=rule_id,
                severity="fixed",
                category=category,
                location=location,
                message=msg,
                before=before.strip() if strip_vals else before,
                after=after.strip() if strip_vals else after,
                guideline_ref=ref,
                auto_fixed=True,
                confidence="deterministic",
            )
        )

    if INVISIBLE_CHARS_RE.search(text) or "\u00a0" in text:
        before = text
        text = INVISIBLE_CHARS_RE.sub("", text).replace("\u00a0", " ")
        if text != before:
            _record(
                "PMC-INVISIBLE-CHARS",
                "Character Entities",
                "Stripped zero-width/soft-hyphen characters and normalized non-breaking spaces.",
                repr(before),
                repr(text),
                "PMC genprac: Clean UTF-8 text",
                strip_vals=False,
            )

    if any(lig in text for lig in LIGATURE_MAP):
        before = text
        for lig, repl in LIGATURE_MAP.items():
            text = text.replace(lig, repl)
        _record(
            "PDF-LIGATURES",
            "Character Entities",
            "Expanded PDF copy-paste ligature glyph(s) (fi/fl/ff) to standard ASCII letters.",
            before,
            text,
            "JoVE Word Cleanup / Full-Text Searchability",
        )

    if "\u00ba" in text or "\u1d52" in text:
        before = text
        text = text.replace("\u00ba", "\u00b0").replace("\u1d52", "\u00b0")
        _record(
            "JATS4R-DEGREE",
            "Character Entities",
            "Replaced visually similar ordinal/modifier character (U+00BA/U+1D52) with true degree sign (U+00B0).",
            before,
            text,
            "PMC genprac / JATS4R Special Characters",
        )

    pua_chars = [ch for ch in text if 0xE000 <= ord(ch) <= 0xF8FF]
    if pua_chars:
        before = text
        text = "".join(ch for ch in text if not (0xE000 <= ord(ch) <= 0xF8FF))
        _record(
            "PMC-PUA",
            "Character Entities",
            f"Removed {len(pua_chars)} forbidden Unicode Private Use Area character(s).",
            before,
            text,
            "PMC genprac: No Private Use Area characters",
        )

    if any(sym in text for sym in ("™", "®", "©")):
        before = text
        text = text.replace("™", "").replace("®", "").replace("©", "")
        _record(
            "JOVE-TRADEMARK",
            "Editorial Style",
            "Removed trademark/registered/copyright symbol (™/®/©) from manuscript body text.",
            before,
            text,
            "JoVE Instructions for Authors: Protocol Style",
        )

    if PLUSMINUS_RE.search(text):
        before = text
        text = PLUSMINUS_RE.sub(r"\1 ± \2", text)
        _record(
            "JOVE-PLUSMINUS",
            "Character Entities",
            "Normalized ASCII '+/-' tolerance notation to Unicode plus-minus sign (±, U+00B1).",
            before,
            text,
            "PMC genprac / Mathematical Notations",
        )

    if LATIN_MICRO_RE.search(text) or GREEK_MU_UNIT_RE.search(text):
        before = text
        text = LATIN_MICRO_RE.sub(r"\1 µ\2", text)
        text = GREEK_MU_UNIT_RE.sub("\u00b5\\1", text)
        if text != before:
            _record(
                "JOVE-MICRO-PREFIX",
                "Character Entities",
                "Normalized Latin 'u' or Greek mu (U+03BC) in SI unit prefix to micro sign (µ, U+00B5).",
                before,
                text,
                "PMC genprac / JoVE SI Units",
            )

    if NO_SPACE_UNIT_RE.search(text):
        before = text
        text = NO_SPACE_UNIT_RE.sub(r"\1 \2", text)
        _record(
            "JOVE-SI-SPACING",
            "SI Units & Formatting",
            "Inserted required space between numeric value and SI unit.",
            before,
            text,
            "JoVE Instructions for Authors: Units & Measurements",
        )

    return text


def _collect_review_warnings_in_text(text: str, location: str, findings: list[QAFinding]) -> None:
    for m in RPM_RE.finditer(text):
        rpm_val = m.group(1).replace(",", "")
        findings.append(
            QAFinding(
                rule_id="JOVE-CENTRIFUGE-RPM",
                severity="warning",
                category="SI Units & Formatting",
                location=location,
                message=f"Centrifugal speed '{m.group(0)}' uses rpm; JoVE requires relative centrifugal force (x g), which depends on rotor radius.",
                before=m.group(0),
                after="Convert via RCF = 1.118e-6 * r(mm) * rpm^2",
                guideline_ref="JoVE Instructions for Authors: Centrifugation in x g",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query=f"Please confirm the centrifuge rotor radius (mm) or exact relative centrifugal force (x g) for '{m.group(0)}' in {location}.",
                review_tool=f"rcf_calculator:{rpm_val}",
            )
        )

    for m in LOST_SUP_RE.finditer(text):
        findings.append(
            QAFinding(
                rule_id="JOVE-LOST-SUPERSCRIPT",
                severity="warning",
                category="Scientific Markup",
                location=location,
                message=f"'{m.group(0)}' looks like a flattened scientific exponent (e.g. 10^{m.group(2)}). Not auto-fixed to avoid altering literal counts.",
                before=m.group(0),
                after=f"{m.group(1)}<sup>{m.group(2)}</sup> {m.group(3)}",
                guideline_ref="JoVE QA: Lost Superscript Detection",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query=f"In {location}, please confirm whether '{m.group(0)}' should be formatted as 10^{m.group(2)} {m.group(3)}.",
            )
        )

    for m in PERCENT_BASIS_RE.finditer(text):
        token = m.group(2)
        if token.lower() not in PERCENT_REAGENT_TERMS and not CHEM_FORMULA_TOKEN_RE.match(token):
            continue
        findings.append(
            QAFinding(
                rule_id="JOVE-PERCENT-BASIS",
                severity="warning",
                category="SI Units & Formatting",
                location=location,
                message=f"Percentage concentration '{m.group(0)}' omits (w/v) or (v/v) basis.",
                before=m.group(0),
                after=f"{m.group(1)} (v/v) or (w/v) {m.group(2)}",
                guideline_ref="JoVE Instructions for Authors: Solution Concentrations",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query=f"In {location}, please specify whether '{m.group(0)}' is (w/v) or (v/v).",
            )
        )

    for m in VAGUE_COND_RE.finditer(text):
        if m.group(1).lower() == "room temperature" and re.search(r"°C", text[m.end() : m.end() + 20]):
            continue
        findings.append(
            QAFinding(
                rule_id="JOVE-VAGUE-CONDITION",
                severity="warning",
                category="Protocol Reproducibility",
                location=location,
                message=f"Vague condition '{m.group(1)}' lacks explicit numeric range (e.g. 20-25 °C or 12-16 h).",
                before=m.group(1),
                after="Specify exact °C or hours",
                guideline_ref="JoVE Instructions for Authors: Reproducible Conditions",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query=f"In {location}, please replace '{m.group(1)}' with the exact temperature (°C) or duration (h).",
            )
        )

    for m in GREEK_HOMOGLYPH_RE.finditer(text):
        findings.append(
            QAFinding(
                rule_id="JOVE-GREEK-HOMOGLYPH",
                severity="warning",
                category="Character Entities",
                location=location,
                message=f"Term '{m.group(1)}' uses a Latin letter prefix that may require a Greek symbol (α/β/γ).",
                before=m.group(1),
                after="Verify α/β/γ symbol",
                guideline_ref="PMC genprac / JATS4R Greek Characters",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query=f"In {location}, please confirm whether '{m.group(1)}' should use a Greek character (α/β/γ).",
            )
        )


def _apply_markup_splits(runs: list[TextRun], location: str, findings: list[QAFinding]) -> list[TextRun]:
    # 1. Italicize species names
    after_species: list[TextRun] = []
    for r in runs:
        if not r.italic and SPECIES_RE.search(r.text):
            def _make_species(m: re.Match[str], base: TextRun) -> list[TextRun]:
                findings.append(
                    QAFinding(
                        rule_id="JOVE-SPECIES-ITALIC",
                        severity="fixed",
                        category="Scientific Markup",
                        location=location,
                        message=f"Italicized species name '{m.group(1)}'.",
                        before=m.group(1),
                        after=f"<i>{m.group(1)}</i>",
                        guideline_ref="JoVE Instructions for Authors / PMC <italic>",
                        auto_fixed=True,
                        confidence="deterministic",
                    )
                )
                return [TextRun(m.group(1), base.bold, True, base.subscript, base.superscript)]

            after_species.extend(_split_run(r, SPECIES_RE, _make_species))
        else:
            after_species.append(r)

    # 2. Subscript chemical formulas and S-parameters
    after_chem: list[TextRun] = []
    for r in after_species:
        if not r.subscript and CHEM_SUB_RE.search(r.text):
            def _make_chem(m: re.Match[str], base: TextRun) -> list[TextRun]:
                token = m.group(1)
                findings.append(
                    QAFinding(
                        rule_id="JOVE-CHEMICAL-SUB",
                        severity="fixed",
                        category="Scientific Markup",
                        location=location,
                        message=f"Applied <sub> markup to '{token}'.",
                        before=token,
                        after=re.sub(r"(\d+)", r"<sub>\1</sub>", token),
                        guideline_ref="PMC genprac: <sub> for chemical/RF notation",
                        auto_fixed=True,
                        confidence="deterministic",
                    )
                )
                return [
                    TextRun(seg, base.bold, base.italic, seg.isdigit(), base.superscript)
                    for seg in re.split(r"(\d+)", token)
                    if seg
                ]

            after_chem.extend(_split_run(r, CHEM_SUB_RE, _make_chem))
        else:
            after_chem.append(r)

    # 3. Superscript caret notation (10^6 -> 10<sup>6</sup>)
    after_sup: list[TextRun] = []
    for r in after_chem:
        if not r.superscript and CARET_SUP_RE.search(r.text):
            def _make_sup(m: re.Match[str], base: TextRun) -> list[TextRun]:
                findings.append(
                    QAFinding(
                        rule_id="JOVE-CARET-SUP",
                        severity="fixed",
                        category="Scientific Markup",
                        location=location,
                        message=f"Converted caret exponent '{m.group(0)}' to <sup> markup.",
                        before=m.group(0),
                        after=f"{m.group(1)}<sup>{m.group(2)}</sup>",
                        guideline_ref="PMC genprac: <sup> for exponents",
                        auto_fixed=True,
                        confidence="deterministic",
                    )
                )
                return [
                    TextRun(m.group(1), base.bold, base.italic, base.subscript, base.superscript),
                    TextRun(m.group(2), base.bold, base.italic, base.subscript, True),
                ]

            after_sup.extend(_split_run(r, CARET_SUP_RE, _make_sup))
        else:
            after_sup.append(r)

    return after_sup


def _normalize_runs(runs: list[TextRun], location: str, findings: list[QAFinding]) -> list[TextRun]:
    cleaned: list[TextRun] = []
    for r in runs:
        fixed_text = _apply_deterministic_text_fixes(r.text, location, findings)
        cleaned.append(TextRun(fixed_text, r.bold, r.italic, r.subscript, r.superscript))
    joined_for_review = "".join(f"^{r.text}" if r.superscript else r.text for r in cleaned)
    _collect_review_warnings_in_text(joined_for_review, location, findings)
    return _apply_markup_splits(cleaned, location, findings)


def _collect_all_plain_text(ms: Manuscript) -> str:
    chunks = [
        "".join(r.text for r in ms.summary),
        "".join(r.text for r in ms.abstract),
        *["".join(r.text for r in p) for p in ms.introduction],
    ]
    for sec in ms.protocol_sections:
        for st in sec.steps:
            chunks.append(st.plain_text)
            chunks.extend("".join(r.text for r in nr) for _, nr in st.notes)
            for sub in st.substeps:
                chunks.append(sub.plain_text)
                chunks.extend("".join(r.text for r in nr) for _, nr in sub.notes)
    chunks.extend("".join(r.text for r in p) for p in ms.representative_results)
    chunks.extend("".join(r.text for r in p) for p in ms.discussion)
    return "\n".join(chunks)


def _check_protocol_sequence(ms: Manuscript, findings: list[QAFinding]) -> None:
    for sec in ms.protocol_sections:
        expected_minor = 1
        for step in sec.steps:
            parts = step.number.split(".")
            if len(parts) == 2 and parts[1].isdigit():
                actual = int(parts[1])
                if actual != expected_minor:
                    findings.append(
                        QAFinding(
                            rule_id="JOVE-STEP-SEQUENCE",
                            severity="warning",
                            category="Protocol Hierarchy",
                            location=f"Protocol {sec.number}",
                            message=f"Step numbering jump: expected '{sec.number}.{expected_minor}', found '{step.number}'. Not auto-renumbered to preserve step cross-references.",
                            before=step.number,
                            after=f"Verify step {sec.number}.{expected_minor}",
                            guideline_ref="JoVE Instructions for Authors: Protocol Numbering",
                            auto_fixed=False,
                            confidence="heuristic",
                            suggested_query=f"In Protocol section {sec.number}, step '{step.number}' skips '{sec.number}.{expected_minor}'. Please confirm intended numbering.",
                        )
                    )
                expected_minor = actual + 1


def _check_metadata_and_xrefs(ms: Manuscript, findings: list[QAFinding]) -> None:
    if ms.track_changes_count > 0:
        findings.append(
            QAFinding(
                rule_id="WORD-TRACK-CHANGES",
                severity="error",
                category="Word OOXML Hygiene",
                location="Document OOXML",
                message=f"Detected {ms.track_changes_count} unaccepted Word Track Change(s) (w:ins/w:del). Accept or reject all revisions before XML export.",
                guideline_ref="JoVE Word Cleanup: Clean Manuscript",
                auto_fixed=False,
                confidence="blocking",
                suggested_query="Please accept or reject all Track Changes in the Word manuscript and re-upload.",
            )
        )

    if ms.comments_count > 0:
        findings.append(
            QAFinding(
                rule_id="WORD-COMMENTS-OPEN",
                severity="warning",
                category="Word OOXML Hygiene",
                location="Document OOXML",
                message=f"Detected {ms.comments_count} unresolved Word comment(s) in word/comments.xml.",
                guideline_ref="JoVE Word Cleanup: Remove Editorial Comments",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query="Please confirm all Word margin comments have been resolved before publication.",
            )
        )

    if ms.omath_count > 0:
        findings.append(
            QAFinding(
                rule_id="WORD-OMML-EQUATION",
                severity="warning",
                category="Scientific Markup",
                location="Document OOXML",
                message=f"Detected {ms.omath_count} Word Equation Editor (OMML) object(s). Verify MathML/LaTeX conversion before PMC XML export.",
                guideline_ref="PMC genprac: <disp-formula> / MathML",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query="Please verify all Word Equation Editor formulas render accurately in MathML/LaTeX.",
            )
        )

    if ms.duplicate_ref_numbers:
        findings.append(
            QAFinding(
                rule_id="JOVE-REF-DUPLICATE-NUM",
                severity="warning",
                category="Cross-References",
                location="References",
                message=f"Duplicate reference number(s) {sorted(set(ms.duplicate_ref_numbers))} detected in Word manuscript; assigned unique sequential XML IDs.",
                before=str(ms.duplicate_ref_numbers),
                after="Sequential unique numbering",
                guideline_ref="JoVE Instructions for Authors / PMC unique @id",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query=f"Duplicate reference number(s) {sorted(set(ms.duplicate_ref_numbers))} found in References. Please confirm intended numbering.",
            )
        )

    if len(ms.title) > 150:
        findings.append(
            QAFinding(
                rule_id="JOVE-TITLE-LEN",
                severity="warning",
                category="Manuscript Structure",
                location="Title",
                message=f"Title is {len(ms.title)} characters (JoVE guideline max: 150 characters).",
                before=f"{len(ms.title)} chars",
                after="<= 150 chars",
                guideline_ref="JoVE Instructions for Authors: Title",
                auto_fixed=False,
                confidence="heuristic",
            )
        )

    if ms.authors and not any(a.is_corresponding and a.email for a in ms.authors):
        findings.append(
            QAFinding(
                rule_id="JOVE-CORRESP-MISSING",
                severity="error",
                category="Author Metadata",
                location="Authors & Affiliations",
                message="Missing corresponding author email address.",
                guideline_ref="JoVE Instructions for Authors / PMC <corresp>",
                auto_fixed=False,
                confidence="blocking",
                suggested_query="Please provide the institutional email address for the corresponding author.",
            )
        )

    aff_ids = {a.id for a in ms.affiliations}
    for aff in ms.affiliations:
        if AFFIL_ABBREV_RE.search(aff.institution):
            findings.append(
                QAFinding(
                    rule_id="JOVE-AFFIL-ABBREV",
                    severity="warning",
                    category="Author Metadata",
                    location=f"Affiliation {aff.label}",
                    message=f"Affiliation '{aff.institution}' contains abbreviation(s); JoVE requires full spelled-out department and institution names.",
                    before=aff.institution,
                    after="Spell out Dept./Univ./Inst.",
                    guideline_ref="JoVE Instructions for Authors: Affiliations",
                    auto_fixed=False,
                    confidence="heuristic",
                    suggested_query=f"Please provide the full, unabbreviated institution name for Affiliation {aff.label}: '{aff.institution}'.",
                )
            )

    for author in ms.authors:
        for aid in author.affiliation_ids:
            if aid not in aff_ids:
                findings.append(
                    QAFinding(
                        rule_id="PMC-AFF-XREF",
                        severity="error",
                        category="Author Metadata",
                        location=f"Author {author.given_names} {author.surname}",
                        message=f"Author references missing affiliation '{aid}'.",
                        guideline_ref="PMC Document Objects: Author/Affiliation",
                        auto_fixed=False,
                        confidence="blocking",
                    )
                )

    if ms.materials:
        original_names = [m.name for m in ms.materials]
        sorted_materials = sorted(ms.materials, key=lambda m: m.name.lower())
        sorted_names = [m.name for m in sorted_materials]
        if original_names != sorted_names:
            ms.materials = sorted_materials
            findings.append(
                QAFinding(
                    rule_id="JOVE-MATERIALS-SORT",
                    severity="fixed",
                    category="Table of Materials",
                    location="Table of Materials",
                    message="Sorted Table of Materials alphabetically by reagent/equipment name.",
                    before=" -> ".join(original_names),
                    after=" -> ".join(sorted_names),
                    guideline_ref="JoVE Instructions for Authors: Table of Materials",
                    auto_fixed=True,
                    confidence="deterministic",
                )
            )
        for item in ms.materials:
            if not item.catalog_number.strip() or item.catalog_number.strip().upper() in ("N/A", "TBD", "NONE"):
                findings.append(
                    QAFinding(
                        rule_id="JOVE-MATERIALS-INCOMPLETE",
                        severity="warning",
                        category="Table of Materials",
                        location=f"Material: {item.name}",
                        message=f"Material '{item.name}' is missing a valid vendor catalog number.",
                        before=item.catalog_number or "<empty>",
                        after="Provide catalog #",
                        guideline_ref="JoVE Instructions for Authors: Table of Materials",
                        auto_fixed=False,
                        confidence="heuristic",
                        suggested_query=f"Please provide the vendor catalog number for '{item.name}' ({item.company}).",
                    )
                )

    full_text = _collect_all_plain_text(ms)
    fig_ids = {f.id for f in ms.figures}
    for m in re.finditer(r"\bFigure\s+(\d+)\b", full_text):
        if f"fig{m.group(1)}" not in fig_ids:
            findings.append(
                QAFinding(
                    rule_id="PMC-XREF-FIG",
                    severity="error",
                    category="Cross-References",
                    location="Body Text",
                    message=f"Text cites 'Figure {m.group(1)}' but no matching figure legend exists.",
                    guideline_ref="PMC genprac: <xref> target integrity",
                    auto_fixed=False,
                    confidence="blocking",
                )
            )

    eq_ids = {eq.id for eq in ms.formulas}
    for m in re.finditer(r"\bEquation\s+(\d+)\b", full_text):
        if f"eq{m.group(1)}" not in eq_ids:
            findings.append(
                QAFinding(
                    rule_id="PMC-XREF-EQ",
                    severity="error",
                    category="Cross-References",
                    location="Body Text",
                    message=f"Text cites 'Equation {m.group(1)}' but no matching formula exists.",
                    guideline_ref="PMC genprac: <xref> target integrity",
                    auto_fixed=False,
                    confidence="blocking",
                )
            )

    ref_nums = {r.number for r in ms.references}
    cited_order: list[int] = []
    for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", full_text):
        for num_str in m.group(1).split(","):
            num = int(num_str.strip())
            if num not in cited_order:
                cited_order.append(num)
            if num not in ref_nums:
                findings.append(
                    QAFinding(
                        rule_id="PMC-XREF-BIBR",
                        severity="error",
                        category="Cross-References",
                        location="Body Text",
                        message=f"Citation '[{num}]' has no matching entry in References.",
                        guideline_ref="PMC genprac: <xref ref-type='bibr'> integrity",
                        auto_fixed=False,
                        confidence="blocking",
                    )
                )

    # Also recognize superscript numeric citations (e.g. Nature/bioRxiv style)
    all_run_lists = [
        ms.summary,
        ms.abstract,
        *ms.introduction,
        *ms.representative_results,
        *ms.discussion,
    ]
    for sec in ms.protocol_sections:
        for st in sec.steps:
            all_run_lists.append(st.runs)
            for sub in st.substeps:
                all_run_lists.append(sub.runs)
    for rlist in all_run_lists:
        for r in rlist:
            if r.superscript and re.fullmatch(r"\s*\d+(?:\s*[,\-–]\s*\d+)*\s*", r.text):
                for tok in re.findall(r"\d+", r.text):
                    num = int(tok)
                    if num in ref_nums and num not in cited_order:
                        cited_order.append(num)
    # Also recognize Author-Year citations (e.g. "(Smith, 2024)" or "Smith et al. 2024")
    for ref in ms.references:
        if ref.number in cited_order:
            continue
        first_surname = re.split(r"[\s,]+", ref.authors.strip())[0] if ref.authors else ""
        if len(first_surname) >= 3 and ref.year:
            ay_pat = re.compile(rf"\b{re.escape(first_surname)}\b.{{0,40}}\b{re.escape(ref.year)}\b")
            if ay_pat.search(full_text):
                cited_order.append(ref.number)
    if cited_order and cited_order != sorted(cited_order):
        findings.append(
            QAFinding(
                rule_id="JOVE-REF-ORDER",
                severity="warning",
                category="Cross-References",
                location="Body Text / References",
                message=f"First-appearance citation order is non-sequential ({cited_order}); JoVE numbers references sequentially by first appearance.",
                before=str(cited_order),
                after=str(sorted(cited_order)),
                guideline_ref="JoVE Instructions for Authors: Reference Order",
                auto_fixed=False,
                confidence="heuristic",
                suggested_query=f"Citations appear out of sequential order ({cited_order}). Please confirm reference renumbering.",
            )
        )

    uncited = sorted(ref_nums - set(cited_order))
    if uncited:
        findings.append(
            QAFinding(
                rule_id="JOVE-UNCITED-REF",
                severity="warning",
                category="Cross-References",
                location="References",
                message=f"Reference(s) {uncited} appear in References list without an in-text citation.",
                guideline_ref="JoVE Instructions for Authors: References",
                auto_fixed=False,
                confidence="heuristic",
            )
        )

    if ms.references and len(ms.references) < 10:
        findings.append(
            QAFinding(
                rule_id="JOVE-REF-COUNT",
                severity="warning",
                category="Manuscript Structure",
                location="References",
                message=f"Manuscript has {len(ms.references)} references (JoVE full-article guideline recommends >= 10).",
                before=f"{len(ms.references)} refs",
                after=">= 10 refs",
                guideline_ref="JoVE Instructions for Authors: References",
                auto_fixed=False,
                confidence="heuristic",
            )
        )


def build_readiness_matrix(ms: Manuscript, findings: list[QAFinding]) -> list[SectionReadiness]:
    def _status_for(categories: set[str], fallback_detail: str) -> tuple[str, str]:
        rel = [f for f in findings if f.category in categories]
        errs = [f for f in rel if f.severity == "error"]
        warns = [f for f in rel if f.severity == "warning"]
        fixed = [f for f in rel if f.severity == "fixed"]
        if errs:
            return "fail", f"{len(errs)} blocking error(s)"
        if warns:
            return "review", f"{len(warns)} review item(s), {len(fixed)} auto-fixed"
        if fixed:
            return "pass", f"{len(fixed)} auto-fixed, 0 issues"
        return "pass", fallback_detail

    rows = [
        ("Word OOXML Hygiene", {"Word OOXML Hygiene"}, "Clean .docx, 0 track changes"),
        ("Authors & Affiliations", {"Author Metadata"}, f"{len(ms.authors)} authors, {len(ms.affiliations)} affiliations"),
        ("Units & Entities", {"Character Entities", "SI Units & Formatting", "Scientific Markup"}, "Entities & SI verified"),
        ("Protocol Hierarchy", {"Protocol Hierarchy", "Protocol Reproducibility"}, f"{len(ms.protocol_sections)} section(s)"),
        ("Graphics & Alt-Text", {"Accessibility & Graphics"}, f"{len(ms.figures)} figure(s) verified"),
        ("Table of Materials", {"Table of Materials"}, f"{len(ms.materials)} item(s) sorted A-Z"),
        ("References & XRefs", {"Cross-References", "Manuscript Structure"}, f"{len(ms.references)} reference(s)"),
    ]
    return [
        SectionReadiness(section=name, status=st, detail=det)  # type: ignore[arg-type]
        for name, cats, fallback in rows
        for st, det in [_status_for(cats, fallback)]
    ]


def run_qa_and_normalize(ms: Manuscript) -> list[QAFinding]:
    """Run JoVE + PMC Tagging Guidelines QA checks and apply deterministic normalizations."""
    findings: list[QAFinding] = []

    if ms.summary:
        ms.summary = _normalize_runs(ms.summary, "Summary", findings)
    if ms.abstract:
        ms.abstract = _normalize_runs(ms.abstract, "Abstract", findings)
        abs_words = len("".join(r.text for r in ms.abstract).split())
        if abs_words < 50 or abs_words > 300:
            findings.append(
                QAFinding(
                    rule_id="JOVE-ABSTRACT-WORDS",
                    severity="warning",
                    category="Manuscript Structure",
                    location="Abstract",
                    message=f"Abstract has {abs_words} words (JoVE target range: 150-300 words).",
                    before=f"{abs_words} words",
                    after="150-300 words",
                    guideline_ref="JoVE Instructions for Authors: Abstract",
                    auto_fixed=False,
                    confidence="heuristic",
                )
            )

    for idx, para in enumerate(ms.introduction, start=1):
        ms.introduction[idx - 1] = _normalize_runs(para, f"Introduction ¶{idx}", findings)

    for sec in ms.protocol_sections:
        for step in sec.steps:
            step.runs = _normalize_runs(step.runs, f"Protocol {step.number}", findings)
            for n_idx, (kind, nruns) in enumerate(step.notes):
                step.notes[n_idx] = (kind, _normalize_runs(nruns, f"Protocol {step.number} {kind}", findings))
            for sub in step.substeps:
                sub.runs = _normalize_runs(sub.runs, f"Protocol {sub.number}", findings)
                for n_idx, (kind, nruns) in enumerate(sub.notes):
                    sub.notes[n_idx] = (kind, _normalize_runs(nruns, f"Protocol {sub.number} {kind}", findings))

    for idx, para in enumerate(ms.representative_results, start=1):
        ms.representative_results[idx - 1] = _normalize_runs(para, f"Representative Results ¶{idx}", findings)

    for fig in ms.figures:
        if fig.caption_runs:
            fig.caption_runs = _normalize_runs(fig.caption_runs, f"{fig.label} Legend", findings)
        if not fig.alt_text.strip():
            findings.append(
                QAFinding(
                    rule_id="JOVE-FIG-ALT",
                    severity="error",
                    category="Accessibility & Graphics",
                    location=fig.label,
                    message=f"{fig.label} is missing descriptive alt text for web accessibility.",
                    guideline_ref="JoVE Web Accessibility / HTML5",
                    auto_fixed=False,
                    confidence="blocking",
                )
            )

    for idx, para in enumerate(ms.discussion, start=1):
        ms.discussion[idx - 1] = _normalize_runs(para, f"Discussion ¶{idx}", findings)

    if ms.acknowledgments:
        ms.acknowledgments = _normalize_runs(ms.acknowledgments, "Acknowledgments", findings)
    if ms.disclosures:
        ms.disclosures = _normalize_runs(ms.disclosures, "Disclosures", findings)

    _check_protocol_sequence(ms, findings)
    _check_metadata_and_xrefs(ms, findings)
    return findings
