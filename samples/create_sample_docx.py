from __future__ import annotations

import math
import zipfile
from pathlib import Path

from docx import Document
from docx.shared import Pt
from PIL import Image, ImageDraw, ImageFont


def generate_sample_figure(output_path: Path) -> Path:
    """Generate a 1600x900 scientific S21 frequency-response figure for JoVE web sizing tests."""
    width, height = 1600, 900
    img = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arial.ttf", 30)
        font_axis = ImageFont.truetype("arial.ttf", 22)
        font_tick = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font_title = ImageFont.load_default()
        font_axis = ImageFont.load_default()
        font_tick = ImageFont.load_default()

    left, top, right, bottom = 160, 110, 1480, 760
    draw.rectangle([left, top, right, bottom], outline="#1E293B", width=3)

    for i in range(1, 6):
        y = top + int((bottom - top) * i / 6)
        draw.line([(left, y), (right, y)], fill="#E2E8F0", width=2)
    for i in range(1, 8):
        x = left + int((right - left) * i / 8)
        draw.line([(x, top), (x, bottom)], fill="#E2E8F0", width=2)

    draw.text(
        (left, 42),
        "Figure 1: Calibrated S21 Transmission Response Across 1.70 - 1.90 GHz",
        fill="#0F172A",
        font=font_title,
    )
    draw.text((700, 820), "Frequency (GHz)", fill="#0F172A", font=font_axis)
    draw.text((24, 410), "S21 (dB)", fill="#0F172A", font=font_axis)

    freqs = [1.70 + 0.025 * i for i in range(9)]
    for i, f in enumerate(freqs):
        x = left + int((right - left) * i / 8)
        draw.text((x - 22, bottom + 16), f"{f:.3f}", fill="#334155", font=font_tick)

    dbs = [0, -5, -10, -15, -20, -25, -30]
    for i, db in enumerate(dbs):
        y = top + int((bottom - top) * i / 6)
        draw.text((left - 62, y - 10), f"{db}", fill="#334155", font=font_tick)

    pts_uncal = []
    pts_cal = []
    n_pts = 200
    for i in range(n_pts):
        t = i / (n_pts - 1)
        x = left + int((right - left) * t)
        db_uncal = -14.5 - 3.2 * math.sin(t * 10.0) - 2.0 * t
        db_cal = -10.0 + 0.35 * math.sin(t * 6.0)
        y_uncal = top + int((bottom - top) * (-db_uncal / 30.0))
        y_cal = top + int((bottom - top) * (-db_cal / 30.0))
        pts_uncal.append((x, y_uncal))
        pts_cal.append((x, y_cal))

    draw.line(pts_uncal, fill="#DC2626", width=4)
    draw.line(pts_cal, fill="#1D4ED8", width=5)

    lx, ly = 1080, 145
    draw.rectangle([lx, ly, lx + 360, ly + 110], fill="#F8FAFC", outline="#94A3B8", width=2)
    draw.line([(lx + 20, ly + 35), (lx + 75, ly + 35)], fill="#1D4ED8", width=5)
    draw.text((lx + 90, ly + 22), "SOLT Calibrated (-10.0 dB)", fill="#0F172A", font=font_tick)
    draw.line([(lx + 20, ly + 75), (lx + 75, ly + 75)], fill="#DC2626", width=4)
    draw.text((lx + 90, ly + 62), "Uncalibrated Baseline", fill="#0F172A", font=font_tick)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path


def generate_coip_figure(output_path: Path) -> Path:
    """Generate a 1500x840 bar chart figure for the Co-IP phosphatase assay sample."""
    width, height = 1500, 840
    img = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arial.ttf", 28)
        font_axis = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font_title = ImageFont.load_default()
        font_axis = ImageFont.load_default()

    left, top, right, bottom = 160, 110, 1380, 700
    draw.rectangle([left, top, right, bottom], outline="#1E293B", width=3)
    draw.text((left, 42), "Figure 1: On-Bead SHP2 Phosphatase Activity (OD 405 nm)", fill="#0F172A", font=font_title)

    bars = [
        ("WT PD-1", 1.00, "#1E40AF"),
        ("Y223F (ITIM)", 0.24, "#B45309"),
        ("Y248F (ITSM)", 0.12, "#991B1B"),
        ("Control", 0.08, "#64748B"),
    ]
    slot_w = (right - left) // len(bars)
    for idx, (label, val, color) in enumerate(bars):
        bx0 = left + idx * slot_w + 65
        bx1 = bx0 + slot_w - 130
        bh = int((bottom - top - 40) * val)
        by0 = bottom - bh
        draw.rectangle([bx0, by0, bx1, bottom], fill=color)
        draw.text((bx0 + 10, bottom + 18), label, fill="#0F172A", font=font_axis)
        draw.text((bx0 + 25, by0 - 30), f"{val:.2f} RU", fill="#0F172A", font=font_axis)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path


