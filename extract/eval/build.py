"""Build the eval dataset.

Pulls raw_data rows (by --ids or --count from top-of-queue), runs both gold models
in parallel on each, writes one JSON snapshot per case to extract/eval/data/<source>/.
"""

import argparse
import concurrent.futures
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from extract.base import BaseExtractor
from extract.eval.runners import run_claude_gold, run_gemini_gold
from extract.immoscout import ImmoscoutExtractor
from extract.immowelt import ImmoweltExtractor
from extract.kleinanzeigen import KleinanzeigenExtractor
from lib.config import BASE_DIR, get_config
from lib.logger import get_logger
from lib.models import ListingSource, NextRawDataModel

config = get_config()
logger = get_logger("eval.build")


EXTRACTORS: dict[ListingSource, type[BaseExtractor]] = {
    ListingSource.KLEINANZEIGEN: KleinanzeigenExtractor,
    ListingSource.IMMOBILIENSCOUT24: ImmoscoutExtractor,
    ListingSource.IMMOWELT: ImmoweltExtractor,
}

SOURCE_BY_NAME = {s.value: s for s in ListingSource}


def data_dir() -> Path:
    return BASE_DIR / config.extract.eval.data_dir


def snapshot_path(source: ListingSource, external_id: str) -> Path:
    return data_dir() / source.value / f"{external_id}.json"


def _build_one(extractor: BaseExtractor, raw_data: NextRawDataModel) -> dict[str, Any]:
    soup = BeautifulSoup(raw_data.html, "lxml")
    json_data = raw_data.json

    address = extractor.get_address(soup, json_data)
    suburbs_dict = (
        extractor.db.get_suburbs_with_ids_by_zipcode(address.zipcode) if address.zipcode else {}
    )
    suburbs = list(suburbs_dict.keys())
    ai_input = extractor.get_ai_input(soup, json_data)

    gemini_model = config.extract.eval.gold_models.gemini
    claude_model = config.extract.eval.gold_models.claude

    models_output: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(run_gemini_gold, ai_input, suburbs, gemini_model): gemini_model,
            executor.submit(run_claude_gold, ai_input, suburbs, claude_model): claude_model,
        }
        for fut in concurrent.futures.as_completed(futures):
            model_name = futures[fut]
            try:
                property_data = fut.result()
                models_output[model_name] = property_data.model_dump(mode="json")
            except Exception as e:
                errors[model_name] = repr(e)
                logger.error(f"  {model_name} failed: {e}")

    return {
        "source": extractor.source.value,
        "external_id": raw_data.external_id,
        "built_at": datetime.now().isoformat(),
        "ai_input": ai_input,
        "suburbs": suburbs,
        "gold": {
            "models": models_output,
            "errors": errors,
            "corrections": {},
        },
    }


def _save(snapshot: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="extract.eval.build")
    parser.add_argument("--source", required=True, choices=list(SOURCE_BY_NAME.keys()))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ids", help="Comma-separated external_ids")
    group.add_argument("--count", type=int, help="Peek top-of-queue N rows")
    parser.add_argument("--rebuild", action="store_true", help="Overwrite existing snapshots")
    args = parser.parse_args()

    source = SOURCE_BY_NAME[args.source]
    extractor = EXTRACTORS[source]()
    db = extractor.db

    if args.ids:
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
        raw_data_list = db.get_raw_data_by_external_ids(source, ids)
    else:
        raw_data_list = db.get_next_raw_data_batch(source, args.count, claim=False)

    if not raw_data_list:
        logger.info("No raw data to build snapshots for.")
        return

    for raw_data in raw_data_list:
        path = snapshot_path(source, raw_data.external_id)
        if path.exists() and not args.rebuild:
            logger.info(f"  {raw_data.external_id}  exists, skipping (use --rebuild to overwrite)")
            continue
        logger.info(f"  {raw_data.external_id}  building snapshot...")
        try:
            snapshot = _build_one(extractor, raw_data)
            _save(snapshot, path)
            logger.info(f"  {raw_data.external_id}  saved -> {path.relative_to(BASE_DIR)}")
        except Exception as e:
            logger.error(f"  {raw_data.external_id}  build failed: {e}")


if __name__ == "__main__":
    main()
