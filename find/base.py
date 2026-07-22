import concurrent.futures
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from lib.logger import get_logger
from lib.fetch.fetcher import Fetcher
from lib.database import Database
from lib.config import get_config


class BaseFinder(ABC):
    # Default behavior: Process locations sequentially (safer for tough sites like Immoscout)
    CONCURRENT_LOCATIONS = False
    CONCURRENT_PAGES = True
    # A string only the fully-rendered page contains; the browser fetcher waits
    # for it so we don't capture the pre-hydration shell. None = no wait (curl).
    READY_MARKER: str | None = None
    # Results are newest-first, so once a page has zero new listings the deeper
    # pages are all already known. When True, paginate sequentially and stop
    # there (Immoscout: 453 pages/category at ~30s each is otherwise hours).
    STOP_WHEN_NO_NEW: bool = False
    # Hard safety cap on pages per location, whatever STOP_WHEN_NO_NEW decides.
    MAX_PAGES: int | None = None

    def __init__(self, method: str, proxy_url: str | None):
        self.config = get_config()
        self.logger = get_logger(self.__class__.__name__)
        self.db = Database()
        self.fetcher = Fetcher(method=method, proxy_url=proxy_url)
        # get worker based on method and config 
        # get max_workers based on method and config
        method_config = getattr(self.config, method)
        self.max_workers = method_config.max_workers
        
    def fetch_html(self, url: str) -> str:
        return self.fetcher.fetch(url, ready_marker=self.READY_MARKER)

    def run(self):
        """
        Main strategy:
        1. Iterate Categories
        2. Iterate Locations (Concurrently OR Sequentially based on flag)
        3. Iterate Pages (Concurrent by default for speed)
        """
        for category_name, category in self.get_categories():
            locations = self.get_locations()
            
            # Limit for testing
            # locations = locations[:3] 
            # locations = ["16315"]

            self.logger.info(
                f"Starting crawl for {category_name} with {len(locations)} locations. "
                f"Concurrency for locations: {'ON' if self.CONCURRENT_LOCATIONS else 'OFF'}. "
                f"Concurrency for pages: {'ON' if self.CONCURRENT_PAGES else 'OFF'}."
            )

            if self.CONCURRENT_LOCATIONS:
                # Parallel processing for sites that allow it (e.g. Kleinanzeigen)
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = [
                        executor.submit(self.process_location, category, location)
                        for location in locations
                    ]
                    concurrent.futures.wait(futures)
            else:
                # Sequential processing for sensitive sites (e.g. Immoscout or Immowelt)
                for location in locations:
                    self.process_location(category, location)

    def process_location(self, category, location):
        """Strategy for a single location."""
        # 1. Process Page 1 and get total page count + how many were new
        pages_count, new_count = self.process_page_strategy(category, location, page=1)

        last_page = pages_count
        if self.MAX_PAGES:
            last_page = min(last_page, self.MAX_PAGES)
        if last_page <= 1:
            return

        # 2a. Early-stop mode: walk pages in order, stop when one has no new
        # listings (deeper pages are older, so all already known). A failed page
        # (new_count is None) doesn't count as "no new" — keep going.
        if self.STOP_WHEN_NO_NEW:
            if new_count == 0:
                return
            for page in range(2, last_page + 1):
                _, new_count = self.process_page_strategy(category, location, page)
                if new_count == 0:
                    self.logger.info(f"Early stop at page {page} for {location}: no new listings.")
                    break
            return

        # 2b. Default: process the remaining pages concurrently
        if self.CONCURRENT_PAGES:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(self.process_page_strategy, category, location, page)
                    for page in range(2, last_page + 1)
                ]
                concurrent.futures.wait(futures)

    def process_page_strategy(self, category, location, page) -> tuple[int, int | None]:
        """
        Builds URL, fetches HTML, parses listings, saves to DB.
        Returns (total pages count, number of NEW listings on this page).
        new_count is None when the page failed — so early-stop won't mistake a
        failed fetch for "no new listings".
        """
        url = self.build_url(category, location, page)

        try:
            # use the fetcher class to get the HTML.
            html = self.fetcher.fetch(url, ready_marker=self.READY_MARKER)
            soup = BeautifulSoup(html, "lxml")

            # Get listings and save
            listings = self.get_listings(soup)
            # This is also saving "alternative" listings. To avoide this dont save them if pages_count is 1
            new_count = 0
            if listings:
                new_count = self.db.set_new_listing_data(listings)

            # Get page count
            pages_count = self.get_pages_count(soup)

            self.logger.info(
                f"Listings: {len(listings):<3} (new: {new_count}) \tPage: {page} of {pages_count}"
                # f"\tCategory {category} \tLocation {location}"
                f"\tURL {url}"
            )
            return pages_count, new_count

        except Exception as e:
            self.logger.error(f"Failed page {page} for {location} (URL: {url}): {e}")
            return 0, None

    # --- Abstract Methods ---

    @abstractmethod
    def get_categories(self) -> list[tuple]:
        pass

    @abstractmethod
    def get_locations(self) -> list[str]:
        pass

    @abstractmethod
    def build_url(self, category: str, location: str, page: int) -> str:
        pass

    @abstractmethod
    def get_listings(self, soup: BeautifulSoup) -> list:
        pass

    @abstractmethod
    def get_pages_count(self, soup: BeautifulSoup) -> int:
        pass