# JoVE Protocol Integrator & PMC JATS QA Workbench

End-to-end scientific publishing prototype built for the **JoVE Protocol Integrator** workflow:

1. **Word Manuscript Ingestion (`.doc` / `.docx`):** Converts legacy `.doc` to `.docx` via Microsoft Word COM (`win32com`) or LibreOffice, parses OOXML runs (`bold`, `italic`, `sub`, `sup`), nested protocol steps (`1.`, `1.1`, `1.1.1`), `NOTE:`/`CAUTION:` callouts, `Table of Materials`, figures, equations, and references.
2. **JoVE + PMC QA Linter & Auto-Normalizer:**
   - Replaces visually ambiguous degree characters (`U+00BA` / `U+1D52`) with true degree sign (`U+00B0`) per JATS4R / PMC `genprac`.
   - Strips Private Use Area characters (`U+E000`–`U+F8FF`) and body trademark/copyright symbols (`™`, `®`, `©`).
   - Normalizes Greek micro prefixes (`U+03BC` → `U+00B5`) and inserts missing spaces between numbers and SI units (`37°C` → `37 °C`, `50µL` → `50 µL`).
   - Italicizes species names (`E. coli`), applies `<sub>` to chemical formulas (`CO2`, `H2O2`), flags `rpm` centrifugation for `x g` review, sorts `Table of Materials` alphabetically, and verifies `<xref>` integrity.
3. **Web Graphics Prep:** Validates JoVE minimum resolution (`1440x480`) and generates web inline (`700px`) and high-res (`1400px`) JPEGs with `alt` text checks.
4. **Semantic HTML5/CSS & NISO JATS 1.3 XML:** Renders a JoVE-style HTML article and generates NISO JATS 1.3 XML verified with **0 errors** (`DTD Validation: OK`, `PMC Style Check: OK`) on the live NCBI PMC StyleChecker (`https://pmc.ncbi.nlm.nih.gov/tools/stylechecker/`).

## Quick Start

```bash
pip install -e ".[dev]"
python samples/create_sample_docx.py
python -m jove_integrator.cli process samples/sample_protocol_messy.docx -o output
python -m jove_integrator.cli serve --port 8765
```

Run tests:

```bash
pytest -v
```
