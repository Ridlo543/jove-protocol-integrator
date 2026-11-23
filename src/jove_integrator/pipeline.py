from __future__ import annotations

from pathlib import Path

from .editor import compute_manuscript_diff, manuscript_to_plain_lines, rebuild_from_manuscript
from .models import PipelineResult
from .word_loader import load_manuscript


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    asset_search_dirs: list[Path] | None = None,
    asset_url_prefix: str = "",
) -> PipelineResult:
    """Run full JoVE Protocol Integrator pipeline on a .doc or .docx manuscript."""
    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    work_dir = output_dir / "_converted"
    search_dirs = [input_path.parent, work_dir / "_media"]
    if asset_search_dirs:
        search_dirs.extend(asset_search_dirs)

    ms = load_manuscript(input_path, work_dir=work_dir)
    original_lines = manuscript_to_plain_lines(ms)

    stem = input_path.stem.replace("_messy", "")
    res = rebuild_from_manuscript(
        ms,
        output_dir=output_dir,
        stem=stem,
        asset_search_dirs=search_dirs,
        asset_url_prefix=asset_url_prefix,
    )
    res.original_lines = original_lines
    res.diff_rows = compute_manuscript_diff(original_lines, manuscript_to_plain_lines(res.manuscript))
    return res
