from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from .models import (
    Affiliation,
    Author,
    FigureItem,
    FormulaItem,
    Manuscript,
    MaterialItem,
    ProtocolSection,
    ProtocolStep,
    ReferenceItem,
    TableItem,
    TextRun,
)

SECTION_ALIASES = {
    "TITLE": "TITLE",
    "REVIEW TITLE": "TITLE",
    "METADATA": "METADATA",
    "AUTHORS AND AFFILIATIONS": "AUTHORS",
    "AUTHORS": "AUTHORS",
    "SUMMARY": "SUMMARY",
    "ABSTRACT": "ABSTRACT",
    "INTRODUCTION": "INTRODUCTION",
    "BACKGROUND": "INTRODUCTION",
    "RATIONALE": "INTRODUCTION",
    "PROTOCOL": "PROTOCOL",
    "LAB PROTOCOL": "PROTOCOL",
    "FIELD-DATA COLLECTION PROTOCOL": "PROTOCOL",
    "METHODS": "PROTOCOL",
    "MATERIALS AND METHODS": "PROTOCOL",
    "EXPERIMENTAL PROCEDURES": "PROTOCOL",
    "PROCEDURE": "PROTOCOL",
    "EQUATIONS": "EQUATIONS",
    "REPRESENTATIVE RESULTS": "RESULTS",
    "RESULTS": "RESULTS",
    "FIGURE LEGENDS": "FIGURES",
    "FIGURE AND TABLE LEGENDS": "FIGURES",
    "TABLE OF MATERIALS": "MATERIALS",
    "MATERIALS": "MATERIALS",
    "DISCUSSION": "DISCUSSION",
    "ACKNOWLEDGMENTS": "ACKNOWLEDGMENTS",
    "ACKNOWLEDGEMENTS": "ACKNOWLEDGMENTS",
    "AUTHOR CONTRIBUTIONS": "ACKNOWLEDGMENTS",
    "FUNDING": "ACKNOWLEDGMENTS",
    "DISCLOSURES": "DISCLOSURES",
    "CONFLICTS OF INTEREST": "DISCLOSURES",
    "COMPETING INTERESTS": "DISCLOSURES",
    "COMPETING INTEREST STATEMENT": "DISCLOSURES",
    "REFERENCES": "REFERENCES",
    "REFERENCE": "REFERENCES",
    "BIBLIOGRAPHY": "REFERENCES",
    "LITERATURE CITED": "REFERENCES",
    "RESULTS AND DISCUSSION": "DISCUSSION",
    "RESULTS & DISCUSSION": "DISCUSSION",
    "SUPPLEMENTARY METHODS": "PROTOCOL",
    "EXPERIMENTAL": "PROTOCOL",
    "EXPERIMENTAL SECTION": "PROTOCOL",
    "REAGENTS AND MATERIALS": "MATERIALS",
    "REAGENTS": "MATERIALS",
    "EQUIPMENT": "MATERIALS",
}

MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".emf", ".wmf")
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
MAX_DOCX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_ZIP_ENTRIES = 500
MAX_SINGLE_ENTRY_BYTES = 15 * 1024 * 1024
SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=False,
    dtd_validation=False,
)