def _add_mixed_paragraph(doc: Document, parts: list[tuple[str, dict]]) -> None:
    p = doc.add_paragraph()
    for text, fmt in parts:
        run = p.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        if fmt.get("bold"):
            run.bold = True
        if fmt.get("italic"):
            run.italic = True
        if fmt.get("sub"):
            run.font.subscript = True
        if fmt.get("sup"):
            run.font.superscript = True


def generate_messy_sample_docx(output_path: Path) -> Path:
    """Sample 1: RF & Microfluidic Biosensor Protocol with entity, SI, and review issues."""
    doc = Document()

    doc.add_heading("TITLE", level=1)
    doc.add_paragraph(
        "Two-Port Vector Network Analyzer Calibration and Microfluidic Biosensor Impedance Assay"
    )

    doc.add_heading("METADATA", level=1)
    doc.add_paragraph("Subject Area: Bioengineering")
    doc.add_paragraph("DOI: 10.3791/60874-demo")
    doc.add_paragraph("Publisher ID: 60874-demo")
    doc.add_paragraph("Publication Date: 2026-11-23")
    doc.add_paragraph(
        "Keywords: Vector Network Analyzer, SOLT calibration, S-parameters, microfluidic impedance, E. coli"
    )

    doc.add_heading("AUTHORS AND AFFILIATIONS", level=1)
    doc.add_paragraph("Elena Rostova [1,*]; Marcus Chen [2]; Priya Nair [1]")
    doc.add_paragraph("1: Dept. of Biomedical Engineering, Cambridge Institute of Technology")
    doc.add_paragraph("2: RF Photonics Laboratory, Boston Metro University")
    doc.add_paragraph("Correspondence: Elena Rostova <e.rostova@cambridge-tech.edu>")

    doc.add_heading("SUMMARY", level=1)
    doc.add_paragraph(
        "This protocol details a reproducible two-port Short-Open-Load-Thru (SOLT) calibration workflow "
        "for measuring S21 attenuation and complex impedance in temperature-controlled micro\ufb02uidic channels."
    )

    doc.add_heading("ABSTRACT", level=1)
    _add_mixed_paragraph(
        doc,
        [
            (
                "Accurate radio-frequency (RF) characterization of biological suspensions requires removing "
                "systematic cable and connector errors prior to sample loading. Here, we present a standardized "
                "calibration and measurement protocol using a two-port vector network analyzer (VNA) across "
                "1.70-1.90GHz. Samples containing ",
                {},
            ),
            ("Escherichia coli", {"italic": True}),
            (" suspensions (5 x 106 cells/mL) are equilibrated at 37ºC in 5% CO", {}),
            ("2", {"sub": True}),
            (
                " and injected at 50uL per channel. Using a 10 dB +/- 0.5 dB reference attenuator and 50 Ω "
                "termination standards, the calibrated S",
                {},
            ),
            ("21", {"sub": True}),
            (" baseline achieves sub-0.2 dB ripple, enabling reliable detection of dielectric shifts.", {}),
        ],
    )

    doc.add_heading("INTRODUCTION", level=1)
    _add_mixed_paragraph(
        doc,
        [
            (
                "Microwave and RF micro\ufb02uidic sensors enable label-free dielectric spectroscopy of bacterial "
                "cultures such as E. coli without \ufb02uorescent dyes [1]. However, uncalibrated coaxial cables, "
                "adapters, and thermal drift introduce phase and magnitude errors that obscure subtle biological "
                "signals in S11 and S21 spectra [2].",
                {},
            ),
        ],
    )
    _add_mixed_paragraph(
        doc,
        [
            (
                "To ensure cross-laboratory reproducibility, the measurement plane must be shifted directly to "
                "the micro\ufb02uidic launch connectors via a full two-port SOLT calibration [3]. Before sample "
                "injection, optical density is verified on a NanoDrop™ spectrophotometer and channels are "
                "rinsed with 0.1% Triton® X-100 buffer\u200b.",
                {},
            )
        ],
    )

    doc.add_heading("PROTOCOL", level=1)
    doc.add_paragraph("1. VNA Setup and Thermal Equilibration")
    _add_mixed_paragraph(
        doc,
        [
            (
                "1.1 Power on the VNA and allow the internal oscillator to warm up for 30min at 23ºC ambient "
                "temperature before connecting coaxial test cables.",
                {},
            )
        ],
    )
    _add_mixed_paragraph(
        doc,
        [
            (
                "1.2 Configure the frequency sweep from 1.70GHz to 1.90GHz with 201 points and an intermediate "
                "frequency (IF) bandwidth of 1 kHz. Compute the frequency step size using Equation 1.",
                {},
            )
        ],
    )
    doc.add_paragraph(
        "NOTE: Maintain coaxial cable bend radii above 5 cm during sweep configuration to prevent phase drift."
    )
    doc.add_paragraph("2. Two-Port SOLT Calibration and Sample Loading")
    _add_mixed_paragraph(
        doc,
        [
            (
                "2.1 Clean all SMA connector interfaces with compressed dry air and torque each 50 Ω calibration "
                "standard (Open, Short, Load, Thru) to 0.9 N·m at room temperature.",
                {},
            )
        ],
    )
    _add_mixed_paragraph(
        doc,
        [
            (
                "2.1.1 Verify the calibrated S21 response using a 10 dB +/- 0.5 dB reference attenuator (Figure 1).",
                {},
            ),
        ],
    )
    _add_mixed_paragraph(
        doc,
        [
            (
                "2.2 Pellet E. coli cultures at 12,000 rpm for 5min at 4ºC, resuspend in 10mM PBS, and inject "
                "50µL into the microfluidic channel equilibrated at 37°C.",
                {},
            )
        ],
    )
    doc.add_paragraph(
        "CAUTION: Handle 30% H2O2 cleaning solution inside a certified chemical fume hood with nitrile gloves."
    )

    doc.add_heading("EQUATIONS", level=1)
    doc.add_paragraph(
        "Equation 1 | \\Delta f = \\frac{f_{\\max} - f_{\\min}}{N - 1} | Frequency step size calculation in MHz"
    )

    doc.add_heading("REPRESENTATIVE RESULTS", level=1)
    _add_mixed_paragraph(
        doc,
        [
            (
                "Following two-port SOLT calibration, the measured S21 transmission across 1.70-1.90 GHz "
                "stabilized at -10.0 dB +/- 0.2 dB compared with the uncalibrated baseline showing up to 4.5 dB "
                "ripple (Figure 1). [Place Figure 1 here]",
                {},
            ),
        ],
    )

    doc.add_heading("FIGURE LEGENDS", level=1)
    doc.add_paragraph(
        "Figure 1 | Calibrated S21 Transmission Response | Comparison of SOLT-calibrated (-10.0 dB) and "
        "uncalibrated baseline S21 transmission across 1.70 to 1.90 GHz. | "
        "ALT: Line graph comparing SOLT calibrated S21 transmission near minus 10 dB against uncalibrated baseline ripple from 1.70 to 1.90 GHz. | "
        "FILE: fig1_raw.png"
    )

    doc.add_heading("TABLE OF MATERIALS", level=1)
    table = doc.add_table(rows=5, cols=4)
    headers = ["Name", "Company", "Catalog Number", "Comments"]
    rows_data = [
        ["Triton X-100", "Sigma-Aldrich", "T8787", "0.1% v/v channel rinse"],
        ["Calibration Kit (3.5 mm SOLT)", "Keysight Technologies", "85052D", "50 Ohm Open/Short/Load/Thru"],
        ["Phosphate-Buffered Saline (10 mM)", "Thermo Fisher Scientific", "10010023", "pH 7.4 sterile buffer"],
        ["E. coli K-12 MG1655", "ATCC", "700926", "Biosafety Level 1 strain"],
    ]
    for col_idx, h in enumerate(headers):
        table.rows[0].cells[col_idx].text = h
    for row_idx, row_vals in enumerate(rows_data, start=1):
        for col_idx, val in enumerate(row_vals):
            table.rows[row_idx].cells[col_idx].text = val

    doc.add_heading("DISCUSSION", level=1)
    doc.add_paragraph(
        "Proper SOLT calibration eliminates systematic cable attenuation and connector mismatch errors prior "
        "to biological impedance measurements. Maintaining strict temperature control at 37 °C and consistent "
        "50 µL injection volumes ensures repeatable S21 baselines across independent microfluidic chips."
    )

    doc.add_heading("ACKNOWLEDGMENTS", level=1)
    doc.add_paragraph("This work was supported by the Bioengineering Instrumentation Core Grant BIO-2026-04.")

    doc.add_heading("DISCLOSURES", level=1)
    doc.add_paragraph("The authors have nothing to disclose.")

    doc.add_heading("REFERENCES", level=1)
    doc.add_paragraph(
        "1. Chen, M., Nair, P. Dielectric spectroscopy of bacterial suspensions in microfluidic channels. "
        "Biosens. Bioelectron. 198 (2), 113842 (2024). DOI: 10.1016/j.bios.2024.113842"
    )
    doc.add_paragraph(
        "2. Rostova, E., Chen, M. Two-port vector network analyzer error correction for RF propagation. "
        "IEEE Trans. Microw. Theory Tech. 71 (4), 1520-1531 (2023). DOI: 10.1109/TMTT.2023.3241100"
    )
    doc.add_paragraph(
        "3. Peled, M., Strazza, M., Mor, A. Co-immunoprecipitation assay for studying functional interactions "
        "between receptors and enzymes. J. Vis. Exp. (139), e58433 (2018). DOI: 10.3791/58433"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    return output_path


def generate_coip_hazards_docx(output_path: Path) -> Path:
    """Sample 2: Co-IP Assay with OOXML Track Changes, Comments, Greek homoglyphs, and step/ref hazards."""
    doc = Document()

    doc.add_heading("TITLE", level=1)
    doc.add_paragraph("Functional Co-Immunoprecipitation and On-Bead SHP2 Phosphatase Assay")

    doc.add_heading("METADATA", level=1)
    doc.add_paragraph("Subject Area: Immunology and Infection")
    doc.add_paragraph("DOI: 10.3791/58433-demo")
    doc.add_paragraph("Publisher ID: 58433-demo")
    doc.add_paragraph("Publication Date: 2026-11-23")
    doc.add_paragraph("Keywords: Co-immunoprecipitation, SHP2, PD-1, phosphatase assay, HEK 293T")

    doc.add_heading("AUTHORS AND AFFILIATIONS", level=1)
    doc.add_paragraph("Michael Peled [1,*]; Marianne Strazza [2]; Adam Mor [2]")
    doc.add_paragraph("1: Pulmonary Dept., Chaim Sheba Medical Center")
    doc.add_paragraph("2: Columbia Center for Translational Immunology, Columbia University Medical Center")
    doc.add_paragraph("Correspondence: Michael Peled <m.peled@sheba-med.org>")

    doc.add_heading("SUMMARY", level=1)
    doc.add_paragraph(
        "This assay combines anti-GFP co-immunoprecipitation with an on-bead colorimetric phosphatase assay "
        "to separate SHP2 recruitment from catalytic activation."
    )

    doc.add_heading("ABSTRACT", level=1)
    doc.add_paragraph(
        "Receptor-associated phosphatases regulate T-cell signaling through sequential SH2 domain binding. "
        "Here, HEK 293T cells expressing wild-type or mutant PD-1-GFP are treated with pervanadate, lysed "
        "at 4ºC, and incubated with anti-GFP agarose beads. Bound SHP2 levels and pNPP dephosphorylation "
        "at 405 nm are quantified in parallel from the same immunoprecipitate."
    )

    doc.add_heading("INTRODUCTION", level=1)
    doc.add_paragraph(
        "Programmed death-1 (PD-1) recruits SHP2 via phosphorylated ITIM and ITSM motifs [2]. "
        "Previous studies showed that TNF-a stimulation alters receptor clustering [1]."
    )

    doc.add_heading("PROTOCOL", level=1)
    doc.add_paragraph("1. Cell Transfection and Pervanadate Treatment")
    doc.add_paragraph("1.1 Seed 5 x 10^6 HEK 293T cells per 10 cm plate and incubate overnight at 37ºC in 5% CO2.")
    doc.add_paragraph("1.3 Prepare fresh pervanadate by mixing 50uL sodium orthovanadate with 50uL 30% H2O2.")
    doc.add_paragraph("NOTE: Protect pervanadate-treated plates from light during the 15min incubation.")
    doc.add_paragraph("2. Immunoprecipitation and On-Bead Assay")
    doc.add_paragraph("2.1 Lyse cells in buffer supplemented with 1 mM b-mercaptoethanol and protease inhibitors.")
    doc.add_paragraph("2.2 Spin lysates at 10,000 rpm for 10min at 4°C and measure absorbance at 405 nm (Figure 1).")

    doc.add_heading("REPRESENTATIVE RESULTS", level=1)
    doc.add_paragraph(
        "Mutation of the ITSM motif (Y248F) abolished SHP2 binding, whereas ITIM mutation (Y223F) reduced "
        "catalytic activity despite partial recruitment (Figure 1). [Place Figure 1 here]"
    )

    doc.add_heading("FIGURE LEGENDS", level=1)
    doc.add_paragraph(
        "Figure 1 | On-Bead SHP2 Phosphatase Activity | Relative optical density at 405 nm across WT, Y223F, "
        "and Y248F PD-1-GFP immunoprecipitates. | "
        "ALT: Bar chart comparing relative SHP2 phosphatase activity across WT PD-1, Y223F, Y248F, and control beads. | "
        "FILE: fig2_coip_raw.png"
    )

    doc.add_heading("TABLE OF MATERIALS", level=1)
    table = doc.add_table(rows=4, cols=4)
    headers = ["Name", "Company", "Catalog Number", "Comments"]
    rows_data = [
        ["p-Nitrophenylphosphate (pNPP)", "Sigma-Aldrich", "N4645", "10 mM substrate"],
        ["Anti-GFP Agarose Beads", "Chromotek", "TBD", "40 uL slurry per sample"],
        ["DMEM High Glucose", "Thermo Fisher Scientific", "11965092", "Supplemented with 10% FBS"],
    ]
    for col_idx, h in enumerate(headers):
        table.rows[0].cells[col_idx].text = h
    for row_idx, row_vals in enumerate(rows_data, start=1):
        for col_idx, val in enumerate(row_vals):
            table.rows[row_idx].cells[col_idx].text = val

    doc.add_heading("DISCUSSION", level=1)
    doc.add_paragraph(
        "Parallel measurement of SHP2 binding and enzymatic turnover distinguishes docking motifs from "
        "allosteric activation domains."
    )

    doc.add_heading("ACKNOWLEDGMENTS", level=1)
    doc.add_paragraph("Supported by NIH Grant 1R01AI125640-01.")

    doc.add_heading("DISCLOSURES", level=1)
    doc.add_paragraph("The authors have nothing to disclose.")

    doc.add_heading("REFERENCES", level=1)
    doc.add_paragraph(
        "1. Okazaki, T., Maeda, A., Honjo, T. PD-1 immunoreceptor inhibits B cell receptor signaling. "
        "Proc. Natl. Acad. Sci. U.S.A. 98 (24), 13866-13871 (2001). DOI: 10.1073/pnas.231486598"
    )
    doc.add_paragraph(
        "2. Chemnitz, J. M., Riley, J. L. SHP-1 and SHP-2 associate with ITSM of PD-1. "
        "J. Immunol. 173 (2), 945-954 (2004). DOI: 10.4049/jimmunol.173.2.945"
    )

    raw_path = output_path.with_suffix(".tmp.docx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(raw_path)

    # Inject realistic unaccepted Track Change (w:ins) and unresolved Word comment (word/comments.xml)
    with zipfile.ZipFile(raw_path, "r") as zin, zipfile.ZipFile(output_path, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml_str = data.decode("utf-8").replace(
                    "<w:t>1.3 Prepare fresh pervanadate by mixing 50uL sodium orthovanadate with 50uL 30% H2O2.</w:t>",
                    '<w:ins w:id="1" w:author="Coauthor"><w:t>1.3 Prepare fresh pervanadate by mixing 50uL sodium orthovanadate with 50uL 30% H2O2.</w:t></w:ins>',
                )
                data = xml_str.encode("utf-8")
            zout.writestr(item, data)
        zout.writestr(
            "word/comments.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:comment w:id="0" w:author="PI"><w:p><w:r><w:t>Confirm rotor radius for 10,000 rpm step.</w:t></w:r></w:p></w:comment>'
            "</w:comments>",
        )
    raw_path.unlink(missing_ok=True)
    return output_path


def generate_clean_ready_docx(output_path: Path) -> Path:
    """Sample 3: Clean, publication-ready JoVE manuscript passing with 0 errors and 0 warnings."""
    doc = Document()

    doc.add_heading("TITLE", level=1)
    doc.add_paragraph("Standardized Two-Port SOLT Calibration for Microfluidic RF Impedance Spectroscopy")

    doc.add_heading("METADATA", level=1)
    doc.add_paragraph("Subject Area: Bioengineering")
    doc.add_paragraph("DOI: 10.3791/60874-clean")
    doc.add_paragraph("Publisher ID: 60874-clean")
    doc.add_paragraph("Publication Date: 2026-11-23")
    doc.add_paragraph("Keywords: Vector Network Analyzer, SOLT calibration, microfluidic impedance, S-parameters")

    doc.add_heading("AUTHORS AND AFFILIATIONS", level=1)
    doc.add_paragraph("Elena Rostova [1,*]; Marcus Chen [2]")
    doc.add_paragraph("1: Department of Biomedical Engineering, Cambridge Institute of Technology")
    doc.add_paragraph("2: RF Photonics Laboratory, Boston Metro University")
    doc.add_paragraph("Correspondence: Elena Rostova <e.rostova@cambridge-tech.edu>")

    doc.add_heading("SUMMARY", level=1)
    doc.add_paragraph(
        "This protocol establishes a verified two-port Short-Open-Load-Thru calibration workflow for "
        "reproducible microfluidic impedance measurements across 1.70 to 1.90 GHz."
    )

    doc.add_heading("ABSTRACT", level=1)
    _add_mixed_paragraph(
        doc,
        [
            (
                "Radio-frequency dielectric spectroscopy of biological suspensions requires shifting the "
                "measurement reference plane directly to the microfluidic launch connectors prior to sample "
                "loading. Here, we describe a standardized two-port Short-Open-Load-Thru (SOLT) calibration "
                "procedure across 1.70 to 1.90 GHz using 50 Ω standards and a 10 dB ± 0.5 dB reference "
                "attenuator. Bacterial suspensions of ",
                {},
            ),
            ("Escherichia coli", {"italic": True}),
            (" at 5 × 10", {}),
            ("6", {"sup": True}),
            (" cells/mL are equilibrated at 37 °C in 5% CO", {}),
            ("2", {"sub": True}),
            (
                " and injected at 50 µL per channel. Following calibration, transmission ripple remains below "
                "0.2 dB across the full sweep, enabling quantitative comparison of cellular dielectric shifts "
                "between independent microfluidic devices and laboratories. All reagents, centrifugation forces, "
                "and thermal equilibration intervals are specified in SI units to ensure full experimental "
                "reproducibility and direct compliance with PubMed Central JATS XML indexing standards.",
                {},
            ),
        ],
    )

    doc.add_heading("INTRODUCTION", level=1)
    doc.add_paragraph(
        "Label-free microwave microfluidic sensors detect dielectric permittivity changes in bacterial "
        "suspensions without fluorescent labels [1, 2]. Systematic cable attenuation and connector mismatch "
        "must be removed via two-port SOLT calibration before biological testing [3, 4, 5]."
    )
    doc.add_paragraph(
        "Standardizing thermal equilibration, buffer composition, and calibration verification ensures "
        "consistent baseline transmission across laboratories [6, 7, 8, 9, 10]."
    )

    doc.add_heading("PROTOCOL", level=1)
    doc.add_paragraph("1. VNA Warm-Up and Sweep Configuration")
    doc.add_paragraph(
        "1.1 Power on the vector network analyzer and equilibrate for 30 min at 23 °C before attaching cables."
    )
    doc.add_paragraph(
        "1.2 Set the frequency sweep from 1.70 GHz to 1.90 GHz with 201 points and compute step size via Equation 1."
    )
    doc.add_paragraph("2. Calibration Verification and Sample Injection")
    _add_mixed_paragraph(
        doc,
        [
            ("2.1 Torque each 50 Ω calibration standard to 0.9 N·m at 22 °C and verify S", {}),
            ("21", {"sub": True}),
            (" with a 10 dB ± 0.5 dB attenuator (Figure 1).", {}),
        ],
    )
    _add_mixed_paragraph(
        doc,
        [
            ("2.2 Pellet ", {}),
            ("E. coli", {"italic": True}),
            (" cultures at 13,684 x g for 5 min at 4 °C, resuspend in 10 mM PBS, and inject 50 µL at 37 °C.", {}),
        ],
    )

    doc.add_heading("EQUATIONS", level=1)
    doc.add_paragraph(
        "Equation 1 | \\Delta f = \\frac{f_{\\max} - f_{\\min}}{N - 1} | Frequency step size calculation in MHz"
    )

    doc.add_heading("REPRESENTATIVE RESULTS", level=1)
    _add_mixed_paragraph(
        doc,
        [
            ("Calibrated S", {}),
            ("21", {"sub": True}),
            (" transmission stabilized at -10.0 dB ± 0.2 dB across 1.70 to 1.90 GHz (Figure 1).", {}),
        ],
    )

    doc.add_heading("FIGURE LEGENDS", level=1)
    doc.add_paragraph(
        "Figure 1 | Calibrated S21 Transmission Response | Comparison of SOLT-calibrated (-10.0 dB) and "
        "uncalibrated baseline transmission across 1.70 to 1.90 GHz. | "
        "ALT: Line graph comparing SOLT calibrated S21 transmission near minus 10 dB against uncalibrated baseline ripple from 1.70 to 1.90 GHz. | "
        "FILE: fig1_raw.png"
    )

    doc.add_heading("TABLE OF MATERIALS", level=1)
    table = doc.add_table(rows=4, cols=4)
    headers = ["Name", "Company", "Catalog Number", "Comments"]
    rows_data = [
        ["Calibration Kit (3.5 mm SOLT)", "Keysight Technologies", "85052D", "50 Ohm Open/Short/Load/Thru"],
        ["Phosphate-Buffered Saline (10 mM)", "Thermo Fisher Scientific", "10010023", "pH 7.4 sterile buffer"],
        ["Triton X-100", "Sigma-Aldrich", "T8787", "0.1% (v/v) channel rinse"],
    ]
    for col_idx, h in enumerate(headers):
        table.rows[0].cells[col_idx].text = h
    for row_idx, row_vals in enumerate(rows_data, start=1):
        for col_idx, val in enumerate(row_vals):
            table.rows[row_idx].cells[col_idx].text = val

    doc.add_heading("DISCUSSION", level=1)
    doc.add_paragraph(
        "Two-port SOLT calibration removes systematic fixture errors and yields reproducible impedance baselines."
    )

    doc.add_heading("ACKNOWLEDGMENTS", level=1)
    doc.add_paragraph("Supported by Bioengineering Instrumentation Core Grant BIO-2026-04.")

    doc.add_heading("DISCLOSURES", level=1)
    doc.add_paragraph("The authors have nothing to disclose.")

    doc.add_heading("REFERENCES", level=1)
    for i in range(1, 11):
        doc.add_paragraph(
            f"{i}. Author, A. Reference study {i} on RF microfluidic calibration. "
            f"J. Vis. Exp. (140), e6087{i} (2024). DOI: 10.3791/6087{i}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    return output_path


def generate_natural_figure(output_path: Path) -> Path:
    """Generate a 1200x600 flowchart figure (intentionally below JoVE 1440px min width)."""
    width, height = 1200, 600
    img = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("arial.ttf", 26)
        font_box = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font_title = ImageFont.load_default()
        font_box = ImageFont.load_default()

    draw.text((60, 36), "Figure 1: PGM Precipitation & Filtration Workflow", fill="#0F172A", font=font_title)
    boxes = [
        (60, 160, 360, 320, "1. Leachate\n(pH 1.2, HCl)"),
        (450, 160, 750, 320, "2. SnCl2 + TeO2\nCo-Precipitation"),
        (840, 160, 1140, 320, "3. 4,500 rpm Spin\n& H2O Rinse"),
    ]
    for x0, y0, x1, y1, label in boxes:
        draw.rectangle([x0, y0, x1, y1], fill="#EFF6FF", outline="#1D4ED8", width=3)
        draw.text((x0 + 24, y0 + 48), label, fill="#0F172A", font=font_box)
    draw.line([(360, 240), (450, 240)], fill="#1E293B", width=4)
    draw.line([(750, 240), (840, 240)], fill="#1E293B", width=4)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path


def generate_natural_manuscript_docx(output_path: Path) -> Path:
    """Sample 4: Natural unstructured Word manuscript without synthetic METADATA/FIGURE tags."""
    from docx.oxml import OxmlElement
    from docx.shared import Inches

    doc = Document()
    doc.add_paragraph("Supplementary File")
    doc.add_paragraph("Catalytic Recovery of Platinum-Group Metals from Spent Autocatalyst Leachate", style="Title")
    doc.add_paragraph("Claire Moreau†, Lukas Weber1, Kenji Sato1*")
    doc.add_paragraph("†Department of Analytical Chemistry, Lyon Institute of Technology")
    doc.add_paragraph("1Institute for Sustainable Metallurgy, Zurich")

    p_corr = doc.add_paragraph("*Corresponding author: ")
    hl = OxmlElement("w:hyperlink")
    r_hl = OxmlElement("w:r")
    t_hl = OxmlElement("w:t")
    t_hl.text = "k.sato@ism-zurich.example"
    r_hl.append(t_hl)
    hl.append(r_hl)
    p_corr._element.append(hl)

    doc.add_heading("Abstract", level=1)
    doc.add_paragraph(
        "Selective recovery of palladium, platinum, and rhodium from acidic chloride leachates remains "
        "challenging in the presence of excess base metals. Here we describe a tellurium-assisted "
        "co-precipitation protocol using stannous chloride reduction at ambient pressure. Following "
        "acidification and reagent addition, quantitative precipitation is achieved within 30 min, "
        "yielding a compact precipitate suitable for gravimetric and ICP-OES quantification (Figure 1). "
        "This workflow builds on prior hydrometallurgical separation studies (Moreau, 2023) and "
        "provides reproducible recovery across spent automotive catalyst batches without organic "
        "solvent extraction or high-temperature smelting steps."
    )

    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph(
        "Tellurium co-precipitation isolates trace PGMs from sodium-rich chloride media（pH 1.2）"
        "using SnCl2 and TeO2 carriers (Moreau, 2023; Weber, 2024)."
    )

    doc.add_heading("Materials and Methods", level=1)
    doc.add_paragraph("2.1 Reagent Preparation")
    doc.add_paragraph("2.1.1 Dissolve 11,4% SnCl2 in 100 ml of 37% HCl and add 0.25g TeO2.")
    doc.add_paragraph("2.2 Precipitation and Filtration")
    doc.add_paragraph("2.2.1 Spin suspension at 4,500 rpm for 10min at 22°C (Figure 1).")

    tbl = doc.add_table(rows=3, cols=3)
    tbl.cell(0, 0).text = "Stage"
    tbl.cell(0, 1).text = "Operation"
    tbl.cell(0, 2).text = "Target"
    tbl.cell(1, 0).text = "Precipitation"
    tbl.cell(1, 1).text = "Add SnCl2 + TeO2 carrier"
    tbl.cell(1, 2).text = "Pd / Pt / Rh"
    tbl.cell(2, 0).text = "Precipitation"
    tbl.cell(2, 1).text = "Rinse precipitate with 50 ml H2O"
    tbl.cell(2, 2).text = "< 0.1% Cl"
    tbl.cell(1, 0).merge(tbl.cell(2, 0))

    fig_tmp = output_path.parent / "_tmp_fig4.png"
    generate_natural_figure(fig_tmp)
    p_img = doc.add_paragraph()
    p_img.add_run().add_picture(str(fig_tmp), width=Inches(5.5))
    fig_tmp.unlink(missing_ok=True)

    doc.add_heading("References", level=1)
    doc.add_paragraph(
        "1.\tMoreau, C. 2023. Hydrometallurgical recovery of PGMs. J. Clean. Prod. 412, 137401. "
        "DOI: 10.1016/j.jclepro.2023.137401"
    )
    doc.add_paragraph(
        "1.\tWeber, L. 2024. Tellurium co-precipitation kinetics. Hydrometallurgy 224, 106210. "
        "DOI: 10.1016/j.hydromet.2024.106210"
    )

    raw_path = output_path.with_suffix(".tmp.docx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(raw_path)

    fn_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:footnote w:id="1"><w:p><w:r><w:t>Analytical grade reagents (ACS >= 99.5%) were used throughout.</w:t></w:r></w:p></w:footnote>'
        b"</w:footnotes>"
    )
    with zipfile.ZipFile(raw_path, "r") as zin, zipfile.ZipFile(output_path, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml_str = data.decode("utf-8").replace(
                    'descr=""',
                    'descr="Flowchart of PGM precipitation and filtration stages."',
                )
                data = xml_str.encode("utf-8")
            zout.writestr(item, data)
        zout.writestr("word/footnotes.xml", fn_xml)
    raw_path.unlink(missing_ok=True)
    return output_path


if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    print("Generated:", generate_sample_figure(base / "fig1_raw.png"))
    print("Generated:", generate_coip_figure(base / "fig2_coip_raw.png"))
    print("Generated:", generate_messy_sample_docx(base / "sample_protocol_messy.docx"))
    print("Generated:", generate_coip_hazards_docx(base / "sample_coip_hazards.docx"))
    print("Generated:", generate_clean_ready_docx(base / "sample_clean_ready.docx"))
    print("Generated:", generate_natural_manuscript_docx(base / "sample_natural_manuscript.docx"))
