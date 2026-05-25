#!/usr/bin/env python3
"""Run the Anatou daily diagnosis pipeline without touching backend code.

Supported flows:
1. Existing wide_rebirth JSONL -> race diagnosis -> daily preview
2. Race payload JSON -> backend API replay -> race diagnosis -> daily preview
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"
SCRIPTS_DIR = PROJECT_DIR / "scripts"


def run_cmd(cmd: list[str]) -> None:
    print("[run] " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)


def normalize_date(value: str) -> str:
    if not value:
        return datetime.now().strftime("%Y%m%d")
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text.replace("-", "")
    return text


def build_wide_from_race_json(args: argparse.Namespace, race_json: Path, suffix: str) -> Path:
    out_path = DATA_DIR / f"anatou_today_wide_{race_json.stem}_{suffix}.jsonl"
    report_path = DOCS_DIR / f"anatou_today_wide_{race_json.stem}_{suffix}.md"
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "build_wide_rebirth_dataset_from_api.py"),
        "--input",
        str(race_json),
        "--existing-dataset",
        args.existing_dataset,
        "--out",
        str(out_path),
        "--report",
        str(report_path),
        "--api-url",
        args.api_url,
        "--min-engines",
        str(args.min_engines),
        "--allow-missing-wide",
        "--timeout",
        str(args.timeout),
        "--retries",
        str(args.retries),
    ]
    if args.limit:
        cmd.extend(["--limit", str(args.limit)])
    if args.sleep:
        cmd.extend(["--sleep", str(args.sleep)])
    run_cmd(cmd)
    return out_path


def build_race_json_from_prefetch(args: argparse.Namespace, prefetch_json: Path, suffix: str) -> Path:
    out_path = DATA_DIR / f"anatou_races_{args.prefetch_race_type}_{prefetch_json.stem}_{suffix}.json"
    report_path = DOCS_DIR / f"anatou_prefetch_to_race_json_{args.prefetch_race_type}_{prefetch_json.stem}_{suffix}.md"
    run_cmd([
        sys.executable,
        str(SCRIPTS_DIR / "anatou_prefetch_to_race_json.py"),
        "--input",
        str(prefetch_json),
        "--race-type",
        args.prefetch_race_type,
        "--out",
        str(out_path),
        "--report",
        str(report_path),
    ])
    return out_path


def build_diagnosis(wide_path: Path, suffix: str) -> Path:
    out_path = DATA_DIR / f"anatou_today_diagnosis_{wide_path.stem}_{suffix}.jsonl"
    report_path = DOCS_DIR / f"anatou_today_diagnosis_build_{wide_path.stem}_{suffix}.md"
    run_cmd([
        sys.executable,
        str(SCRIPTS_DIR / "anatou_race_diagnosis.py"),
        "--profile",
        "v2",
        "--input",
        str(wide_path),
        "--out",
        str(out_path),
        "--report",
        str(report_path),
    ])
    return out_path


def build_preview(args: argparse.Namespace, diagnosis_paths: list[Path], suffix: str) -> tuple[Path, Path]:
    if args.forward_log:
        md_path = Path(args.out_md) if args.out_md else DOCS_DIR / "anatou_forward" / suffix / "preview.md"
        json_path = Path(args.out_json) if args.out_json else DATA_DIR / "anatou_forward" / suffix / "preview.json"
    else:
        md_path = Path(args.out_md) if args.out_md else DOCS_DIR / f"anatou_today_diagnosis_preview_{suffix}.md"
        json_path = Path(args.out_json) if args.out_json else DATA_DIR / f"anatou_today_diagnosis_preview_{suffix}.json"
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "anatou_today_diagnosis.py"),
        "--limit",
        str(args.preview_limit),
        "--out-md",
        str(md_path),
        "--out-json",
        str(json_path),
    ]
    if args.date:
        cmd.extend(["--date", args.date])
    for path in diagnosis_paths:
        cmd.extend(["--input", str(path)])
    run_cmd(cmd)
    return md_path, json_path


def write_forward_log(
    args: argparse.Namespace,
    suffix: str,
    wide_paths: list[Path],
    diagnosis_paths: list[Path],
    preview_md: Path,
    preview_json: Path,
) -> None:
    data_dir = DATA_DIR / "anatou_forward" / suffix
    docs_dir = DOCS_DIR / "anatou_forward" / suffix
    data_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    archived_diagnosis = []
    for idx, path in enumerate(diagnosis_paths, start=1):
        archived = data_dir / f"diagnosis_{idx}.jsonl"
        shutil.copy2(path, archived)
        archived_diagnosis.append(str(archived))

    manifest = {
        "schema_version": "anatou_forward_log.v1",
        "date": suffix,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "wide_jsonl" if args.wide_jsonl and not args.race_json else "race_json_or_mixed",
        "source_wide_jsonl": [str(path) for path in wide_paths],
        "source_race_json": [str(path) for path in args.race_json],
        "diagnosis_original": [str(path) for path in diagnosis_paths],
        "diagnosis_archived": archived_diagnosis,
        "preview_md": str(preview_md),
        "preview_json": str(preview_json),
        "result_check_md": str(docs_dir / "result_check.md"),
        "notes": [
            "This is a forward validation log, not a purchase recommendation.",
            "User-facing skip should be read as low priority.",
            "AI low-rated popular is not a confirmed elimination signal.",
        ],
    }

    manifest_json = data_dir / "manifest.json"
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_md = docs_dir / "manifest.md"
    lines = [
        f"# 穴党参謀AI フォワードログ {suffix}",
        "",
        "## Files",
        "",
        f"- preview_md: `{preview_md}`",
        f"- preview_json: `{preview_json}`",
        f"- manifest_json: `{manifest_json}`",
        f"- result_check_md: `{docs_dir / 'result_check.md'}`",
        "",
        "## Diagnosis",
        "",
        *[f"- `{path}`" for path in archived_diagnosis],
        "",
        "## Notes",
        "",
        "- これは購入推奨ではなく、診断AIのフォワード検証ログ。",
        "- `skip` はユーザー表示では低優先度として扱う。",
        "- `AI低評価人気` は消しではなく過信注意として扱う。",
        "",
    ]
    manifest_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[forward_manifest_json] {manifest_json}")
    print(f"[forward_manifest_md] {manifest_md}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Anatou daily diagnosis pipeline")
    parser.add_argument("--date", default="", help="target date YYYYMMDD or YYYY-MM-DD. Defaults to today")
    parser.add_argument("--wide-jsonl", action="append", default=[], help="existing wide_rebirth JSONL input")
    parser.add_argument("--race-json", action="append", default=[], help="race payload JSON for API replay")
    parser.add_argument("--prefetch-json", action="append", default=[], help="prefetch_races.py output JSON")
    parser.add_argument("--prefetch-race-type", choices=("jra", "nar", "both"), default="both")
    parser.add_argument("--api-url", default="http://localhost:8011")
    parser.add_argument("--existing-dataset", default=str(DATA_DIR / "wide_rebirth_dataset_20260301_20260525_existing.jsonl"))
    parser.add_argument("--min-engines", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0, help="limit race-json replay count")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--preview-limit", type=int, default=8)
    parser.add_argument("--out-md", default="")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--forward-log", action="store_true", help="write preview and manifest under data/docs anatou_forward/YYYYMMDD")
    args = parser.parse_args()

    if not args.wide_jsonl and not args.race_json and not args.prefetch_json:
        parser.error("provide at least one --wide-jsonl, --race-json, or --prefetch-json")

    suffix = normalize_date(args.date)
    race_json_paths = [Path(path) for path in args.race_json]
    for prefetch_json in args.prefetch_json:
        race_json_paths.append(build_race_json_from_prefetch(args, Path(prefetch_json), suffix))

    wide_paths = [Path(path) for path in args.wide_jsonl]
    for race_json in race_json_paths:
        wide_paths.append(build_wide_from_race_json(args, race_json, suffix))

    diagnosis_paths = [build_diagnosis(path, suffix) for path in wide_paths]
    md_path, json_path = build_preview(args, diagnosis_paths, suffix)
    if args.forward_log:
        write_forward_log(args, suffix, wide_paths, diagnosis_paths, md_path, json_path)
    print("")
    print("[done] Anatou daily diagnosis pipeline")
    print(f"[preview_md] {md_path}")
    print(f"[preview_json] {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
