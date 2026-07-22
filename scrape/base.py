import concurrent.futures
from abc import ABC, abstractmethod
from typing import Any

from bs4 import BeautifulSoup

from lib.config import get_config
from lib.database import Database
from lib.exceptions import InactiveListingError
from lib.fetch.fetcher import Fetcher
from lib.logger import get_logger
from lib.models import ListingSource, NextListingModel


class BaseScraper(ABC):
    # Default behavior: process listings concurrently (curl_cffi supports parallelism)
    CONCURRENT_LISTINGS = True
    # When True: only re-scrape if modified_at > last_scraped_at (Immowelt, Immoscout)
    # When False: re-scrape any listing older than 12h (Kleinanzeigen — no modified_at updates)
    RESCRAPE_ON_MODIFIED_ONLY = False
    # A string only the fully-rendered page contains; the browser fetcher waits
    # for it so we don't capture the pre-hydration shell. None = no wait (curl).
    READY_MARKER: str | None = None

    def __init__(self, source: ListingSource, method: str, proxy_url: str | None):
        self.source = source
        self.config = get_config()
        self.logger = get_logger(self.__class__.__name__)
        self.db = Database()
        self.fetcher = Fetcher(method=method, proxy_url=proxy_url)
        method_config = getattr(self.config, method)
        self.max_workers = method_config.max_workers

    def run(self):
        """
        Main strategy:
        1. Fetch a batch of unscraped listings from the DB
        2. Process each listing (Concurrently OR Sequentially based on flag)
        3. Repeat until no listings remain or interrupted with Ctrl+C
        """
        scrape_config = getattr(self.config.scrape, self.source.value)
        batch_size = scrape_config.batch_size
        total_scraped = 0

        try:
            while True:
                listings = self.db.get_next_listings(
                    self.source, batch_size, rescrape_on_modified_only=self.RESCRAPE_ON_MODIFIED_ONLY
                )

                if not listings:
                    self.logger.info(f"No more listings to scrape. Total processed: {total_scraped}")
                    break

                self.logger.info(
                    f"Starting batch of {len(listings)} listings. "
                    f"Concurrency: {'ON' if self.CONCURRENT_LISTINGS else 'OFF'}."
                )

                if self.CONCURRENT_LISTINGS:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        futures = [
                            executor.submit(self.process_listing, listing)
                            for listing in listings
                        ]
                        concurrent.futures.wait(futures)
                else:
                    for listing in listings:
                        self.process_listing(listing)

                total_scraped += len(listings)

        except KeyboardInterrupt:
            self.logger.info(f"Interrupted. Total processed: {total_scraped}")

    def process_listing(self, listing: NextListingModel):
        """Fetch, extract, and save data for a single listing."""
        url = self.build_url(listing.external_id)
        prefix = f"{listing.id}  {url}"
        try:
            html = self.fetcher.fetch(url, ready_marker=self.READY_MARKER)
            soup = BeautifulSoup(html, "lxml")

            minified_html = self.get_minified_html(soup)
            json_data = self.get_json_data(soup)
            image_urls = self.get_image_urls(soup, json_data)
            main_image_url = self.get_main_image_url(soup, json_data)
            extra_data = self.get_extra_data(soup, json_data)

            self.db.set_raw_data(listing.id, minified_html, json_data)
            self.db.set_image_urls(listing.id, image_urls)
            if main_image_url:
                self.db.set_main_image_url(listing.id, main_image_url)
            if extra_data:
                self.db.update_extra_data(listing.id, extra_data)
            self.db.set_last_scraped(listing.id)

            self.logger.info(f"{prefix}  Scraped successfully")

        except InactiveListingError:
            if listing.last_scraped_at is None:
                self.logger.info(f"{prefix}  Never scraped, deleting (inactive listing)")
                self.db.delete_listing(listing.id)
            else:
                self.logger.info(f"{prefix}  Deactivating (inactive listing)")
                self.db.deactivate_listing(listing.id)

        except Exception as e:
            if self.is_deactivated_listing(e, listing):
                if listing.last_scraped_at is None:
                    self.logger.info(f"{prefix}  Never scraped, deleting: {e}")
                    self.db.delete_listing(listing.id)
                else:
                    self.logger.info(f"{prefix}  Deactivating: {e}")
                    self.db.deactivate_listing(listing.id)
            else:
                self.logger.error(f"{prefix}  Failed to scrape: {e}")

    # --- Abstract Methods ---

    @abstractmethod
    def build_url(self, external_id: str) -> str:
        pass

    @abstractmethod
    def get_minified_html(self, soup: BeautifulSoup) -> str:
        pass

    @abstractmethod
    def get_json_data(self, soup: BeautifulSoup) -> dict[str, Any]:
        pass

    @abstractmethod
    def get_image_urls(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> list[str]:
        pass

    @abstractmethod
    def get_main_image_url(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str | None:
        pass

    # --- Optional Overrides ---

    def get_extra_data(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """
        Extracts extra data to be persisted.
        Returns a dict with table names as keys and column dicts as values.
        """
        return {}

    def is_deactivated_listing(self, exception: Exception, listing: NextListingModel) -> bool:
        """
        Returns True if the exception indicates the listing has been deactivated/removed.
        Override in subclasses to implement platform-specific detection.
        """
        return False