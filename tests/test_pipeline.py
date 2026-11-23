from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from jove_integrator.pipeline import run_pipeline
from jove_integrator.web import app
from jove_integrator.xml_validator import validate_jats_xml_local

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DOCX = ROOT / "samples" / "sample_protocol_messy.docx"


def test_full_pipeline_separates_deterministic_fixes_from_human_review(tmp_path: Path) -> None:
    res = run_pipeline(SAMPLE_DOCX, tmp_path, asset_search_dirs=[ROOT / "samples"])

    fixed_ids = {f.rule_id for f in res.findings if f.severity == "fixed"}
    review_ids = {f.rule_id for f in res.findings if f.severity == "warning"}
    error_ids = {f.rule_id for f in res.findings if f.severity == "error"}

    assert {
        "PDF-LIGATURES",
        "PMC-INVISIBLE-CHARS",
        "JATS4R-DEGREE",
        "JOVE-PLUSMINUS",
        "JOVE-MICRO-PREFIX",
        "JOVE-SI-SPACING",
        "JOVE-TRADEMARK",
        "JOVE-SPECIES-ITALIC",
        "JOVE-CHEMICAL-SUB",
        "JOVE-MATERIALS-SORT",
    }.issubset(fixed_ids)

    assert {
        "JOVE-LOST-SUPERSCRIPT",
        "JOVE-PERCENT-BASIS",
        "JOVE-VAGUE-CONDITION",
        "JOVE-CENTRIFUGE-RPM",
        "JOVE-AFFIL-ABBREV",
        "JOVE-REF-COUNT",
    }.issubset(review_ids)

    assert error_ids == set()

    # Ambiguous items must NOT be silently mutated in HTML or XML
    assert "12,000 rpm" in res.html_article
    assert "5 x 106 cells" in res.html_article
    assert "room temperature" in res.html_article

    # Deterministic fixes MUST be applied cleanly
    assert "microfluidic" in res.html_article
    assert "\ufb02" not in res.html_article
    assert "\u200b" not in res.html_article
    assert "\u00ba" not in res.jats_xml
    assert "&#x00B0;C" in res.html_article
    assert "&#x00B5;L" in res.html_article
    assert "&#x00B1;" in res.html_article
    assert "<em>E. coli</em>" in res.html_article
    assert "[Place " not in res.html_article
    assert "[Place " not in res.jats_xml
    assert 'data-qa-loc="Protocol 2.2"' in res.html_article
    assert 'data-qa-loc="Abstract"' in res.html_article

    mat_names = [m.name for m in res.manuscript.materials]
    assert mat_names == sorted(mat_names, key=str.lower)

    assert res.xml_check.well_formed is True
    assert res.xml_check.errors == []
    assert "JATS-journalpublishing1-3.dtd" in res.jats_xml
    assert 'publication-format="electronic"' in res.jats_xml
    assert "\\documentclass{article}" in res.jats_xml

    assert len(res.image_reports) == 1
    img = res.image_reports[0]
    assert img.meets_jove_min_resolution is True
    assert img.web_width == 700
    assert img.large_width == 1400


