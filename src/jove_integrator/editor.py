from __future__ import annotations

import difflib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .html_renderer import render_article_html
from .image_prep import prepare_figure_assets
from .jats_builder import build_jats_xml
from .models import Manuscript, MaterialItem, PipelineResult, TextRun
from .qa import build_readiness_matrix, run_qa_and_normalize
from .word_loader import write_clean_docx
from .xml_validator import validate_jats_xml_local


def manuscript_to_plain_lines(ms: Manuscript) -> list[str]:
    """Produce a deterministic line-by-line text snapshot for Before/After diffing."""
    lines: list[str] = [f"TITLE: {ms.title}", f"SUBJECT: {ms.subject_area}", f"DOI: {ms.doi}"]
    for aff in ms.affiliations:
        lines.append(f"AFFILIATION {aff.label}: {aff.institution}")
    if ms.summary:
        lines.append("SUMMARY: " + "".join(r.text for r in ms.summary))
    if ms.abstract:
        lines.append("ABSTRACT: " + "".join(r.text for r in ms.abstract))
    for idx, p in enumerate(ms.introduction, start=1):
        lines.append(f"INTRO {idx}: " + "".join(r.text for r in p))
    for sec in ms.protocol_sections:
        lines.append(f"PROTOCOL {sec.number}: {sec.title}")
        for st in sec.steps:
            lines.append(f"  {st.number} {st.plain_text}")
            for kind, nr in st.notes:
                lines.append(f"    {kind}: " + "".join(r.text for r in nr))
            for sub in st.substeps:
                lines.append(f"    {sub.number} {sub.plain_text}")
                for kind, nr in sub.notes:
                    lines.append(f"      {kind}: " + "".join(r.text for r in nr))
    for idx, p in enumerate(ms.representative_results, start=1):
        lines.append(f"RESULTS {idx}: " + "".join(r.text for r in p))
    for m in ms.materials:
        lines.append(f"MATERIAL: {m.name} | {m.company} | {m.catalog_number} | {m.comments}")
    for idx, p in enumerate(ms.discussion, start=1):
        lines.append(f"DISCUSSION {idx}: " + "".join(r.text for r in p))
    return lines


