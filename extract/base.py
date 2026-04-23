import concurrent.futures
from abc import ABC, abstractmethod
from pprint import pprint
from typing import Any

from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process

from lib.ai import parse_property_with_ai
from lib.config import get_config
from lib.database import Database, UpsertItem
from lib.logger import get_logger
from lib.models import Address, Description, ListingSource, NextRawDataModel


class BaseExtractor(ABC):
    # AI calls are I/O bound - parallel is fine and significantly faster
    CONCURRENT_LISTINGS = True

    def __init__(self, source: ListingSource):
        self.source = source
        self.config = get_config()
        self.logger = get_logger(self.__class__.__name__)
        self.db = Database()

    def run(self, max_batches: int | None = None):
        """
        1. Claim a batch of unextracted raw_data rows from DB
        2. Process each (concurrently or sequentially based on flag)
        3. Repeat until no rows remain (or until `max_batches` reached, for testing)
        """
        extract_config = getattr(self.config.extract, self.source.value)
        batch_size = extract_config.batch_size
        max_workers = extract_config.max_workers
        total_extracted = 0
        batches_done = 0

        try:
            while True:
                raw_data_list = self.db.get_next_raw_data_batch(self.source, batch_size)

                if not raw_data_list:
                    self.logger.info(f"No more raw data to extract. Total processed: {total_extracted}")
                    break

                self.logger.info(
                    f"Starting batch of {len(raw_data_list)} rows. "
                    f"Concurrency: {'ON' if self.CONCURRENT_LISTINGS else 'OFF'}."
                )

                if self.CONCURRENT_LISTINGS:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [executor.submit(self.process_raw_data, raw_data) for raw_data in raw_data_list]
                        concurrent.futures.wait(futures)
                else:
                    for raw_data in raw_data_list:
                        self.process_raw_data(raw_data)

                total_extracted += len(raw_data_list)
                batches_done += 1

                if max_batches is not None and batches_done >= max_batches:
                    self.logger.info(f"Reached max_batches={max_batches}. Total processed: {total_extracted}")
                    break

        except KeyboardInterrupt:
            self.logger.info(f"Interrupted. Total processed: {total_extracted}")

    def process_raw_data(self, raw_data: NextRawDataModel):
        prefix = f"{raw_data.id}  {raw_data.external_id}"
        try:
            description, address, property_data = self.extract(raw_data)

            items: list[UpsertItem] = [
                UpsertItem(model=description, uuid=raw_data.id, table="descriptions"),
                UpsertItem(model=property_data.building, uuid=raw_data.id, table="building"),
                UpsertItem(model=property_data.general, uuid=raw_data.id, table="general"),
                UpsertItem(model=property_data.features, uuid=raw_data.id, table="features"),
                UpsertItem(model=property_data.heating, uuid=raw_data.id, table="heating"),
                UpsertItem(
                    model=property_data.financial,
                    uuid=raw_data.id,
                    table="financial",
                    exclude={"buyer_commission_amount"},
                ),
                UpsertItem(
                    model=property_data.contact,
                    uuid=raw_data.id,
                    table="contact",
                    conflict=["property_id", "first_name", "last_name"],
                ),
            ]

            self.db.batch_upsert(items)
            self.db.set_address(raw_data.id, address)
            self.db.set_last_extracted(raw_data.id)

            self.logger.info(f"{prefix}  Extracted successfully")

        except Exception as e:
            self.logger.error(f"{prefix}  Failed to extract: {e}")

    def extract(self, raw_data: NextRawDataModel, on_ai_input=None):
        """Run the full extraction pipeline (parse + AI + matching). Returns the
        extracted data without touching the DB. Used by both production
        (`process_raw_data`) and test mode. `on_ai_input` is an optional callback
        invoked with the assembled AI input string before the AI call."""
        soup = BeautifulSoup(raw_data.html, "lxml")
        json_data = raw_data.json

        description = self.get_description(soup, json_data)
        address = self.get_address(soup, json_data)

        suburbs = self.db.get_suburbs_with_ids_by_zipcode(address.zipcode) if address.zipcode else {}

        ai_input = self.get_ai_input(soup, json_data)
        if on_ai_input is not None:
            on_ai_input(ai_input)
        property_data = parse_property_with_ai(ai_input, list(suburbs.keys()))
        property_data.financial.price = self.get_price(soup, json_data)
        property_data.financial.buyer_commission = property_data.get_buyer_commission()
        property_data.financial.price_per_sqm = property_data.get_price_per_sqm()
        property_data.general.title = self.get_title(soup, json_data)

        if address.zipcode:
            if address.street:
                street_names = self.db.get_street_names_by_zipcode(address.zipcode)
                if street_names:
                    match = self._get_best_match(address.street, street_names)
                    if match:
                        address.street = match

            if property_data.location.suburb:
                suburb = self._get_best_match(property_data.location.suburb, list(suburbs.keys()))
                address.suburb = suburb
                address.place_ids = suburbs.get(suburb) if suburb else None

        return description, address, property_data

    def test_run(self, ids: list[str] | None = None, limit: int = 1) -> None:
        """Test mode: print AI input + extracted data, never touch the DB.

        - If `ids` is given (list of external_ids), fetch exactly those rows for
          this extractor's source.
        - Otherwise pull `limit` rows WITHOUT claiming, deterministically picking
          the same top-priority row(s) each time so you can iterate on the AI
          prompt against a stable input.
        """
        if ids:
            raw_data_list = self.db.get_raw_data_by_external_ids(self.source, ids)
        else:
            raw_data_list = self.db.get_next_raw_data_batch(self.source, limit, claim=False)
        if not raw_data_list:
            self.logger.info("No raw data available for test extraction.")
            return

        for raw_data in raw_data_list:
            prefix = f"{raw_data.id}  {raw_data.external_id}"
            print("=" * 100)
            print(f"TEST EXTRACTION  {prefix}")
            print("=" * 100)

            def _print_ai_input(text: str) -> None:
                print("-" * 100)
                print("AI INPUT")
                print("-" * 100)
                print(text)

            try:
                description, address, property_data = self.extract(raw_data, on_ai_input=_print_ai_input)
            except Exception as e:
                self.logger.error(f"{prefix}  Failed to extract: {e}")
                continue

            print("-" * 100)
            print("EXTRACTED RESULT")
            print("-" * 100)
            pprint(
                {
                    "id": str(raw_data.id),
                    "external_id": raw_data.external_id,
                    "description": description.model_dump(),
                    "address": address.__dict__,
                    **property_data.model_dump(),
                },
                sort_dicts=False,
                width=100,
            )

    def _get_best_match(self, input: str, choices: list[str]) -> str | None:
        if not input or not choices:
            return None

        if input in choices:
            return input

        result = process.extractOne(
            input,
            choices,
            scorer=fuzz.WRatio,
            score_cutoff=self.config.extract.match_score_cutoff,
        )
        if result is None:
            return None

        match, _score, _index = result
        return match

    # --- Abstract Methods ---

    @abstractmethod
    def get_title(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        pass

    @abstractmethod
    def get_price(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> float | None:
        pass

    @abstractmethod
    def get_address(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> Address:
        pass

    @abstractmethod
    def get_description(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> Description:
        pass

    @abstractmethod
    def get_ai_input(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        pass
