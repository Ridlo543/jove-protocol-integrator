from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import secrets
import shutil
import time
import uuid
import zipfile
from collections import defaultdict, deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .editor import (
    apply_review_fix,
    compute_manuscript_diff,
    manuscript_to_plain_lines,
    rebuild_from_manuscript,
    update_manuscript_fields,
)
from .pipeline import run_pipeline
from .pmc_client import verify_xml_on_live_pmc
from .storage import RunStore, manuscript_from_dict, manuscript_to_dict

_pkg_root = Path(__file__).resolve().parents[2]
BASE_DIR = Path(os.getenv("JOVE_APP_DIR", str(_pkg_root if (_pkg_root / "templates").exists() else Path.cwd())))
DATA_DIR = Path(os.getenv("JOVE_DATA_DIR", str(BASE_DIR / "output")))
TEMPLATES_DIR = BASE_DIR / "templates"
SAMPLES_DIR = BASE_DIR / "samples"
RUNS_DIR = DATA_DIR / "web_runs"
STORE = RunStore(DATA_DIR / "workbench.db")

IS_PROD = os.getenv("JOVE_ENV", "").lower() == "production"
TRUST_PROXY = os.getenv("JOVE_TRUST_PROXY", "0") == "1"
MAX_MANUSCRIPT_BYTES = int(os.getenv("JOVE_MAX_MANUSCRIPT_BYTES", str(10 * 1024 * 1024)))
MAX_FIGURE_BYTES = int(os.getenv("JOVE_MAX_FIGURE_BYTES", str(5 * 1024 * 1024)))
MAX_STORED_RUNS = int(os.getenv("JOVE_MAX_RUNS", "40"))
ALLOWED_FIGURE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}

app = FastAPI(
    title="JoVE Protocol Integrator & PMC JATS QA Workbench",
    version="1.0.0",
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
    openapi_url=None if IS_PROD else "/openapi.json",
)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_PIPELINE_SEMAPHORE = asyncio.Semaphore(2)
_SESSION_SECRET = os.getenv("JOVE_SESSION_SECRET") or secrets.token_hex(32)
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "").strip()
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "").strip()


def _sign_sid(sid: str) -> str:
    sig = hmac.new(_SESSION_SECRET.encode("utf-8"), sid.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{sid}.{sig}"


def _read_sid(request: Request) -> tuple[str, bool]:
    raw = request.cookies.get("jove_sid", "")
    if "." in raw:
        sid, sig = raw.split(".", 1)
        if SAFE_NAME_RE.match(sid) and hmac.compare_digest(_sign_sid(sid), f"{sid}.{sig}"):
            return sid, False
    return uuid.uuid4().hex[:16], True


def _attach_sid_cookie(response, sid: str) -> None:
    response.set_cookie(
        key="jove_sid",
        value=_sign_sid(sid),
        httponly=True,
        samesite="lax",
        secure=IS_PROD,
        max_age=86400 * 7,
    )


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_sec: int) -> None:
        if os.getenv("JOVE_RATE_LIMIT_ENABLED", "1") != "1":
            return
        now = time.monotonic()
        if len(self._hits) > 2000:
            stale_keys = [k for k, dq in self._hits.items() if not dq or dq[-1] < now - 3600]
            for k in stale_keys:
                del self._hits[k]
        q = self._hits[key]
        cutoff = now - window_sec
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            retry_after = max(1, int(window_sec - (now - q[0])))
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please wait before retrying.",
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


RATE_LIMITER = SlidingWindowLimiter()

def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        cf_ip = request.headers.get("cf-connecting-ip", "").strip()
        if cf_ip:
            return cf_ip
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def _enforce_rate(request: Request, bucket: str, limit: int, window_sec: int) -> None:
    RATE_LIMITER.check(f"{bucket}:{_client_ip(request)}", limit=limit, window_sec=window_sec)


def _safe_filename(raw_name: str, fallback: str) -> str:
    base = Path(raw_name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return cleaned[:120] or fallback


async def _save_upload_limited(upload: UploadFile, dest: Path, max_bytes: int, label: str) -> None:
    total = 0
    with dest.open("wb") as out:
        while True:
            chunk = await upload.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"{label} exceeds maximum allowed size ({max_bytes // (1024 * 1024)} MB).",
                )
            out.write(chunk)


def _save_and_prune(payload: dict[str, Any], owner_sid: str = "") -> None:
    STORE.save_run(payload, owner_sid=owner_sid)
    for stale_id in STORE.prune_old_runs(max_runs=MAX_STORED_RUNS):
        if SAFE_NAME_RE.match(stale_id):
            shutil.rmtree(RUNS_DIR / stale_id, ignore_errors=True)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if request.url.path.endswith("/preview"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
        )
    return response
