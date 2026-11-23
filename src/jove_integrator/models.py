from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TextRun:
    text: str
    bold: bool = False
    italic: bool = False
    subscript: bool = False
    superscript: bool = False


@dataclass
class Author:
    given_names: str
    surname: str
    affiliation_ids: list[str] = field(default_factory=list)
    is_corresponding: bool = False
    email: str | None = None


@dataclass
class Affiliation:
    id: str
    label: str
    institution: str


@dataclass
class ProtocolStep:
    number: str
    runs: list[TextRun] = field(default_factory=list)
    notes: list[tuple[Literal["NOTE", "CAUTION"], list[TextRun]]] = field(default_factory=list)
    substeps: list[ProtocolStep] = field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class ProtocolSection:
    number: str
    title: str
    steps: list[ProtocolStep] = field(default_factory=list)


@dataclass
class MaterialItem:
    name: str
    company: str
    catalog_number: str
    comments: str = ""


@dataclass
class FigureItem:
    id: str
    label: str
    title: str
    caption_runs: list[TextRun] = field(default_factory=list)
    alt_text: str = ""
    source_filename: str = ""
    web_filename: str = ""
    large_filename: str = ""


@dataclass
class FormulaItem:
    id: str
    label: str
    tex: str
    description: str
    variables: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class TableItem:
    id: str
    label: str
    title: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ReferenceItem:
    id: str
    number: int
    authors: str
    title: str
    journal: str
    year: str
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pmid: str = ""
    raw_text: str = ""
    raw_number: int | None = None


@dataclass
class QAFinding:
    rule_id: str
    severity: Literal["error", "warning", "fixed"]
    category: str
    location: str
    message: str
    before: str = ""
    after: str = ""
    guideline_ref: str = ""
    auto_fixed: bool = False
    confidence: Literal["deterministic", "heuristic", "blocking"] = "deterministic"
    suggested_query: str = ""
    review_tool: str = ""


@dataclass
class SectionReadiness:
    section: str
    status: Literal["pass", "review", "fail"]
    detail: str


@dataclass
class ImageAssetReport:
    source_path: str
    original_width: int
    original_height: int
    web_path: str
    web_width: int
    web_height: int
    large_path: str
    large_width: int
    large_height: int
    alt_text: str
    meets_jove_min_resolution: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class Manuscript:
    title: str
    subject_area: str = "Bioengineering"
    doi: str = "10.3791/60874-demo"
    publisher_id: str = "60874-demo"
    pub_date: str = "2026-11-23"
    authors: list[Author] = field(default_factory=list)
    affiliations: list[Affiliation] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    summary: list[TextRun] = field(default_factory=list)
    abstract: list[TextRun] = field(default_factory=list)
    introduction: list[list[TextRun]] = field(default_factory=list)
    protocol_sections: list[ProtocolSection] = field(default_factory=list)
    representative_results: list[list[TextRun]] = field(default_factory=list)
    discussion: list[list[TextRun]] = field(default_factory=list)
    acknowledgments: list[TextRun] = field(default_factory=list)
    disclosures: list[TextRun] = field(default_factory=list)
    figures: list[FigureItem] = field(default_factory=list)
    formulas: list[FormulaItem] = field(default_factory=list)
    materials: list[MaterialItem] = field(default_factory=list)
    tables: list[TableItem] = field(default_factory=list)
    references: list[ReferenceItem] = field(default_factory=list)
    source_format: str = "docx"
    source_filename: str = ""
    track_changes_count: int = 0
    comments_count: int = 0
    native_list_items_count: int = 0
    omath_count: int = 0
    duplicate_ref_numbers: list[int] = field(default_factory=list)


@dataclass
class XMLCheckResult:
    well_formed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    manuscript: Manuscript
    findings: list[QAFinding]
    readiness: list[SectionReadiness]
    image_reports: list[ImageAssetReport]
    html_article: str
    jats_xml: str
    xml_check: XMLCheckResult
    clean_docx_path: str | None = None
    html_path: str | None = None
    xml_path: str | None = None
    report_path: str | None = None
    original_lines: list[str] = field(default_factory=list)
    diff_rows: list[dict[str, str]] = field(default_factory=list)
