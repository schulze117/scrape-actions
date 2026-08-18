import concurrent.futures
import sys
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from lib.logger import get_logger
from lib.fetch.fetcher import Fetcher
from lib.database import Database
from lib.config import get_config
from lib.exceptions import FinderFailedError


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
    # How many *consecutive* pages must yield zero new listings before stopping.
    # >1 guards against a single page that happens to be all-known (promoted /
    # sponsored listings are pinned to page 1, so it can look empty while the
    # pages behind it are full of new ones).
    NO_NEW_PAGES_TO_STOP: int = 3
    # Hard safety cap on pages per location, whatever STOP_WHEN_NO_NEW decides.
    MAX_PAGES: int | None = None
    # Page 1 decides the fate of the whole category — it is the only page that
    # yields the page count, so losing it discards every page behind it. One
    # blocked fetch must not cost a category, so it gets its own retries.
    PAGE_ONE_ATTEMPTS: int = 3

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

        Raises FinderFailedError if any (category, location) lost page 1, which
        means its whole result set was silently skipped. Losing page 1 used to
        end the category with a clean exit code, so a total outage looked
        identical to a quiet day — see the immoscout blackout of 2026-08-16.
        """
        lost: list[str] = []
        total_new = 0

        for category_name, category in self.get_categories():
            locations = self.get_locations()

            self.logger.info(
                f"Starting crawl for {category_name} with {len(locations)} locations. "
                f"Concurrency for locations: {'ON' if self.CONCURRENT_LOCATIONS else 'OFF'}. "
                f"Concurrency for pages: {'ON' if self.CONCURRENT_PAGES else 'OFF'}."
            )

            if self.CONCURRENT_LOCATIONS:
                # Parallel processing for sites that allow it (e.g. Kleinanzeigen)
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {
                        executor.submit(self.process_location, category, location): location
                        for location in locations
                    }
                    for future in concurrent.futures.as_completed(futures):
                        page_one_ok, new_count = future.result()
                        total_new += new_count
                        if not page_one_ok:
                            lost.append(f"{category_name}/{futures[future]}")
            else:
                # Sequential processing for sensitive sites (e.g. Immoscout or Immowelt)
                for location in locations:
                    page_one_ok, new_count = self.process_location(category, location)
                    total_new += new_count
                    if not page_one_ok:
                        lost.append(f"{category_name}/{location}")

        self.logger.info(f"Crawl finished: {total_new} new listings, {len(lost)} lost page 1.")
        if lost:
            raise FinderFailedError(lost, total_new)

    def process_location(self, category, location) -> tuple[bool, int]:
        """Strategy for a single location.

        Returns (page 1 succeeded, new listings saved for this location).
        """
        # 1. Process Page 1 and get total page count + how many were new. Page 1
        # is retried on its own: it carries the page count, so a single blocked
        # fetch would otherwise discard every page behind it.
        for attempt in range(1, self.PAGE_ONE_ATTEMPTS + 1):
            pages_count, new_count = self.process_page_strategy(category, location, page=1)
            if new_count is not None:
                break
            if attempt < self.PAGE_ONE_ATTEMPTS:
                self.logger.warning(
                    f"Page 1 failed for {location} "
                    f"(attempt {attempt}/{self.PAGE_ONE_ATTEMPTS}); retrying."
                )
        else:
            self.logger.error(
                f"Page 1 failed for {location} after {self.PAGE_ONE_ATTEMPTS} attempts — "
                f"skipping the whole category, no listings collected."
            )
            return False, 0

        location_new = new_count

        last_page = pages_count
        if self.MAX_PAGES:
            last_page = min(last_page, self.MAX_PAGES)
        if last_page <= 1:
            return True, location_new

        # 2a. Early-stop mode: walk pages in order, stop once NO_NEW_PAGES_TO_STOP
        # consecutive pages have no new listings (deeper pages are older, so all
        # already known). A single new listing resets the streak. A failed page
        # (new_count is None) is neutral — it neither confirms nor breaks the
        # streak, so a fetch error can't be mistaken for "no new listings".
        if self.STOP_WHEN_NO_NEW:
            empty_streak = 1 if new_count == 0 else 0
            if empty_streak >= self.NO_NEW_PAGES_TO_STOP:
                return True, location_new
            for page in range(2, last_page + 1):
                _, new_count = self.process_page_strategy(category, location, page)
                if new_count is None:
                    continue
                location_new += new_count
                empty_streak = empty_streak + 1 if new_count == 0 else 0
                if empty_streak >= self.NO_NEW_PAGES_TO_STOP:
                    self.logger.info(
                        f"Early stop at page {page} for {location}: "
                        f"{empty_streak} consecutive pages with no new listings."
                    )
                    break
            return True, location_new

        # 2b. Default: process the remaining pages concurrently
        if self.CONCURRENT_PAGES:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(self.process_page_strategy, category, location, page)
                    for page in range(2, last_page + 1)
                ]
                for future in concurrent.futures.as_completed(futures):
                    _, new_count = future.result()
                    location_new += new_count or 0

        return True, location_new

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


def run_finder(finder_cls: type[BaseFinder]) -> None:
    """Entry point for every `python -m find.<platform>` module.

    Exists so a crawl that collected nothing turns the workflow run RED. The
    finders used to swallow every per-page error and return normally, so a
    totally blocked run exited 0 and looked identical to a quiet day — the
    immoscout blackout of August 2026 ran green for two days.
    """
    finder = finder_cls()
    try:
        finder.run()
    except FinderFailedError as exc:
        finder.logger.error(str(exc))
        sys.exit(1)