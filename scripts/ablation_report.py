"""Final blackjack ablation report: tables (LaTeX + Markdown), charts (PNG + PDF), JSON.

Usage:
    python scripts/ablation_report.py                         # discover runs/hcc_*_v3_*_seed2026*
    python scripts/ablation_report.py --label v3 --out results/
    python scripts/ablation_report.py --runs-glob 'runs/hcc_*_v3*'
    python scripts/ablation_report.py runs/dirA runs/dirB ...  # explicit run folders

With no run folders and no --runs-glob, every HCC full-run folder for --label under
--runs-dir is used (named runs/hcc_{baseline|scenarios}_<label>[_<config>]_seed2026[_<model>],
see hcc/full_run.sbatch). Each run's model and config come from its metadata; the folder
name is only a fallback. Missing runs are listed in summary.md and skipped.

Writes to --out (default results/):
    summary.md                        tables and chart links
    report.json                       every number
    tables/ablation_<model>.tex/.md   main table per model
    tables/coverage.tex/.md           covered vs uncovered accuracy
    tables/self_eval_flips.tex/.md    self-evaluation fixes and breaks
    charts/*.png (300 dpi), charts/*.pdf (vector)

All statistics come from analysis/paired.py; see analysis/ablation_report.py.
"""

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.ablation_report import (  # noqa: E402
    DEFAULT_LABEL,
    DEFAULT_SEED,
    EXPECTED_MODELS,
    build_report,
    default_classifier,
    discover_run_dirs,
    flip_rows,
    latex_coverage_table,
    latex_flips_table,
    latex_main_table,
    markdown_coverage_table,
    markdown_flips_table,
    markdown_main_table,
    model_slug,
    render_summary,
)


def write_outputs(report: dict, out: Path, charts: bool = True, titles: bool = True) -> list[Path]:
    """Write every table, chart, summary.md and report.json into out; returns the files written."""
    out.mkdir(parents=True, exist_ok=True)
    tables_dir = out / "tables"
    tables_dir.mkdir(exist_ok=True)
    written: list[Path] = []
    tables: dict[str, str] = {}

    def table(name: str, latex: str, markdown: str, what: str) -> None:
        for suffix, text in ((".tex", latex), (".md", markdown + "\n")):
            path = tables_dir / f"{name}{suffix}"
            path.write_text(text, encoding="utf-8")
            written.append(path)
        tables[f"tables/{name}.tex"] = what

    for model in report["models"]:
        table(f"ablation_{model_slug(model)}", latex_main_table(report, model), markdown_main_table(report, model),
              f"main table, {model}")
    table("coverage", latex_coverage_table(report), markdown_coverage_table(report), "covered vs uncovered accuracy")
    if flip_rows(report):
        table("self_eval_flips", latex_flips_table(report), markdown_flips_table(report),
              "self-evaluation fixes and breaks")

    chart_files: dict[str, list[str]] = {}
    if charts:
        from analysis.ablation_charts import write_charts  # matplotlib only when drawing
        chart_files = write_charts(report, out, titles=titles)
        written += [out / f for files in chart_files.values() for f in files]
    report = {**report, "charts": chart_files, "tables": sorted(tables)}

    summary = out / "summary.md"
    summary.write_text(render_summary(report, chart_files, tables), encoding="utf-8")
    data = out / "report.json"
    data.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return written + [summary, data]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path, help="run folders (default: discover under --runs-dir)")
    parser.add_argument("--runs-glob", action="append", default=[],
                        help="glob of run folders, e.g. 'runs/hcc_*_v3*' (repeatable)")
    parser.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs", help="where to discover runs")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="HCC run label (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="run seed (default: %(default)s)")
    parser.add_argument("--out", type=Path, default=Path("results"), help="output folder (default: %(default)s)")
    parser.add_argument("--models", nargs="*", default=EXPECTED_MODELS,
                        help="models expected in the study, for the missing-run list (default: %(default)s)")
    parser.add_argument("--no-charts", action="store_true", help="tables and JSON only")
    parser.add_argument("--no-titles", action="store_true",
                        help="draw charts without title/subtitle (for paper figures with captions)")
    parser.add_argument("--no-coverage", action="store_true", help="skip the covered/uncovered breakdown")
    args = parser.parse_args(argv)

    paths = list(args.runs)
    for pattern in args.runs_glob:
        paths += sorted(Path(p) for p in glob.glob(pattern) if Path(p).is_dir())
    if not paths:
        paths = discover_run_dirs(args.runs_dir, args.label, args.seed)
    if not paths:
        print(f"no runs found (looked under {args.runs_dir} for label {args.label!r})", file=sys.stderr)
        return 1

    classifier = None if args.no_coverage else default_classifier()
    report = build_report(paths, args.label, args.seed, classifier, expected_models=args.models)
    written = write_outputs(report, args.out, charts=not args.no_charts, titles=not args.no_titles)

    print(f"{len(report['runs'])} runs, {len(report['missing'])} missing, models: {', '.join(report['models'])}")
    for entry in report["missing"]:
        print(f"  missing: {entry['model']} {entry['config']} {entry['kind']} ({entry['expected_folder']})")
    for note in report["notes"]:
        print(f"  note: {note}")
    print(f"wrote {len(written)} files to {args.out}/ (see {args.out / 'summary.md'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
