from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

PMC_PAGE_URL = "https://pmc.ncbi.nlm.nih.gov/tools/stylechecker/"
PMC_API_URL = "https://pmc.ncbi.nlm.nih.gov/tools/stylechecker/api/v1/check/"


@dataclass
class LivePMCResult:
    reachable: bool
    dtd_valid: bool
    style_valid: bool
    response_date: str
    status: str
    messages: list[dict]
    error_detail: str = ""


def verify_xml_on_live_pmc(xml_text: str, filename: str = "manuscript.jats.xml") -> LivePMCResult:
    """Submit JATS XML to the official NCBI PMC StyleChecker API and return structured results."""
    try:
        with httpx.Client(timeout=25.0, follow_redirects=True) as client:
            page_resp = client.get(PMC_PAGE_URL)
            page_resp.raise_for_status()
            m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', page_resp.text)
            if not m:
                return LivePMCResult(
                    reachable=False,
                    dtd_valid=False,
                    style_valid=False,
                    response_date="",
                    status="ERROR",
                    messages=[],
                    error_detail="Could not extract CSRF token from NCBI PMC StyleChecker page.",
                )
            token = m.group(1)
            check_resp = client.post(
                PMC_API_URL,
                data={"csrfmiddlewaretoken": token},
                files={"nxml": (filename, xml_text.encode("utf-8"), "application/xml")},
                headers={"Referer": PMC_PAGE_URL, "Origin": "https://pmc.ncbi.nlm.nih.gov"},
            )
            check_resp.raise_for_status()
            payload = check_resp.json()
            return LivePMCResult(
                reachable=True,
                dtd_valid=bool(payload.get("dtd_valid", False)),
                style_valid=bool(payload.get("style_valid", False)),
                response_date=str(payload.get("responseDate", "")),
                status=str(payload.get("status", "UNKNOWN")),
                messages=list(payload.get("messages", [])),
            )
    except Exception as exc:
        return LivePMCResult(
            reachable=False,
            dtd_valid=False,
            style_valid=False,
            response_date="",
            status="UNREACHABLE",
            messages=[],
            error_detail=str(exc),
        )