SAMPLE_CATALOG = [
    {
        "id": "rf-biosensor",
        "filename": "sample_protocol_messy.docx",
        "title": "RF & Microfluidic Biosensor Calibration",
        "discipline": "Bioengineering",
        "profile": "Entity & SI Cleanup",
        "summary": "PDF ligatures, U+00BA typos, uL, +/-, 12,000 rpm, 5 x 106 cells, unsorted materials.",
    },
    {
        "id": "coip-hazards",
        "filename": "sample_coip_hazards.docx",
        "title": "Co-IP & On-Bead SHP2 Phosphatase Assay",
        "discipline": "Immunology & Infection",
        "profile": "OOXML & Sequence Hazards",
        "summary": "Unaccepted w:ins track changes, comments.xml, TNF-a homoglyphs, step gap 1.1 -> 1.3.",
    },
    {
        "id": "natural-word",
        "filename": "sample_natural_manuscript.docx",
        "title": "PGM Recovery (Natural Word Format)",
        "discipline": "Analytical Chemistry",
        "profile": "Unstructured Word & Intl Units",
        "summary": "Hyperlink email, † affil, embedded media (1200px), vMerge table, footnotes, 100 ml, 11,4%, （pH 1.2）.",
    },
    {
        "id": "clean-ready",
        "filename": "sample_clean_ready.docx",
        "title": "Standardized Two-Port SOLT Calibration",
        "discipline": "Bioengineering",
        "profile": "Clean Baseline",
        "summary": "10 sequential refs, full affiliations, 13,684 x g RCF, sorted materials (0 errors).",
    },
]
SAMPLE_BY_ID = {item["id"]: item for item in SAMPLE_CATALOG}


def _validate_run_id(run_id: str) -> Path:
    if not SAFE_NAME_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run ID.")
    base = RUNS_DIR.resolve()
    target = (RUNS_DIR / run_id).resolve()
    if target.parent != base:
        raise HTTPException(status_code=400, detail="Invalid run ID.")
    return target