def convert_doc_to_docx(doc_path: Path, output_dir: Path) -> Path:
    """Convert legacy binary .doc to .docx using Microsoft Word COM or LibreOffice."""
    doc_path = doc_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target_docx = output_dir / f"{doc_path.stem}.docx"

    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore

        pythoncom.CoInitialize()
        word = None
        doc = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(str(doc_path), ReadOnly=True)
            doc.SaveAs2(str(target_docx), FileFormat=16)
            return target_docx
        finally:
            if doc is not None:
                doc.Close(False)
            if word is not None:
                word.Quit()
            pythoncom.CoUninitialize()
    except ImportError:
        pass
    except Exception as exc:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            raise RuntimeError(f"Failed to convert .doc via Word COM: {exc}") from exc

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        import tempfile
        import uuid

        lo_profile = Path(tempfile.gettempdir()) / f"lo_prof_{uuid.uuid4().hex[:8]}"
        try:
            proc = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--norestore",
                    "--invisible",
                    "--nodefault",
                    "--nofirststartwizard",
                    f"-env:UserInstallation={lo_profile.as_uri()}",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(output_dir),
                    str(doc_path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("LibreOffice .doc conversion timed out.") from exc
        finally:
            shutil.rmtree(lo_profile, ignore_errors=True)
        if proc.returncode == 0 and target_docx.exists():
            return target_docx
        raise RuntimeError(f"LibreOffice conversion failed: {proc.stderr or proc.stdout}")

    raise RuntimeError("Cannot convert legacy .doc: neither Microsoft Word COM nor LibreOffice is available.")


def _validate_docx_archive(zf: zipfile.ZipFile) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ValueError(f"Archive exceeds maximum entry count ({MAX_ZIP_ENTRIES}).")
    total_uncompressed = 0
    for info in infos:
        if info.file_size > MAX_SINGLE_ENTRY_BYTES:
            raise ValueError(f"Archive entry '{info.filename}' exceeds {MAX_SINGLE_ENTRY_BYTES // (1024 * 1024)} MB limit.")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise ValueError(f"Uncompressed .docx size exceeds {MAX_DOCX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit.")


def _inspect_ooxml_hazards(
    docx_path: Path,
    media_dir: Path | None = None,
) -> tuple[int, int, list[str], list[str], list[str]]:
    """Count Track Changes, comments, extract embedded media, wp:docPr alt texts, and footnotes/endnotes."""
    track_changes = 0
    comments = 0
    extracted_media: list[str] = []
    docpr_alts: list[str] = []
    footnotes: list[str] = []
    with zipfile.ZipFile(docx_path, "r") as zf:
        _validate_docx_archive(zf)
        names = zf.namelist()
        if "word/document.xml" in names:
            root = etree.fromstring(zf.read("word/document.xml"), parser=SAFE_XML_PARSER)
            ns = {"w": W_NS, "wp": WP_NS}
            track_changes = len(root.xpath(".//w:ins | .//w:del", namespaces=ns))
            for docpr in root.xpath(".//wp:docPr", namespaces=ns):
                alt = (docpr.get("descr") or docpr.get("title") or "").strip()
                docpr_alts.append(alt)
        if "word/comments.xml" in names:
            croot = etree.fromstring(zf.read("word/comments.xml"), parser=SAFE_XML_PARSER)
            comments = len(croot.xpath(".//w:comment", namespaces={"w": W_NS}))
        for note_part, tag_name in (("word/footnotes.xml", "footnote"), ("word/endnotes.xml", "endnote")):
            if note_part in names:
                nroot = etree.fromstring(zf.read(note_part), parser=SAFE_XML_PARSER)
                for note_el in nroot.xpath(f".//w:{tag_name}", namespaces={"w": W_NS}):
                    nid = note_el.get(f"{{{W_NS}}}id") or "0"
                    try:
                        if int(nid) <= 0:
                            continue
                    except ValueError:
                        continue
                    ntxt = "".join(note_el.xpath(".//w:t/text()", namespaces={"w": W_NS})).strip()
                    if ntxt:
                        footnotes.append(ntxt)
        if media_dir is not None:
            for member in sorted(names):
                if member.startswith("word/media/") and Path(member).suffix.lower() in MEDIA_EXTS:
                    media_dir.mkdir(parents=True, exist_ok=True)
                    raw_name = Path(member).name
                    out_name = re.sub(r"[^A-Za-z0-9._-]", "_", raw_name)
                    if not out_name or out_name in (".", ".."):
                        continue
                    (media_dir / out_name).write_bytes(zf.read(member))
                    extracted_media.append(out_name)
    return track_changes, comments, extracted_media, docpr_alts, footnotes

def _get_native_list_level(paragraph: Paragraph) -> int | None:
    ppr = paragraph._element.pPr
    if ppr is None:
        return None
    num_pr = ppr.find(qn("w:numPr"))
    if num_pr is None:
        return None
    ilvl = num_pr.find(qn("w:ilvl"))
    if ilvl is not None and ilvl.get(qn("w:val")) is not None:
        return int(ilvl.get(qn("w:val")))
    return 0


def _extract_run_element(r_el) -> TextRun | None:
    text_parts = [t.text for t in r_el.findall(qn("w:t")) if t.text]
    if r_el.find(qn("w:tab")) is not None:
        text_parts.append(" ")
    txt = "".join(text_parts)
    if not txt:
        return None
    rpr = r_el.find(qn("w:rPr"))
    bold = False
    italic = False
    is_sub = False
    is_sup = False
    if rpr is not None:
        b_el = rpr.find(qn("w:b"))
        bold = b_el is not None and b_el.get(qn("w:val")) not in ("0", "false")
        i_el = rpr.find(qn("w:i"))
        italic = i_el is not None and i_el.get(qn("w:val")) not in ("0", "false")
        va = rpr.find(qn("w:vertAlign"))
        if va is not None:
            val = va.get(qn("w:val"))
            is_sub = val == "subscript"
            is_sup = val == "superscript"
    return TextRun(text=txt, bold=bold, italic=italic, subscript=is_sub, superscript=is_sup)


def _extract_runs(paragraph: Paragraph) -> tuple[list[TextRun], int]:
    """Extract formatted runs including hyperlinks, smartTags, SDTs, and Word OMML (<m:oMath>)."""
    runs: list[TextRun] = []
    omath_count = 0
    container_tags = {qn("w:hyperlink"), qn("w:smartTag"), qn("w:fldSimple"), qn("w:sdt"), qn("w:sdtContent")}

    def _walk(el) -> None:
        nonlocal omath_count
        for child in el.iterchildren():
            if child.tag == qn("w:r"):
                tr = _extract_run_element(child)
                if tr is not None:
                    runs.append(tr)
            elif child.tag in (f"{{{M_NS}}}oMath", f"{{{M_NS}}}oMathPara"):
                omath_count += 1
                math_txt = "".join(t.text for t in child.xpath(".//m:t", namespaces={"m": M_NS}) if t.text)
                if math_txt.strip():
                    runs.append(TextRun(text=f" {math_txt.strip()} ", italic=True))
            elif child.tag in container_tags:
                _walk(child)

    _walk(paragraph._element)
    if not runs and paragraph.text:
        runs.append(TextRun(text=paragraph.text))
    return _merge_adjacent_runs(runs), omath_count


def _merge_adjacent_runs(runs: Iterable[TextRun]) -> list[TextRun]:
    merged: list[TextRun] = []
    for run in runs:
        if not run.text:
            continue
        if (
            merged
            and merged[-1].bold == run.bold
            and merged[-1].italic == run.italic
            and merged[-1].subscript == run.subscript
            and merged[-1].superscript == run.superscript
        ):
            merged[-1].text += run.text
        else:
            merged.append(
                TextRun(
                    text=run.text,
                    bold=run.bold,
                    italic=run.italic,
                    subscript=run.subscript,
                    superscript=run.superscript,
                )
            )
    return merged


def _iter_body_blocks(doc: Document):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


AFF_SYMBOL_MAP = {"*": "star", "†": "dag", "‡": "ddag", "§": "sec", "¶": "pil"}


def _safe_aff_id(label: str) -> str:
    lbl = label.strip()
    if lbl in AFF_SYMBOL_MAP:
        return f"aff-{AFF_SYMBOL_MAP[lbl]}"
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", lbl)
    return f"aff{cleaned or 'x'}"


def _parse_authors_line(line: str) -> list[Author]:
    authors: list[Author] = []
    # Support semicolon-separated ("A [1,*]; B [2]") or comma/"and"-separated ("A1 and B2,3,*")
    if ";" in line:
        chunks = [c.strip() for c in line.split(";") if c.strip()]
    else:
        normalized = re.sub(r"\s+and\s+", ", ", line)
        chunks = [c.strip() for c in re.split(r",(?![\da-zA-Z,*†‡§¶]+\b)", normalized) if c.strip()]
        if len(chunks) == 1 and "," in line:
            chunks = [c.strip() for c in re.split(r",\s+(?=[A-Z])", normalized) if c.strip()]

    for chunk in chunks:
        m = re.match(r"^(.+?)\s*\[([^\]]+)\]\s*$", chunk)
        if m:
            full_name = m.group(1).strip()
            tags = [t.strip() for t in m.group(2).split(",") if t.strip()]
        else:
            m2 = re.match(r"^(.+?)([,\d*†‡§¶]+)$", chunk)
            if m2 and any(ch.isdigit() or ch in "*†‡§¶" for ch in m2.group(2)):
                full_name = m2.group(1).strip().rstrip(",")
                tags = [t.strip() for t in re.findall(r"\d+|[a-z]|[*†‡§¶]", m2.group(2))]
            else:
                full_name = chunk.strip()
                tags = []
        is_corr = "*" in tags or "*" in chunk
        aff_ids = [_safe_aff_id(t) for t in tags if t != "*"]
        parts = full_name.split()
        if not parts:
            continue
        given = " ".join(parts[:-1]) if len(parts) >= 2 else ""
        surname = parts[-1] if len(parts) >= 2 else full_name
        authors.append(
            Author(
                given_names=given,
                surname=surname,
                affiliation_ids=aff_ids,
                is_corresponding=is_corr,
            )
        )
    return authors


def _parse_reference_line(line: str, seq_num: int) -> ReferenceItem:
    m = re.match(r"^(\d+)\.\s*(.+)$", line.strip())
    raw_num = int(m.group(1)) if m else None
    body = m.group(2).strip() if m else line.strip()

    doi = ""
    doi_m = re.search(r"DOI:\s*([^\s]+)", body, flags=re.IGNORECASE)
    if doi_m:
        raw_doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi_m.group(1).rstrip("."), flags=re.IGNORECASE)
        if re.match(r"^10\.\d{4,9}/\S+$", raw_doi):
            doi = raw_doi
        body_wo_doi = body[: doi_m.start()].strip()
    else:
        body_wo_doi = body

    year_m = re.search(r"\((\d{4})\)\.?$", body_wo_doi)
    if year_m:
        year = year_m.group(1)
        core = body_wo_doi[: year_m.start()].strip()
    else:
        ym2 = re.search(r"(?:^|[.,\s(])((?:19|20)\d{2})(?:[.,)\s]|$)", body_wo_doi)
        year = ym2.group(1) if ym2 else "2024"
        core = body_wo_doi
    parts = [p.strip() for p in core.split(". ") if p.strip()]
    authors = parts[0] if len(parts) >= 1 else "Unknown"
    title = parts[1] if len(parts) >= 2 else core
    journal_part = ". ".join(parts[2:]) if len(parts) >= 3 else "Journal"

    vol = ""
    issue = ""
    pages = ""
    journal = journal_part
    jm = re.match(r"^(.+?)\s+(\d+)?\s*(?:\(([^)]+)\))?,?\s*([e\d\-]+)?$", journal_part)
    if jm and (jm.group(2) or jm.group(3) or jm.group(4)):
        journal = jm.group(1).strip().rstrip(".")
        vol = jm.group(2) or ""
        issue = jm.group(3) or ""
        pages = jm.group(4) or ""

    return ReferenceItem(
        id=f"B{seq_num}",
        number=seq_num,
        authors=authors.rstrip("."),
        title=title.rstrip("."),
        journal=journal.rstrip("."),
        year=year,
        volume=vol,
        issue=issue,
        pages=pages,
        doi=doi,
        raw_text=line.strip(),
        raw_number=raw_num,
    )


