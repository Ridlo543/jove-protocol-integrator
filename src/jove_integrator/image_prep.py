from __future__ import annotations

from pathlib import Path

from PIL import Image

from .models import FigureItem, ImageAssetReport

Image.MAX_IMAGE_PIXELS = 25_000_000
JOVE_MIN_WIDTH = 1440
JOVE_MIN_HEIGHT = 480
WEB_INLINE_WIDTH = 700
WEB_LARGE_WIDTH = 1400


def prepare_figure_assets(
    figures: list[FigureItem],
    search_dirs: list[Path],
    output_dir: Path,
) -> list[ImageAssetReport]:
    """Inspect figure dimensions and generate JoVE-sized web (700px) and large (1400px) JPEGs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[ImageAssetReport] = []

    for fig in figures:
        if not fig.source_filename:
            continue
        src_path: Path | None = None
        for d in search_dirs:
            candidate = d / fig.source_filename
            if candidate.exists():
                src_path = candidate
                break
        if src_path is None:
            reports.append(
                ImageAssetReport(
                    source_path=fig.source_filename,
                    original_width=0,
                    original_height=0,
                    web_path="",
                    web_width=0,
                    web_height=0,
                    large_path="",
                    large_width=0,
                    large_height=0,
                    alt_text=fig.alt_text,
                    meets_jove_min_resolution=False,
                    warnings=[f"Source image '{fig.source_filename}' not found in search directories."],
                )
            )
            continue

        try:
            with Image.open(src_path) as im:
                rgb = im.convert("RGB")
                orig_w, orig_h = rgb.size
                meets_min = orig_w >= JOVE_MIN_WIDTH and orig_h >= JOVE_MIN_HEIGHT
                warnings: list[str] = []
                if not meets_min:
                    warnings.append(
                        f"Image {orig_w}x{orig_h}px is below JoVE minimum {JOVE_MIN_WIDTH}x{JOVE_MIN_HEIGHT}px."
                    )
                if not fig.alt_text.strip():
                    warnings.append("Missing descriptive alt text.")

                web_w = min(WEB_INLINE_WIDTH, orig_w)
                web_h = max(1, round(orig_h * (web_w / orig_w)))
                web_img = rgb.resize((web_w, web_h), Image.Resampling.LANCZOS)
                web_name = f"{fig.id}_web.jpg"
                web_path = output_dir / web_name
                web_img.save(web_path, format="JPEG", quality=90, optimize=True)

                large_w = min(WEB_LARGE_WIDTH, orig_w)
                large_h = max(1, round(orig_h * (large_w / orig_w)))
                large_img = rgb.resize((large_w, large_h), Image.Resampling.LANCZOS)
                large_name = f"{fig.id}_large.jpg"
                large_path = output_dir / large_name
                large_img.save(large_path, format="JPEG", quality=92, optimize=True)

                fig.web_filename = web_name
                fig.large_filename = large_name

                reports.append(
                    ImageAssetReport(
                        source_path=str(src_path),
                        original_width=orig_w,
                        original_height=orig_h,
                        web_path=str(web_path),
                        web_width=web_w,
                        web_height=web_h,
                        large_path=str(large_path),
                        large_width=large_w,
                        large_height=large_h,
                        alt_text=fig.alt_text,
                        meets_jove_min_resolution=meets_min,
                        warnings=warnings,
                    )
                )
        except Exception as exc:
            reports.append(
                ImageAssetReport(
                    source_path=str(src_path),
                    original_width=0,
                    original_height=0,
                    web_path="",
                    web_width=0,
                    web_height=0,
                    large_path="",
                    large_width=0,
                    large_height=0,
                    alt_text=fig.alt_text,
                    meets_jove_min_resolution=False,
                    warnings=[f"Could not rasterize '{src_path.name}': {exc}"],
                )
            )

    return reports
