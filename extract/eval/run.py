"""Score the cheap model against the gold-standard dataset.

Usage:
  python -m extract.eval.run --model gemini-2.5-flash-lite
  python -m extract.eval.run --model gemini-2.5-flash-lite --source kleinanzeigen
  python -m extract.eval.run --model gemini-2.5-flash-lite --ids 3284839151,3354036198
"""

import argparse
import concurrent.futures
import json
from typing import Any

from extract.eval.build import SOURCE_BY_NAME, data_dir
from extract.eval.compare import compute_agreement, diff_against_gold, effective_gold
from extract.eval.report import CaseResult, render
from extract.eval.runners import run_gemini
from lib.config import BASE_DIR, get_config
from lib.logger import get_logger
from lib.models import ListingSource

config = get_config()
logger = get_logger("eval.run")


def _load_snapshots(
    sources: list[ListingSource] | None, ids: list[str] | None
) -> list[dict[str, Any]]:
    base = data_dir()
    if not base.exists():
        return []

    source_dirs = (
        [base / s.value for s in sources] if sources else [d for d in base.iterdir() if d.is_dir()]
    )
    snapshots: list[dict[str, Any]] = []
    for sdir in source_dirs:
        if not sdir.exists():
            continue
        for path in sorted(sdir.glob("*.json")):
            if ids is not None and path.stem not in ids:
                continue
            with path.open("r", encoding="utf-8") as f:
                snapshots.append(json.load(f))
    return snapshots


def _score_one(snapshot: dict[str, Any], model_name: str) -> CaseResult:
    ai_input = snapshot["ai_input"]
    suburbs = snapshot.get("suburbs", [])
    models_output = snapshot["gold"]["models"]
    corrections = snapshot["gold"].get("corrections", {})

    agreed, disagreed = compute_agreement(models_output)
    gold_flat = effective_gold(agreed, corrections)
    skipped = {f: vals for f, vals in disagreed.items() if f not in corrections}

    cheap_output: dict[str, Any] | None = None
    error: str | None = None
    try:
        property_data = run_gemini(ai_input, suburbs, model_name)
        cheap_output = property_data.model_dump(mode="json")
    except Exception as e:
        error = repr(e)

    diffs = diff_against_gold(cheap_output, gold_flat) if cheap_output else []

    return CaseResult(
        source=snapshot["source"],
        external_id=snapshot["external_id"],
        cheap_output=cheap_output,
        error=error,
        effective_gold=gold_flat,
        skipped_fields=skipped,
        diffs=diffs,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="extract.eval.run")
    parser.add_argument(
        "--model",
        required=True,
        help="Cheap model to score (e.g. gemini-2.5-flash-lite)",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=list(SOURCE_BY_NAME.keys()),
        help="Filter to this source (repeatable). Default: all.",
    )
    parser.add_argument("--ids", help="Comma-separated external_ids to filter to")
    parser.add_argument("--workers", type=int, default=5, help="Parallel cheap-model calls")
    args = parser.parse_args()

    sources = [SOURCE_BY_NAME[s] for s in args.source] if args.source else None
    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None

    snapshots = _load_snapshots(sources, ids)
    if not snapshots:
        logger.info("No snapshots found in %s", data_dir())
        return

    logger.info(f"Scoring {len(snapshots)} cases with model={args.model}...")

    results: list[CaseResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_score_one, snap, args.model) for snap in snapshots]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: (r.source, r.external_id))
    print(render(results, args.model, data_dir().relative_to(BASE_DIR)))


if __name__ == "__main__":
    main()