def _strip_prefix_from_runs(runs: list[TextRun], prefix_chars: int) -> list[TextRun]:
    remaining = prefix_chars
    out: list[TextRun] = []
    for r in runs:
        if remaining <= 0:
            out.append(TextRun(r.text, r.bold, r.italic, r.subscript, r.superscript))
            continue
        if len(r.text) <= remaining:
            remaining -= len(r.text)
            continue
        sliced = r.text[remaining:]
        remaining = 0
        if sliced:
            out.append(TextRun(sliced, r.bold, r.italic, r.subscript, r.superscript))
    if out:
        out[0].text = out[0].text.lstrip()
    return out


class _ProtocolParserState:
    def __init__(self, ms: Manuscript) -> None:
        self.ms = ms
        self.current_sec: ProtocolSection | None = None
        self.last_top_step: ProtocolStep | None = None
        self.last_step: ProtocolStep | None = None

    def consume(self, text: str, runs: list[TextRun], native_level: int | None, is_subheading: bool = False) -> None:
        note_m = re.match(r"^(NOTE|CAUTION):\s*(.+)$", text)
        if note_m and self.last_step is not None:
            kind = note_m.group(1)
            trimmed = _strip_prefix_from_runs(runs, len(kind) + 1)
            self.last_step.notes.append((kind, trimmed))  # type: ignore[arg-type]
            return

        sec_m = re.match(r"^(\d+)\.\s+(.+)$", text)
        if sec_m:
            self.current_sec = ProtocolSection(number=sec_m.group(1), title=sec_m.group(2).strip())
            self.ms.protocol_sections.append(self.current_sec)
            self.last_top_step = None
            self.last_step = None
            return

        sub_heading_m = re.match(r"^(\d+\.\d+(?:\.\d+)?)\s+(.+)$", text)
        all_bold = bool(runs) and all(r.bold or not r.text.strip() for r in runs)
        looks_like_numbered_heading = bool(
            sub_heading_m
            and (
                is_subheading
                or (
                    not text.endswith(".")
                    and len(sub_heading_m.group(2).split()) <= 12
                    and (all_bold or sub_heading_m.group(2)[:1].isupper())
                )
            )
        )
        if is_subheading or looks_like_numbered_heading:
            sec_num = sub_heading_m.group(1) if sub_heading_m else str(len(self.ms.protocol_sections) + 1)
            clean_title = sub_heading_m.group(2).strip() if sub_heading_m else re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", text).strip()
            self.current_sec = ProtocolSection(number=sec_num, title=clean_title or text)
            self.ms.protocol_sections.append(self.current_sec)
            self.last_top_step = None
            self.last_step = None
            return
        subsub_m = re.match(r"^(\d+\.\d+\.\d+)\s+(.+)$", text)
        if subsub_m and self.last_top_step is not None:
            step_num = subsub_m.group(1)
            sub = ProtocolStep(number=step_num, runs=_strip_prefix_from_runs(runs, len(step_num)))
            self.last_top_step.substeps.append(sub)
            self.last_step = sub
            return

        step_m = re.match(r"^(\d+\.\d+)\s+(.+)$", text)
        if step_m:
            self._ensure_section()
            step_num = step_m.group(1)
            step = ProtocolStep(number=step_num, runs=_strip_prefix_from_runs(runs, len(step_num)))
            assert self.current_sec is not None
            self.current_sec.steps.append(step)
            self.last_top_step = step
            self.last_step = step
            return

        if native_level is not None:
            self.ms.native_list_items_count += 1
            self._ensure_section()
            assert self.current_sec is not None
            if native_level >= 1 and self.last_top_step is not None:
                sub_num = f"{self.last_top_step.number}.{len(self.last_top_step.substeps) + 1}"
                sub = ProtocolStep(number=sub_num, runs=runs)
                self.last_top_step.substeps.append(sub)
                self.last_step = sub
                return
            step_num = f"{self.current_sec.number}.{len(self.current_sec.steps) + 1}"
            step = ProtocolStep(number=step_num, runs=runs)
            self.current_sec.steps.append(step)
            self.last_top_step = step
            self.last_step = step
            return

        self._ensure_section()
        assert self.current_sec is not None
        step_num = f"{self.current_sec.number}.{len(self.current_sec.steps) + 1}"
        step = ProtocolStep(number=step_num, runs=runs)
        self.current_sec.steps.append(step)
        self.last_top_step = step
        self.last_step = step

    def _ensure_section(self) -> None:
        if self.current_sec is None:
            self.current_sec = ProtocolSection(number="1", title="Protocol Steps")
            self.ms.protocol_sections.append(self.current_sec)


