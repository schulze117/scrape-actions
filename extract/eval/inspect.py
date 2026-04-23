"""Inspect snapshots: show where the gold models disagree.

Usage:
  python -m extract.eval.inspect                                  # all sources
  python -m extract.eval.inspect --source kleinanzeigen           # one source
  python -m extract.eval.inspect --ids 3374382798,3386520939      # specific cases
  python -m extract.eval.inspect --field-summary                  # only the per-field totals
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from extract.eval.build import SOURCE_BY_NAME, data_dir
from extract.eval.compare import compute_agreement
from lib.config import BASE_DIR
from lib.logger import get_logger
from lib.models import ListingSource

logger = get_logger("eval.inspect")


def _load(sources: list[ListingSource] | None, ids: list[str] | None) -> list[tuple[Path, dict[str, Any]]]:
    base = data_dir()
    if not base.exists():
        return []
    source_dirs = (
        [base / s.value for s in sources] if sources else [d for d in base.iterdir() if d.is_dir()]
    )
    out: list[tuple[Path, dict[str, Any]]] = []
    for sdir in source_dirs:
        if not sdir.exists():
            continue
        for path in sorted(sdir.glob("*.json")):
            if ids is not None and path.stem not in ids:
                continue
            out.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="extract.eval.inspect")
    parser.add_argument(
        "--source",
        action="append",
        choices=list(SOURCE_BY_NAME.keys()),
        help="Filter to this source (repeatable). Default: all.",
    )
    parser.add_argument("--ids", help="Comma-separated external_ids to filter to")
    parser.add_argument(
        "--field-summary",
        action="store_true",
        help="Only print the per-field disagreement totals (no per-case detail).",
    )
    args = parser.parse_args()

    sources = [SOURCE_BY_NAME[s] for s in args.source] if args.source else None
    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None

    snapshots = _load(sources, ids)
    if not snapshots:
        logger.info("No snapshots found in %s", data_dir())
        return

    field_to_cases: dict[str, list[str]] = defaultdict(list)
    total_agree = total_disagree = 0
    cases_missing_a_model: list[tuple[str, str, list[str]]] = []
    per_case_diffs: list[tuple[str, str, dict[str, dict[str, Any]], dict[str, str]]] = []

    for path, snap in snapshots:
        models = snap["gold"]["models"]
        errors = snap["gold"].get("errors", {})
        corrections = snap["gold"].get("corrections", {})
        source = snap["source"]
        ext_id = snap["external_id"]
        if len(models) < 2:
            cases_missing_a_model.append((source, ext_id, list(models.keys())))
            continue
        agreed, disagreed = compute_agreement(models)
        total_agree += len(agreed)
        total_disagree += len(disagreed)
        for fname in disagreed:
            field_to_cases[fname].append(ext_id)
        if disagreed:
            per_case_diffs.append((source, ext_id, disagreed, corrections))

    print(f"\nDataset: {data_dir().relative_to(BASE_DIR)}")
    print(f"Snapshots scanned: {len(snapshots)}  (with both gold models: {len(snapshots) - len(cases_missing_a_model)})")
    print(f"Field outcomes:    agree={total_agree}  disagree={total_disagree}")
    if cases_missing_a_model:
        print("\nCASES MISSING A GOLD MODEL (rebuild these):")
        for src, eid, present in cases_missing_a_model:
            print(f"  {eid} ({src})  present_models={present}")

    if field_to_cases:
        print("\nFIELDS WHERE GOLD MODELS DISAGREE:")
        for fname, cases in sorted(field_to_cases.items(), key=lambda x: -len(x[1])):
            print(f"  {fname:<42} {len(cases):>3} cases  {cases}")

    if not args.field_summary and per_case_diffs:
        print("\nPER-CASE DISAGREEMENTS (add to gold.corrections to score):")
        for src, eid, disagreed, corrections in per_case_diffs:
            print(f"\n--- {eid} ({src}) ---")
            for fname, vals in disagreed.items():
                marker = "  [corrected]" if fname in corrections else ""
                print(f"  {fname}{marker}")
                for mname, v in vals.items():
                    print(f"    {mname:<26} = {v!r}")


if __name__ == "__main__":
    main()