def compute_manuscript_diff(original_lines: list[str], current_lines: list[str]) -> list[dict[str, str]]:
    """Compute structured line-level changes between original Word extraction and cleaned manuscript."""
    diff_rows: list[dict[str, str]] = []
    for line in difflib.unified_diff(original_lines, current_lines, lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("-"):
            diff_rows.append({"kind": "removed", "text": line[1:]})
        elif line.startswith("+"):
            diff_rows.append({"kind": "added", "text": line[1:]})
    return diff_rows


def _iter_target_run_lists(ms: Manuscript, location: str):
    if location == "Summary":
        yield ms.summary
    elif location == "Abstract":
        yield ms.abstract
    elif location.startswith("Introduction ¶"):
        idx = int(location.split("¶", 1)[1]) - 1
        if 0 <= idx < len(ms.introduction):
            yield ms.introduction[idx]
    elif location.startswith("Representative Results ¶"):
        idx = int(location.split("¶", 1)[1]) - 1
        if 0 <= idx < len(ms.representative_results):
            yield ms.representative_results[idx]
    elif location.startswith("Discussion ¶"):
        idx = int(location.split("¶", 1)[1]) - 1
        if 0 <= idx < len(ms.discussion):
            yield ms.discussion[idx]
    elif location.startswith("Protocol "):
        is_note = location.endswith(" NOTE") or location.endswith(" CAUTION")
        step_num = location.replace("Protocol ", "").replace(" NOTE", "").replace(" CAUTION", "").strip()
        for sec in ms.protocol_sections:
            for st in sec.steps:
                if st.number == step_num:
                    if is_note:
                        for _, nr in st.notes:
                            yield nr
                    else:
                        yield st.runs
                for sub in st.substeps:
                    if sub.number == step_num:
                        if is_note:
                            for _, nr in sub.notes:
                                yield nr
                        else:
                            yield sub.runs


def _replace_in_runs(runs: list[TextRun], pattern: re.Pattern[str], repl_fn) -> bool:
    changed = False
    new_runs: list[TextRun] = []
    for r in runs:
        if not pattern.search(r.text):
            new_runs.append(r)
            continue
        pos = 0
        for m in pattern.finditer(r.text):
            if m.start() > pos:
                new_runs.append(TextRun(r.text[pos : m.start()], r.bold, r.italic, r.subscript, r.superscript))
            new_runs.extend(repl_fn(m, r))
            pos = m.end()
            changed = True
        if pos < len(r.text):
            new_runs.append(TextRun(r.text[pos:], r.bold, r.italic, r.subscript, r.superscript))
    if changed:
        runs[:] = new_runs
    return changed


def apply_review_fix(ms: Manuscript, rule_id: str, location: str, value: str) -> bool:
    """Apply a human-confirmed fix directly into the Manuscript model."""
    value = value.strip()
    if not value:
        return False

    if rule_id == "JOVE-AFFIL-ABBREV" and location.startswith("Affiliation "):
        label = location.replace("Affiliation ", "").strip()
        for aff in ms.affiliations:
            if aff.label == label:
                aff.institution = value
                return True
        return False

    if rule_id == "JOVE-MATERIALS-INCOMPLETE" and location.startswith("Material: "):
        mat_name = location.replace("Material: ", "").strip()
        for item in ms.materials:
            if item.name == mat_name:
                item.catalog_number = value
                return True
        return False

    if rule_id == "JOVE-STEP-SEQUENCE" and location.startswith("Protocol "):
        sec_num = location.replace("Protocol ", "").strip()
        for sec in ms.protocol_sections:
            if sec.number == sec_num:
                for idx, st in enumerate(sec.steps, start=1):
                    st.number = f"{sec.number}.{idx}"
                    for s_idx, sub in enumerate(st.substeps, start=1):
                        sub.number = f"{st.number}.{s_idx}"
                return True
        return False

    if rule_id == "JOVE-FIG-ALT":
        for fig in ms.figures:
            if fig.label == location:
                fig.alt_text = value
                return True
        return False

    applied = False
    for runs in _iter_target_run_lists(ms, location):
        if rule_id == "JOVE-CENTRIFUGE-RPM":
            applied |= _replace_in_runs(
                runs,
                re.compile(r"\b[\d,]+\s*rpm\b", re.IGNORECASE),
                lambda m, base: [TextRun(value, base.bold, base.italic, base.subscript, base.superscript)],
            )
        elif rule_id == "JOVE-LOST-SUPERSCRIPT":
            applied |= _replace_in_runs(
                runs,
                re.compile(r"\b(\d+(?:\.\d+)?\s*[x×]\s*10)([4-9])(\s+(?:cells|CFU|copies|pfu|particles))\b", re.IGNORECASE),
                lambda m, base: [
                    TextRun(m.group(1), base.bold, base.italic, base.subscript, base.superscript),
                    TextRun(m.group(2), base.bold, base.italic, base.subscript, True),
                    TextRun(m.group(3), base.bold, base.italic, base.subscript, base.superscript),
                ],
            )
        elif rule_id == "JOVE-PERCENT-BASIS":
            basis = value if value.startswith("(") else f"({value})"
            applied |= _replace_in_runs(
                runs,
                re.compile(r"\b(\d+(?:\.\d+)?%)\s+(?!\((?:w/v|v/v|w/w)\))"),
                lambda m, base: [TextRun(f"{m.group(1)} {basis} ", base.bold, base.italic, base.subscript, base.superscript)],
            )
        elif rule_id == "JOVE-VAGUE-CONDITION":
            applied |= _replace_in_runs(
                runs,
                re.compile(r"\b(room temperature|overnight)\b", re.IGNORECASE),
                lambda m, base: [TextRun(value, base.bold, base.italic, base.subscript, base.superscript)],
            )
        elif rule_id == "JOVE-GREEK-HOMOGLYPH":
            greek_map = {
                "a-MEM": "α-MEM",
                "b-actin": "β-actin",
                "b-mercaptoethanol": "β-mercaptoethanol",
                "TNF-a": "TNF-α",
                "g-globulin": "γ-globulin",
            }
            applied |= _replace_in_runs(
                runs,
                re.compile(r"\b(a-MEM|b-actin|b-mercaptoethanol|TNF-a|g-globulin)\b"),
                lambda m, base: [
                    TextRun(
                        value if value != "auto" else greek_map.get(m.group(1), m.group(1)),
                        base.bold,
                        base.italic,
                        base.subscript,
                        base.superscript,
                    )
                ],
            )
    return applied


def update_manuscript_fields(ms: Manuscript, updates: dict[str, Any]) -> None:
    """Apply direct editorial edits from the Edit Manuscript form."""
    if "title" in updates and str(updates["title"]).strip():
        ms.title = str(updates["title"]).strip()
    if "subject_area" in updates and str(updates["subject_area"]).strip():
        ms.subject_area = str(updates["subject_area"]).strip()
    if "doi" in updates and str(updates["doi"]).strip():
        ms.doi = str(updates["doi"]).strip()
    if "summary" in updates:
        ms.summary = [TextRun(text=str(updates["summary"]).strip())] if str(updates["summary"]).strip() else []
    if "abstract" in updates:
        ms.abstract = [TextRun(text=str(updates["abstract"]).strip())] if str(updates["abstract"]).strip() else []
    if "affiliations" in updates and isinstance(updates["affiliations"], list):
        for idx, inst in enumerate(updates["affiliations"]):
            if idx < len(ms.affiliations) and str(inst).strip():
                ms.affiliations[idx].institution = str(inst).strip()
    if "materials" in updates and isinstance(updates["materials"], list):
        ms.materials = [
            MaterialItem(
                name=str(m.get("name", "")).strip(),
                company=str(m.get("company", "")).strip(),
                catalog_number=str(m.get("catalog_number", "")).strip(),
                comments=str(m.get("comments", "")).strip(),
            )
            for m in updates["materials"]
            if str(m.get("name", "")).strip()
        ]


def rebuild_from_manuscript(
    ms: Manuscript,
    output_dir: Path,
    stem: str,
    asset_search_dirs: list[Path],
    asset_url_prefix: str = "",
) -> PipelineResult:
    """Re-run QA, image prep, clean .docx, HTML5, and JATS 1.3 XML from an edited Manuscript."""
    output_dir.mkdir(parents=True, exist_ok=True)
    findings = run_qa_and_normalize(ms)
    readiness = build_readiness_matrix(ms, findings)
    image_reports = prepare_figure_assets(ms.figures, search_dirs=asset_search_dirs, output_dir=output_dir)

    clean_docx_path = write_clean_docx(ms, output_dir / f"{stem}_clean.docx")
    html_article = render_article_html(ms, asset_prefix=asset_url_prefix)
    html_path = output_dir / f"{stem}.html"
    html_path.write_text(html_article, encoding="utf-8")

    jats_xml = build_jats_xml(ms)
    xml_path = output_dir / f"{stem}.jats.xml"
    xml_path.write_text(jats_xml, encoding="utf-8")

    xml_check = validate_jats_xml_local(jats_xml)

    report_payload = {
        "source_file": ms.source_filename,
        "title": ms.title,
        "summary_counts": {
            "fixed": sum(1 for f in findings if f.severity == "fixed"),
            "warnings": sum(1 for f in findings if f.severity == "warning"),
            "errors": sum(1 for f in findings if f.severity == "error"),
        },
        "readiness": [asdict(r) for r in readiness],
        "findings": [asdict(f) for f in findings],
        "images": [asdict(r) for r in image_reports],
        "xml_check": asdict(xml_check),
        "artifacts": {
            "clean_docx": str(clean_docx_path),
            "html": str(html_path),
            "jats_xml": str(xml_path),
        },
    }
    report_path = output_dir / f"{stem}_qa_report.json"
    report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return PipelineResult(
        manuscript=ms,
        findings=findings,
        readiness=readiness,
        image_reports=image_reports,
        html_article=html_article,
        jats_xml=jats_xml,
        xml_check=xml_check,
        clean_docx_path=str(clean_docx_path),
        html_path=str(html_path),
        xml_path=str(xml_path),
        report_path=str(report_path),
    )