def _match_section_alias(text: str, style_name: str) -> str | None:
    stripped = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", text.strip()).upper()
    is_heading_style = style_name.startswith("heading") or style_name in ("title", "abstract")
    if stripped in SECTION_ALIASES and (is_heading_style or text.strip().isupper() or len(text.split()) <= 4):
        return SECTION_ALIASES[stripped]
    return None


def load_manuscript(input_path: Path, work_dir: Path | None = None) -> Manuscript:
    """Load a .doc or .docx manuscript into a structured Manuscript model."""
    input_path = Path(input_path)
    ext = input_path.suffix.lower()
    source_format = ext.lstrip(".") or "docx"

    if ext == ".doc":
        docx_path = convert_doc_to_docx(input_path, work_dir or input_path.parent)
    elif ext == ".docx":
        docx_path = input_path
    else:
        raise ValueError(f"Unsupported manuscript format '{ext}'. Expected .doc or .docx.")

    media_dir = (work_dir / "_media") if work_dir else None
    track_changes, comments, extracted_media, docpr_alts, footnotes = _inspect_ooxml_hazards(docx_path, media_dir=media_dir)
    doc = Document(str(docx_path))
    ms = Manuscript(
        title="Untitled Protocol Manuscript",
        source_format=source_format,
        source_filename=input_path.name,
        track_changes_count=track_changes,
        comments_count=comments,
        footnotes=footnotes,
    )

    current_section = "PREAMBLE"
    proto_state = _ProtocolParserState(ms)
    fallback_paragraphs: list[list[TextRun]] = []
    seen_raw_ref_nums: set[int] = set()

    def _unique_row_cells(row, seen_table_tc: set) -> list[str]:
        vals: list[str] = []
        seen_row_tc: set = set()
        for cell in row.cells:
            tc = cell._tc
            if tc in seen_row_tc:
                continue
            seen_row_tc.add(tc)
            if tc in seen_table_tc:
                vals.append("")
                continue
            seen_table_tc.add(tc)
            tc_pr = tc.tcPr
            vmerge = tc_pr.find(qn("w:vMerge")) if tc_pr is not None else None
            if vmerge is not None and vmerge.get(qn("w:val")) != "restart":
                vals.append("")
            else:
                vals.append(cell.text.strip())
        return vals

    for block in _iter_body_blocks(doc):
        if isinstance(block, Table):
            if len(block.rows) >= 2:
                seen_table_tc: set = set()
                headers = _unique_row_cells(block.rows[0], seen_table_tc)
                headers_lower = [h.lower() for h in headers]
                if current_section == "MATERIALS" or (
                    "name" in headers_lower and ("company" in headers_lower or "catalog" in " ".join(headers_lower))
                ):
                    for row in block.rows[1:]:
                        vals = _unique_row_cells(row, seen_table_tc)
                        if any(vals):
                            ms.materials.append(
                                MaterialItem(
                                    name=vals[0] if len(vals) > 0 else "",
                                    company=vals[1] if len(vals) > 1 else "",
                                    catalog_number=vals[2] if len(vals) > 2 else "",
                                    comments=vals[3] if len(vals) > 3 else "",
                                )
                            )
                else:
                    rows_data = [_unique_row_cells(row, seen_table_tc) for row in block.rows[1:]]
                    if any(any(r) for r in rows_data):
                        t_idx = len(ms.tables) + 1
                        ms.tables.append(
                            TableItem(
                                id=f"tbl-data-{t_idx}",
                                label=f"Table {t_idx}",
                                title=f"Manuscript Table {t_idx}",
                                headers=headers,
                                rows=rows_data,
                            )
                        )
            continue

        runs, omath_cnt = _extract_runs(block)
        ms.omath_count += omath_cnt
        text = "".join(r.text for r in runs).strip() or block.text.strip()
        if not text:
            continue

        style_name = (block.style.name or "").lower() if block.style else ""

        # Style-driven front matter detection for real-world Word templates
        if style_name == "title" and ms.title == "Untitled Protocol Manuscript":
            ms.title = text
            continue
        if style_name in ("author name", "authors"):
            ms.authors.extend(_parse_authors_line(text))
            continue
        if style_name in ("author affiliation", "affiliation"):
            _consume_authors(ms, text)
            continue
        if style_name == "keywords" or text.lower().startswith("keywords:"):
            kw_str = text.split(":", 1)[1] if ":" in text else text
            ms.keywords = [kw.strip() for kw in re.split(r"[,;]", kw_str) if kw.strip()]
            continue

        if style_name in ("endnote bibliography", "bibliography", "reference"):
            current_section = "REFERENCES"
        else:
            alias = _match_section_alias(text, style_name)
            if alias:
                current_section = alias
                continue

        # Exit single-block sections (Abstract/Summary/References) when a new Heading 1 starts
        if style_name in ("heading 1", "heading1") and current_section in ("ABSTRACT", "SUMMARY", "REFERENCES", "AUTHORS", "TITLE"):
            current_section = "BODY"

        is_subheading = style_name.startswith("heading") and style_name not in ("heading 1", "heading1")

        if current_section == "PREAMBLE":
            lower_t = text.lower()
            is_wrapper_label = lower_t in (
                "supplementary file",
                "supplementary material",
                "supplementary materials",
                "supplementary data",
                "supplementary information",
            )
            if (
                ms.title == "Untitled Protocol Manuscript"
                and len(text) <= 220
                and not lower_t.startswith("the template is designed")
                and not is_wrapper_label
            ):
                ms.title = text
            elif "@" in text or re.match(r"^[*†‡§¶\s]*(?:correspondence|corresponding\s+author)\b", lower_t):
                _consume_authors(ms, text)
            elif (
                re.match(r"^(?:[1-9]\d*|[*†‡§¶])[:.\s]*(?=[A-Z])", text)
                or re.match(r"^[a-f](?:[:.\s]+|(?=[A-Z]))", text)
            ) and len(text) < 220:
                _consume_authors(ms, text)
            elif (";" in text or any(sym in text for sym in ("*", "†", "‡"))) and len(text) < 220 and not ms.authors:
                ms.authors.extend(_parse_authors_line(text))
            else:
                fallback_paragraphs.append(runs)
        elif current_section == "TITLE":
            ms.title = text
        elif current_section == "METADATA":
            _consume_metadata(ms, text)
        elif current_section == "AUTHORS":
            _consume_authors(ms, text)
        elif current_section == "SUMMARY":
            ms.summary.extend(runs)
        elif current_section == "ABSTRACT":
            ms.abstract.extend(runs)
        elif current_section == "INTRODUCTION":
            ms.introduction.append(runs)
        elif current_section == "PROTOCOL":
            proto_state.consume(text, runs, _get_native_list_level(block), is_subheading=is_subheading)
        elif current_section == "EQUATIONS":
            _consume_equation(ms, text)
        elif current_section == "RESULTS":
            ms.representative_results.append(runs)
        elif current_section == "FIGURES":
            _consume_figure(ms, text)
        elif current_section == "DISCUSSION":
            ms.discussion.append(runs)
        elif current_section == "ACKNOWLEDGMENTS":
            ms.acknowledgments.extend(runs)
        elif current_section == "DISCLOSURES":
            ms.disclosures.extend(runs)
        elif current_section == "REFERENCES":
            ref = _parse_reference_line(text, len(ms.references) + 1)
            if ref.raw_number is not None:
                if ref.raw_number in seen_raw_ref_nums:
                    ms.duplicate_ref_numbers.append(ref.raw_number)
                seen_raw_ref_nums.add(ref.raw_number)
            ms.references.append(ref)
        else:
            fallback_paragraphs.append(runs)

    if not ms.introduction and fallback_paragraphs:
        ms.introduction = fallback_paragraphs
    elif fallback_paragraphs and current_section == "PREAMBLE":
        ms.introduction = fallback_paragraphs + ms.introduction

    if not ms.figures and extracted_media:
        for idx, fname in enumerate(extracted_media, start=1):
            alt = docpr_alts[idx - 1] if idx - 1 < len(docpr_alts) else ""
            ms.figures.append(
                FigureItem(
                    id=f"fig{idx}",
                    label=f"Figure {idx}",
                    title=f"Embedded Manuscript Figure {idx}",
                    caption_runs=[TextRun(text=f"Extracted from word/media/{fname}.")],
                    alt_text=alt,
                    source_filename=fname,
                )
            )

    return ms