def test_ooxml_track_changes_comments_and_sequence_hazards(tmp_path: Path) -> None:
    doc = Document()
    doc.add_heading("TITLE", level=1)
    doc.add_paragraph("Hazard Detection Test")
    doc.add_heading("AUTHORS AND AFFILIATIONS", level=1)
    doc.add_paragraph("Jane Doe [1,*]")
    doc.add_paragraph("1: Department of Biology, Example University")
    doc.add_paragraph("Correspondence: Jane Doe <j.doe@example.edu>")
    doc.add_heading("INTRODUCTION", level=1)
    doc.add_paragraph("First citation out of order [2] before [1].")
    doc.add_heading("PROTOCOL", level=1)
    doc.add_paragraph("1. Setup")
    doc.add_paragraph("1.1 First step.")
    doc.add_paragraph("1.3 Skipped step 1.2.")
    doc.add_heading("REFERENCES", level=1)
    doc.add_paragraph("1. Alpha, A. First paper. J. Test. 1 (1), 1-5 (2024).")
    doc.add_paragraph("2. Beta, B. Second paper. J. Test. 2 (1), 6-10 (2025).")

    raw_docx = tmp_path / "hazards.docx"
    doc.save(raw_docx)

    # Inject w:ins track change and word/comments.xml into the OOXML archive
    patched_docx = tmp_path / "hazards_ooxml.docx"
    with zipfile.ZipFile(raw_docx, "r") as zin, zipfile.ZipFile(patched_docx, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml_str = data.decode("utf-8").replace(
                    "<w:t>1.1 First step.</w:t>",
                    '<w:ins w:id="1" w:author="Reviewer"><w:t>1.1 First step.</w:t></w:ins>',
                )
                assert "w:ins" in xml_str
                data = xml_str.encode("utf-8")
            zout.writestr(item, data)
        zout.writestr(
            "word/comments.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:comment w:id="0" w:author="Coauthor"><w:p><w:r><w:t>Check concentration</w:t></w:r></w:p></w:comment>'
            "</w:comments>",
        )

    res = run_pipeline(patched_docx, tmp_path / "out")
    rule_ids = {f.rule_id for f in res.findings}
    assert "WORD-TRACK-CHANGES" in rule_ids
    assert "WORD-COMMENTS-OPEN" in rule_ids
    assert "JOVE-STEP-SEQUENCE" in rule_ids
    assert "JOVE-REF-ORDER" in rule_ids


def test_local_xml_validator_catches_pmc_style_violations() -> None:
    bad_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <article>
      <front>
        <journal-meta><journal-title-group><journal-title>J</journal-title></journal-title-group></journal-meta>
        <article-meta>
          <title-group><article-title>T</article-title></title-group>
          <pub-date date-type="pub"><year>2026</year></pub-date>
        </article-meta>
      </front>
      <body>
        <sec id="s1">
          <title><bold>Bad Title</bold></title>
          <sec id="s1a"><title>Sub</title><p>Text</p></sec>
          <p>Paragraph after child sec <xref ref-type="fig" rid="missing_fig">Figure 9</xref></p>
          <tex-math>x = 1</tex-math>
        </sec>
      </body>
    </article>"""
    check = validate_jats_xml_local(bad_xml)
    assert check.well_formed is True
    joined = "\n".join(check.errors)
    assert "Broken <xref>" in joined
    assert "<tex-math> found outside <alternatives>" in joined
    assert "<bold> wraps entire content" in joined
    assert "follows <sec>" in joined
    assert "@publication-format" in joined
    assert "complete LaTeX document" in joined


def test_web_workbench_endpoints() -> None:
    client = TestClient(app)

    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "Sample manuscripts" in r_home.text
    assert "gate-badge" in r_home.text
    assert "let currentData = null;" in r_home.text

    r_s1 = client.post("/api/process", data={"sample_id": "rf-biosensor"})
    assert r_s1.status_code == 200
    p1 = r_s1.json()
    assert p1["xml_check"]["errors"] == []
    assert p1["summary_counts"]["fixed"] >= 20
    assert p1["summary_counts"]["warnings"] >= 5
    assert len(p1["readiness"]) == 7

    r_s2 = client.post("/api/process", data={"sample_id": "coip-hazards"})
    assert r_s2.status_code == 200
    p2 = r_s2.json()
    assert p2["xml_check"]["errors"] == []
    assert p2["ooxml_stats"]["track_changes"] >= 1
    assert p2["ooxml_stats"]["comments"] >= 1
    assert p2["summary_counts"]["errors"] >= 1

    r_s3 = client.post("/api/process", data={"sample_id": "clean-ready"})
    assert r_s3.status_code == 200
    p3 = r_s3.json()
    assert p3["xml_check"]["errors"] == []
    assert p3["summary_counts"] == {"fixed": 0, "warnings": 0, "errors": 0}

    with SAMPLE_DOCX.open("rb") as f:
        r_upload = client.post(
            "/api/process",
            files={"manuscript": ("uploaded_test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert r_upload.status_code == 200
    up_data = r_upload.json()
    run_id = up_data["run_id"]
    assert up_data["source_filename"] == "uploaded_test.docx"
    assert len(up_data["diff_rows"]) >= 2

    # Apply interactive RCF fix and verify manuscript + artifacts update
    r_fix = client.post(
        f"/api/runs/{run_id}/apply-fix",
        json={"rule_id": "JOVE-CENTRIFUGE-RPM", "location": "Protocol 2.2", "value": "13,684 x g"},
    )
    assert r_fix.status_code == 200
    fixed_data = r_fix.json()
    assert "13,684 x g" in fixed_data["html_article"]
    assert "13,684 x g" in fixed_data["jats_xml"]
    assert "12,000 rpm" not in fixed_data["html_article"]
    assert fixed_data["summary_counts"]["warnings"] == up_data["summary_counts"]["warnings"] - 1
    assert fixed_data["summary_counts"]["fixed"] == up_data["summary_counts"]["fixed"] + 1

    # Direct manuscript edit endpoint
    r_edit = client.post(
        f"/api/runs/{run_id}/edit",
        json={"title": "Edited Protocol Title for Verification"},
    )
    assert r_edit.status_code == 200
    assert "Edited Protocol Title for Verification" in r_edit.json()["jats_xml"]

    # SQLite persistence & ZIP bundle download
    r_runs = client.get("/api/runs")
    assert r_runs.status_code == 200
    assert any(r["run_id"] == run_id for r in r_runs.json()["runs"])

    r_bundle = client.get(fixed_data["download_urls"]["bundle"])
    assert r_bundle.status_code == 200
    assert r_bundle.headers["content-type"] == "application/zip"

    r_xml = client.get(fixed_data["download_urls"]["xml"])
    assert r_xml.status_code == 200
    assert "JATS-journalpublishing1-3.dtd" in r_xml.text

    r_preview = client.get(fixed_data["preview_url"])
    assert r_preview.status_code == 200
    assert "Edited Protocol Title for Verification" in r_preview.text

    # Clean up test runs from SQLite
    for rid in (p1["run_id"], p2["run_id"], p3["run_id"], run_id):
        assert client.delete(f"/api/runs/{rid}").status_code == 200

    r_bad = client.get("/runs/..%2F../assets/secret.txt")
    assert r_bad.status_code in (400, 404)


def test_embedded_word_media_extraction(tmp_path: Path) -> None:
    doc = Document()
    doc.add_heading("Title", level=1)
    doc.add_paragraph("Embedded Image Test")
    doc.add_heading("Methods", level=1)
    doc.add_paragraph("1.1 Measure sample at 37°C.")
    raw_docx = tmp_path / "embedded.docx"
    doc.save(raw_docx)

    fig_bytes = (ROOT / "samples" / "fig1_raw.png").read_bytes()
    patched = tmp_path / "embedded_with_media.docx"
    with zipfile.ZipFile(raw_docx, "r") as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("word/media/image1.png", fig_bytes)

    res = run_pipeline(patched, tmp_path / "out")
    assert len(res.image_reports) == 1
    assert res.image_reports[0].web_width == 700
    assert res.image_reports[0].large_width == 1400


def test_real_world_docx_edge_cases(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("Real-World Edge Case Manuscript", style="Title")
    doc.add_paragraph("Jane Doe†, John Smith*")
    doc.add_paragraph("†Department of Biology, Example University")
    doc.add_paragraph("*Correspondence: John Smith <j.smith@example.edu>")
    doc.add_heading("1. Introduction", level=1)
    p = doc.add_paragraph("Yield was 78% higher and 30% of samples matched (Smith, 2024).")
    # Whitespace-only bold run must not emit empty <bold> in JATS XML
    r_ws = p.add_run("   ")
    r_ws.bold = True
    doc.add_heading("2. Methods", level=1)
    doc.add_heading("2.1 Empty Parent Subsection", level=2)
    doc.add_heading("2.2 Actual Step Subsection", level=2)
    doc.add_paragraph("2.1 Incubate with 5% BSA at 37°C.")
    doc.add_heading("References", level=1)
    doc.add_paragraph("12. Smith, J. First paper. J. Test. 1 (1), 1-5 (2024). DOI: http://")
    doc.add_paragraph("12. Doe, J. Duplicate ref number. J. Test. 2 (1), 6-10 (2025). DOI: 10.1000/xyz123")

    docx_path = tmp_path / "real_edge.docx"
    doc.save(docx_path)

    res = run_pipeline(docx_path, tmp_path / "out")
    assert res.xml_check.well_formed is True
    assert res.xml_check.errors == []
    assert "<bold>" not in res.jats_xml
    assert "aff-dag" in res.jats_xml
    assert ">http://<" not in res.jats_xml
    assert "<xref ref-type=\"aff\" rid=\"aff-dag\">†</xref>" in res.jats_xml
    assert "<sup>†</sup>" in res.html_article
    assert "-dag" not in res.html_article
    assert "10.1000/xyz123" in res.jats_xml

    rule_ids = {f.rule_id for f in res.findings}
    assert "JOVE-REF-DUPLICATE-NUM" in rule_ids
    # 78% higher and 30% of must NOT trigger JOVE-PERCENT-BASIS, while 5% BSA MUST trigger it
    pct_findings = [f for f in res.findings if f.rule_id == "JOVE-PERCENT-BASIS"]
    assert len(pct_findings) == 1
    assert "5% BSA" in pct_findings[0].before
    # Author-year citation (Smith, 2024) must mark ref 1 as cited
    uncited = [f for f in res.findings if f.rule_id == "JOVE-UNCITED-REF"]
    assert uncited and "1," not in uncited[0].message and "[1]" not in uncited[0].message
def test_legacy_doc_conversion_via_word_com_if_available(tmp_path: Path) -> None:
    win32com = pytest.importorskip("win32com.client")
    pythoncom = pytest.importorskip("pythoncom")

    doc_path = tmp_path / "legacy_sample.doc"
    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32com.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(SAMPLE_DOCX.resolve()), ReadOnly=True)
        doc.SaveAs2(str(doc_path.resolve()), FileFormat=0)
    except Exception as exc:
        pytest.skip(f"Word COM unavailable in test environment: {exc}")
    finally:
        if doc is not None:
            doc.Close(False)
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()

    assert doc_path.exists()
    res = run_pipeline(doc_path, tmp_path / "out", asset_search_dirs=[ROOT / "samples"])
    assert res.manuscript.source_format == "doc"
    assert res.xml_check.well_formed is True
    assert res.xml_check.errors == []
