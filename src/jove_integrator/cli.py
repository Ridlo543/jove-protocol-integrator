from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jove-integrator",
        description="JoVE Protocol Integrator & PMC JATS QA Workbench",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("process", help="Process a .doc or .docx manuscript into HTML, JATS 1.3 XML, and QA report")
    p_run.add_argument("input", type=Path, help="Path to .doc or .docx manuscript")
    p_run.add_argument("-o", "--output", type=Path, default=Path("output"), help="Output directory")

    p_web = sub.add_parser("serve", help="Launch the interactive QA Workbench web UI")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()

    if args.command == "process":
        res = run_pipeline(args.input, args.output, asset_search_dirs=[Path("samples")])
        fixed = sum(1 for f in res.findings if f.severity == "fixed")
        warns = sum(1 for f in res.findings if f.severity == "warning")
        errs = sum(1 for f in res.findings if f.severity == "error")
        print(f"Processed: {res.manuscript.title}")
        print(f"QA Findings -> Auto-fixed: {fixed}, Warnings: {warns}, Errors: {errs}")
        print(f"Local XML Pre-flight -> Well-formed: {res.xml_check.well_formed}, Errors: {len(res.xml_check.errors)}")
        print(f"Clean DOCX : {res.clean_docx_path}")
        print(f"HTML5 Page : {res.html_path}")
        print(f"JATS XML   : {res.xml_path}")
        print(f"QA Report  : {res.report_path}")
    elif args.command == "serve":
        uvicorn.run("jove_integrator.web:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