def _consume_metadata(ms: Manuscript, text: str) -> None:
    if ":" not in text:
        return
    k, v = [x.strip() for x in text.split(":", 1)]
    kl = k.lower()
    if kl == "subject area":
        ms.subject_area = v
    elif kl == "doi":
        ms.doi = v
    elif kl == "publisher id":
        ms.publisher_id = v
    elif kl == "publication date":
        ms.pub_date = v
    elif kl == "keywords":
        ms.keywords = [kw.strip() for kw in v.split(",") if kw.strip()]


def _consume_authors(ms: Manuscript, text: str) -> None:
    lower = text.lower()
    if re.match(r"^[*†‡§¶\s]*(?:correspondence|corresponding\s+author)\b", lower):
        em = re.search(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text)
        email = em.group(1).strip() if em else ""
        if ms.authors:
            matched = False
            for a in ms.authors:
                if a.is_corresponding or (a.surname and a.surname in text):
                    a.is_corresponding = True
                    if email:
                        a.email = email
                    matched = True
            if not matched and email:
                ms.authors[0].is_corresponding = True
                ms.authors[0].email = email
        return

    aff_m = re.match(r"^([1-9]\d*|[*†‡§¶])[:.\s]*(?=[A-Z])(.+)$", text) or re.match(
        r"^([a-z])(?:[:.\s]+|(?=[A-Z]))(.+)$", text
    )
    if aff_m and ("@" not in text):
        lbl = aff_m.group(1).strip()
        inst = aff_m.group(2).strip()
        ms.affiliations.append(Affiliation(id=_safe_aff_id(lbl), label=lbl, institution=inst))
        return

    if ";" in text or "[" in text or any(sym in text for sym in ("*", "†", "‡")):
        ms.authors.extend(_parse_authors_line(text))