def _serialize_result(
    run_id: str,
    res,
    original_lines: list[str] | None = None,
    live_pmc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    orig = original_lines if original_lines is not None else res.original_lines
    diff_rows = compute_manuscript_diff(orig, manuscript_to_plain_lines(res.manuscript)) if orig else res.diff_rows
    return {
        "run_id": run_id,
        "title": res.manuscript.title,
        "source_filename": res.manuscript.source_filename,
        "source_format": res.manuscript.source_format,
        "ooxml_stats": {
            "track_changes": res.manuscript.track_changes_count,
            "comments": res.manuscript.comments_count,
            "native_list_items": res.manuscript.native_list_items_count,
        },
        "summary_counts": {
            "fixed": sum(1 for f in res.findings if f.severity == "fixed"),
            "warnings": sum(1 for f in res.findings if f.severity == "warning"),
            "errors": sum(1 for f in res.findings if f.severity == "error"),
        },
        "readiness": [asdict(r) for r in res.readiness],
        "findings": [asdict(f) for f in res.findings],
        "images": [
            {
                **asdict(img),
                "web_url": f"/runs/{run_id}/assets/{Path(img.web_path).name}" if img.web_path else "",
                "large_url": f"/runs/{run_id}/assets/{Path(img.large_path).name}" if img.large_path else "",
            }
            for img in res.image_reports
        ],
        "materials": [asdict(m) for m in res.manuscript.materials],
        "manuscript_data": manuscript_to_dict(res.manuscript),
        "original_lines": orig,
        "diff_rows": diff_rows,
        "xml_check": asdict(res.xml_check),
        "live_pmc": live_pmc,
        "html_article": res.html_article,
        "jats_xml": res.jats_xml,
        "preview_url": f"/runs/{run_id}/preview",
        "download_urls": {
            "xml": f"/runs/{run_id}/download/xml",
            "html": f"/runs/{run_id}/download/html",
            "docx": f"/runs/{run_id}/download/docx",
            "report": f"/runs/{run_id}/download/report",
            "bundle": f"/runs/{run_id}/download/bundle",
        },
    }


def _run_sample(sample_id: str) -> dict[str, Any]:
    meta = SAMPLE_BY_ID.get(sample_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown sample '{sample_id}'.")
    run_id = f"sample-{sample_id}-{uuid.uuid4().hex[:6]}"
    run_dir = RUNS_DIR / run_id
    sample_docx = SAMPLES_DIR / meta["filename"]
    res = run_pipeline(
        sample_docx,
        run_dir,
        asset_search_dirs=[SAMPLES_DIR],
        asset_url_prefix=f"/runs/{run_id}/assets/",
    )
    payload = _serialize_result(run_id, res)
    _save_and_prune(payload)
    return payload


@app.get("/healthz")
async def healthz():
    return JSONResponse({"status": "ok"})

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, sample: str | None = None, run_id: str | None = None):
    sid, is_new = _read_sid(request)
    initial_data = None
    if run_id:
        initial_data = STORE.get_run(run_id)
    elif sample and sample in SAMPLE_BY_ID:
        initial_data = _run_sample(sample)
    resp = templates.TemplateResponse(
        request=request,
        name="workbench.html",
        context={
            "samples": SAMPLE_CATALOG,
            "recent_runs": STORE.list_runs(limit=12, owner_sid=sid),
            "initial_data": initial_data,
            "turnstile_site_key": TURNSTILE_SITE_KEY,
        },
    )
    if is_new:
        _attach_sid_cookie(resp, sid)
    return resp


@app.get("/api/runs")
async def list_runs(request: Request):
    sid, _ = _read_sid(request)
    return JSONResponse({"runs": STORE.list_runs(limit=25, owner_sid=sid)})


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    _validate_run_id(run_id)
    payload = STORE.get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Run not found.")
    return JSONResponse(payload)


@app.delete("/api/runs/{run_id}")
async def delete_run(request: Request, run_id: str):
    _enforce_rate(request, "mutate", limit=30, window_sec=60)
    run_dir = _validate_run_id(run_id)
    sid, _ = _read_sid(request)
    owner = STORE.get_run_owner(run_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if owner and owner != sid:
        raise HTTPException(status_code=403, detail="You can only delete runs created in your session.")
    deleted = STORE.delete_run(run_id)
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found.")
    return JSONResponse({"deleted": True, "run_id": run_id})


async def _verify_turnstile_if_configured(token: str, remote_ip: str) -> None:
    if not TURNSTILE_SECRET_KEY:
        return
    if not token:
        raise HTTPException(status_code=400, detail="Verification challenge required.")
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": TURNSTILE_SECRET_KEY, "response": token, "remoteip": remote_ip},
        )
        if r.status_code != 200 or not r.json().get("success"):
            raise HTTPException(status_code=403, detail="Verification challenge failed.")


@app.post("/api/process")
async def process_manuscript(
    request: Request,
    sample_id: str | None = Form(None),
    use_sample: bool = Form(False),
    website: str = Form(""),
    cf_turnstile_response: str = Form("", alias="cf-turnstile-response"),
    manuscript: UploadFile | None = File(None),
    figure: UploadFile | None = File(None),
):
    _enforce_rate(request, "process_min", limit=12, window_sec=60)
    _enforce_rate(request, "process_hr", limit=40, window_sec=3600)
    if website.strip():
        raise HTTPException(status_code=400, detail="Invalid submission.")

    sid, is_new = _read_sid(request)

    if sample_id:
        async with _PIPELINE_SEMAPHORE:
            resp = JSONResponse(await asyncio.to_thread(_run_sample, sample_id))
            if is_new:
                _attach_sid_cookie(resp, sid)
            return resp
    if use_sample and (manuscript is None or not manuscript.filename):
        async with _PIPELINE_SEMAPHORE:
            resp = JSONResponse(await asyncio.to_thread(_run_sample, "rf-biosensor"))
            if is_new:
                _attach_sid_cookie(resp, sid)
            return resp
    if manuscript is None or not manuscript.filename:
        raise HTTPException(status_code=400, detail="Select a .doc/.docx file or choose a sample manuscript.")

    await _verify_turnstile_if_configured(cf_turnstile_response, _client_ip(request))

    ext = Path(manuscript.filename).suffix.lower()
    if ext not in (".doc", ".docx"):
        raise HTTPException(status_code=400, detail="Only .doc and .docx manuscripts are supported.")

    run_id = uuid.uuid4().hex[:12]
    run_dir = RUNS_DIR / run_id
    upload_dir = run_dir / "_upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    try:
        safe_ms_name = _safe_filename(manuscript.filename, f"manuscript{ext}")
        ms_path = upload_dir / safe_ms_name
        await _save_upload_limited(manuscript, ms_path, MAX_MANUSCRIPT_BYTES, "Manuscript file")

        if figure is not None and figure.filename:
            fig_ext = Path(figure.filename).suffix.lower()
            if fig_ext not in ALLOWED_FIGURE_EXTS:
                raise HTTPException(status_code=400, detail="Unsupported figure format. Use PNG, JPG, or TIFF.")
            fig_path = upload_dir / _safe_filename(figure.filename, f"figure{fig_ext}")
            await _save_upload_limited(figure, fig_path, MAX_FIGURE_BYTES, "Figure image")

        async with _PIPELINE_SEMAPHORE:
            res = await asyncio.to_thread(
                run_pipeline,
                ms_path,
                run_dir,
                asset_search_dirs=[upload_dir, SAMPLES_DIR],
                asset_url_prefix=f"/runs/{run_id}/assets/",
            )
    except HTTPException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Could not process manuscript: {exc}") from exc

    payload = _serialize_result(run_id, res)
    _save_and_prune(payload, owner_sid=sid)
    resp = JSONResponse(payload)
    if is_new:
        _attach_sid_cookie(resp, sid)
    return resp

def _merge_prior_fixed_findings(
    updated: dict[str, Any],
    prior_payload: dict[str, Any],
    applied_fix: dict[str, str] | None = None,
) -> None:
    prior_fixed = [f for f in prior_payload.get("findings", []) if f.get("severity") == "fixed"]
    new_findings = list(updated.get("findings", []))
    if applied_fix:
        prior_fixed.append(
            {
                "rule_id": applied_fix["rule_id"],
                "severity": "fixed",
                "category": "Human-Verified Fix",
                "location": applied_fix["location"],
                "message": f"Applied human-verified fix: {applied_fix['value']}.",
                "before": applied_fix.get("before", ""),
                "after": applied_fix["value"],
                "guideline_ref": "Protocol Integrator Review Resolution",
                "auto_fixed": False,
                "confidence": "deterministic",
                "suggested_query": "",
                "review_tool": "",
            }
        )
    merged = prior_fixed + new_findings
    updated["findings"] = merged
    updated["summary_counts"] = {
        "fixed": sum(1 for f in merged if f.get("severity") == "fixed"),
        "warnings": sum(1 for f in merged if f.get("severity") == "warning"),
        "errors": sum(1 for f in merged if f.get("severity") == "error"),
    }


@app.post("/api/runs/{run_id}/apply-fix")
async def apply_fix_endpoint(request: Request, run_id: str, body: dict[str, Any] = Body(...)):
    _enforce_rate(request, "mutate", limit=30, window_sec=60)
    run_dir = _validate_run_id(run_id)
    payload = STORE.get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Run not found.")

    rule_id = str(body.get("rule_id", "")).strip()
    location = str(body.get("location", "")).strip()
    value = str(body.get("value", "")).strip()
    if not rule_id or not location or not value or len(value) > 500:
        raise HTTPException(status_code=400, detail="Valid rule_id, location, and value are required.")

    prior_match = next(
        (f for f in payload.get("findings", []) if f.get("rule_id") == rule_id and f.get("location") == location),
        None,
    )
    ms = manuscript_from_dict(payload["manuscript_data"])
    applied = apply_review_fix(ms, rule_id=rule_id, location=location, value=value)
    if not applied:
        raise HTTPException(status_code=422, detail=f"Could not apply fix for {rule_id} at {location}.")

    stem = _safe_filename(Path(ms.source_filename or "manuscript").stem.replace("_messy", ""), "manuscript")
    search_dirs = [run_dir / "_upload", run_dir / "_converted" / "_media", SAMPLES_DIR]
    async with _PIPELINE_SEMAPHORE:
        res = await asyncio.to_thread(
            rebuild_from_manuscript,
            ms,
            output_dir=run_dir,
            stem=stem,
            asset_search_dirs=search_dirs,
            asset_url_prefix=f"/runs/{run_id}/assets/",
        )
    updated = _serialize_result(run_id, res, original_lines=payload.get("original_lines", []))
    _merge_prior_fixed_findings(
        updated,
        payload,
        applied_fix={
            "rule_id": rule_id,
            "location": location,
            "value": value,
            "before": prior_match.get("before", "") if prior_match else "",
        },
    )
    _save_and_prune(updated)
    return JSONResponse(updated)


@app.post("/api/runs/{run_id}/edit")
async def edit_manuscript_endpoint(request: Request, run_id: str, body: dict[str, Any] = Body(...)):
    _enforce_rate(request, "mutate", limit=30, window_sec=60)
    run_dir = _validate_run_id(run_id)
    payload = STORE.get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Run not found.")

    if len(str(body.get("title", ""))) > 500 or len(str(body.get("summary", ""))) > 10000 or len(str(body.get("abstract", ""))) > 20000:
        raise HTTPException(status_code=400, detail="Edited field exceeds maximum allowed length.")
    affs = body.get("affiliations", [])
    if isinstance(affs, list) and (len(affs) > 30 or any(len(str(a)) > 500 for a in affs)):
        raise HTTPException(status_code=400, detail="Affiliation list exceeds maximum allowed size.")

    ms = manuscript_from_dict(payload["manuscript_data"])
    update_manuscript_fields(ms, body)
    stem = _safe_filename(Path(ms.source_filename or "manuscript").stem.replace("_messy", ""), "manuscript")
    search_dirs = [run_dir / "_upload", run_dir / "_converted" / "_media", SAMPLES_DIR]
    async with _PIPELINE_SEMAPHORE:
        res = await asyncio.to_thread(
            rebuild_from_manuscript,
            ms,
            output_dir=run_dir,
            stem=stem,
            asset_search_dirs=search_dirs,
            asset_url_prefix=f"/runs/{run_id}/assets/",
        )
    updated = _serialize_result(run_id, res, original_lines=payload.get("original_lines", []))
    _merge_prior_fixed_findings(updated, payload)
    _save_and_prune(updated)
    return JSONResponse(updated)


@app.post("/api/runs/{run_id}/verify-pmc")
async def verify_pmc_endpoint(request: Request, run_id: str):
    _enforce_rate(request, "verify_pmc", limit=10, window_sec=60)
    _validate_run_id(run_id)
    payload = STORE.get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Run not found.")

    xml_text = payload.get("jats_xml", "")
    stem = _safe_filename(Path(payload.get("source_filename") or "manuscript").stem.replace("_messy", ""), "manuscript")
    async with _PIPELINE_SEMAPHORE:
        live_res = await asyncio.to_thread(verify_xml_on_live_pmc, xml_text, filename=f"{stem}.jats.xml")
    live_dict = asdict(live_res)
    STORE.update_pmc_result(run_id, live_dict)
    return JSONResponse(live_dict)

@app.get("/runs/{run_id}/preview", response_class=HTMLResponse)
async def preview_html(run_id: str):
    run_dir = _validate_run_id(run_id)
    html_files = list(run_dir.glob("*.html"))
    if not html_files:
        raise HTTPException(status_code=404, detail="HTML preview not found.")
    return HTMLResponse(html_files[0].read_text(encoding="utf-8"))


@app.get("/runs/{run_id}/assets/{filename}")
async def get_asset(run_id: str, filename: str):
    run_dir = _validate_run_id(run_id)
    if not SAFE_NAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid asset path.")
    target = (run_dir / filename).resolve()
    if not target.exists() or target.parent != run_dir.resolve():
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(target)


@app.get("/runs/{run_id}/download/{kind}")
async def download_artifact(request: Request, run_id: str, kind: str):
    _enforce_rate(request, "download", limit=30, window_sec=60)
    run_dir = _validate_run_id(run_id)
    if kind == "bundle":
        payload = STORE.get_run(run_id)
        if not payload:
            raise HTTPException(status_code=404, detail="Run not found.")
        stem = _safe_filename(Path(payload.get("source_filename") or "manuscript").stem.replace("_messy", ""), "manuscript")
        bundle_path = run_dir / f"{stem}_production_bundle.zip"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for pat in ("*.jats.xml", "*.html", "*_clean.docx", "*_qa_report.json", "*.jpg"):
                for fpath in run_dir.glob(pat):
                    zf.write(fpath, arcname=fpath.name)
            queries = [
                f"{idx}. [{f['rule_id']}] {f.get('suggested_query') or f['message']}"
                for idx, f in enumerate(
                    [x for x in payload.get("findings", []) if x["severity"] in ("warning", "error")],
                    start=1,
                )
            ]
            query_txt = "\n".join(queries) if queries else "No unresolved author queries."
            zf.writestr(f"{stem}_author_queries.txt", query_txt)
        return FileResponse(bundle_path, media_type="application/zip", filename=bundle_path.name)

    patterns = {
        "xml": ("*.jats.xml", "application/xml"),
        "html": ("*.html", "text/html"),
        "docx": ("*_clean.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "report": ("*_qa_report.json", "application/json"),
    }
    if kind not in patterns:
        raise HTTPException(status_code=400, detail="Unknown artifact kind.")
    glob_pat, media_type = patterns[kind]
    matches = list(run_dir.glob(glob_pat))
    if not matches:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(matches[0], media_type=media_type, filename=matches[0].name)
