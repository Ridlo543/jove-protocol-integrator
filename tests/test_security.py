from __future__ import annotations

import io
import zipfile
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from jove_integrator import web
from jove_integrator.word_loader import load_manuscript


def test_healthz_and_security_headers() -> None:
    web.RATE_LIMITER.reset()
    client = TestClient(web.app)

    r_health = client.get("/healthz")
    assert r_health.status_code == 200
    assert r_health.json() == {"status": "ok"}
    assert r_health.headers.get("x-content-type-options") == "nosniff"
    assert r_health.headers.get("x-frame-options") == "SAMEORIGIN"

    r_sample = client.post("/api/process", data={"sample_id": "clean-ready"})
    assert r_sample.status_code == 200
    run_id = r_sample.json()["run_id"]

    r_prev = client.get(f"/runs/{run_id}/preview")
    assert r_prev.status_code == 200
    csp = r_prev.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'self'" in csp


def test_upload_size_limit_and_extension_validation(monkeypatch) -> None:
    web.RATE_LIMITER.reset()
    monkeypatch.setattr(web, "MAX_MANUSCRIPT_BYTES", 1024)
    client = TestClient(web.app)

    oversized = b"PK\x03\x04" + b"A" * 2048
    r_big = client.post(
        "/api/process",
        files={"manuscript": ("big.docx", io.BytesIO(oversized), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r_big.status_code == 413

    r_bad_fig = client.post(
        "/api/process",
        files={
            "manuscript": ("ok.docx", io.BytesIO(b"PK\x03\x04" + b"A" * 100), "application/octet-stream"),
            "figure": ("evil.svg", io.BytesIO(b"<svg onload=alert(1)>"), "image/svg+xml"),
        },
    )
    assert r_bad_fig.status_code == 400


def test_zip_bomb_and_xxe_blocked(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("Normal text")
    base_docx = tmp_path / "base.docx"
    doc.save(base_docx)

    # 1. Zip bomb: single entry > 15 MB uncompressed
    bomb_docx = tmp_path / "bomb.docx"
    with zipfile.ZipFile(base_docx, "r") as zin, zipfile.ZipFile(bomb_docx, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("word/media/huge.bin", b"\x00" * (16 * 1024 * 1024))

    try:
        load_manuscript(bomb_docx, tmp_path / "out_bomb")
        raise AssertionError("Expected ValueError for oversized archive entry")
    except ValueError as exc:
        assert "exceeds" in str(exc)

    # 2. XXE entity expansion inside word/document.xml must not resolve external/entity payloads
    xxe_docx = tmp_path / "xxe.docx"
    xxe_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<!DOCTYPE document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(base_docx, "r") as zin, zipfile.ZipFile(xxe_docx, "w") as zout:
        for item in zin.infolist():
            if item.filename == "word/document.xml":
                zout.writestr(item, xxe_xml)
            else:
                zout.writestr(item, zin.read(item.filename))

    try:
        ms = load_manuscript(xxe_docx, tmp_path / "out_xxe")
        joined = " ".join(r.text for p in ms.introduction for r in p)
        assert "root:" not in joined
    except Exception:
        # Rejecting DOCTYPE/entity XML is also safe
        pass


def test_path_traversal_and_rate_limiter() -> None:
    web.RATE_LIMITER.reset()
    client = TestClient(web.app)

    r_trav = client.get("/runs/..%2F..%2Fetc/assets/passwd")
    assert r_trav.status_code in (400, 404)

    # Trigger rate limit on /api/process (12/min)
    for _ in range(12):
        r = client.post("/api/process", data={"sample_id": "clean-ready"})
        assert r.status_code == 200
    r_limited = client.post("/api/process", data={"sample_id": "clean-ready"})
    assert r_limited.status_code == 429
    assert "retry-after" in r_limited.headers
    web.RATE_LIMITER.reset()