def _consume_equation(ms: Manuscript, text: str) -> None:
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        return
    label, tex = parts[0], parts[1]
    desc = parts[2] if len(parts) > 2 else label
    eq_num = re.sub(r"\D+", "", label) or str(len(ms.formulas) + 1)
    ms.formulas.append(FormulaItem(id=f"eq{eq_num}", label=f"({eq_num})", tex=tex, description=desc))


def _consume_figure(ms: Manuscript, text: str) -> None:
    parts = [p.strip() for p in text.split("|")]
    if not parts:
        return
    label = parts[0]
    title = parts[1] if len(parts) > 1 else label
    caption = parts[2] if len(parts) > 2 else ""
    alt_text = ""
    src_file = ""
    for extra in parts[3:]:
        if extra.upper().startswith("ALT:"):
            alt_text = extra.split(":", 1)[1].strip()
        elif extra.upper().startswith("FILE:"):
            src_file = extra.split(":", 1)[1].strip()
    fig_num = re.sub(r"\D+", "", label) or str(len(ms.figures) + 1)
    ms.figures.append(
        FigureItem(
            id=f"fig{fig_num}",
            label=label,
            title=title,
            caption_runs=[TextRun(text=caption)] if caption else [],
            alt_text=alt_text,
            source_filename=src_file,
        )
    )


def _write_runs(paragraph, runs: list[TextRun]) -> None:
    for r in runs:
        run = paragraph.add_run(r.text)
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        run.bold = r.bold
        run.italic = r.italic
        run.font.subscript = r.subscript
        run.font.superscript = r.superscript


def write_clean_docx(ms: Manuscript, output_path: Path) -> Path:
    """Write a cleaned, normalized JoVE-structured .docx manuscript."""
    doc = Document()
    doc.add_heading(ms.title, level=0)

    aff_label_by_id = {aff.id: aff.label for aff in ms.affiliations}
    if ms.authors:
        p = doc.add_paragraph()
        author_strs = []
        for a in ms.authors:
            tags = [aff_label_by_id.get(aid, aid.replace("aff", "")) for aid in a.affiliation_ids]
            if a.is_corresponding:
                tags.append("*")
            suffix = f" [{','.join(tags)}]" if tags else ""
            author_strs.append(f"{a.given_names} {a.surname}".strip() + suffix)
        p.add_run("; ".join(author_strs))
    for aff in ms.affiliations:
        doc.add_paragraph(f"{aff.label}. {aff.institution}")

    if ms.summary:
        doc.add_heading("Summary", level=1)
        _write_runs(doc.add_paragraph(), ms.summary)

    if ms.abstract:
        doc.add_heading("Abstract", level=1)
        _write_runs(doc.add_paragraph(), ms.abstract)

    if ms.introduction:
        doc.add_heading("Introduction", level=1)
        for para in ms.introduction:
            _write_runs(doc.add_paragraph(), para)

    if ms.protocol_sections:
        doc.add_heading("Protocol", level=1)
        for sec in ms.protocol_sections:
            doc.add_heading(f"{sec.number}. {sec.title}", level=2)
            for step in sec.steps:
                p = doc.add_paragraph()
                r_num = p.add_run(f"{step.number} ")
                r_num.bold = True
                _write_runs(p, step.runs)
                for kind, nruns in step.notes:
                    np = doc.add_paragraph()
                    rk = np.add_run(f"{kind}: ")
                    rk.bold = True
                    _write_runs(np, nruns)
                for sub in step.substeps:
                    sp = doc.add_paragraph()
                    sr = sp.add_run(f"    {sub.number} ")
                    sr.bold = True
                    _write_runs(sp, sub.runs)
                    for kind, nruns in sub.notes:
                        np = doc.add_paragraph()
                        rk = np.add_run(f"    {kind}: ")
                        rk.bold = True
                        _write_runs(np, nruns)

    if ms.representative_results:
        doc.add_heading("Representative Results", level=1)
        for para in ms.representative_results:
            _write_runs(doc.add_paragraph(), para)

    if ms.figures:
        doc.add_heading("Figure Legends", level=1)
        for fig in ms.figures:
            p = doc.add_paragraph()
            r = p.add_run(f"{fig.label}: {fig.title}. ")
            r.bold = True
            _write_runs(p, fig.caption_runs)

    if ms.materials:
        doc.add_heading("Table of Materials", level=1)
        tbl = doc.add_table(rows=len(ms.materials) + 1, cols=4)
        for idx, h in enumerate(["Name", "Company", "Catalog Number", "Comments"]):
            tbl.rows[0].cells[idx].text = h
        for r_idx, item in enumerate(ms.materials, start=1):
            tbl.rows[r_idx].cells[0].text = item.name
            tbl.rows[r_idx].cells[1].text = item.company
            tbl.rows[r_idx].cells[2].text = item.catalog_number
            tbl.rows[r_idx].cells[3].text = item.comments

    for t in ms.tables:
        doc.add_heading(f"{t.label}: {t.title}", level=2)
        cols = max(len(t.headers), max((len(r) for r in t.rows), default=1))
        tbl = doc.add_table(rows=len(t.rows) + 1, cols=cols)
        for c_idx, h in enumerate(t.headers[:cols]):
            tbl.rows[0].cells[c_idx].text = h
        for r_idx, row_vals in enumerate(t.rows, start=1):
            for c_idx, val in enumerate(row_vals[:cols]):
                tbl.rows[r_idx].cells[c_idx].text = val

    if ms.discussion:
        doc.add_heading("Discussion", level=1)
        for para in ms.discussion:
            _write_runs(doc.add_paragraph(), para)

    if ms.acknowledgments:
        doc.add_heading("Acknowledgments", level=1)
        _write_runs(doc.add_paragraph(), ms.acknowledgments)

    if ms.disclosures:
        doc.add_heading("Disclosures", level=1)
        _write_runs(doc.add_paragraph(), ms.disclosures)

    if ms.references:
        doc.add_heading("References", level=1)
        for ref in ms.references:
            doc.add_paragraph(ref.raw_text)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path
