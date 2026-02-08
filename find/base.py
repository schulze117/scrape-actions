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
        return self.fetcher.fetch(url)

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
        # 1. Process Page 1 and get total page count
        pages_count = self.process_page_strategy(category, location, page=1)
        
        # 2. If more pages, process them concurrently
        if pages_count > 1 and self.CONCURRENT_PAGES:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(self.process_page_strategy, category, location, page)
                    for page in range(2, pages_count + 1)
                ]
                concurrent.futures.wait(futures)

    def process_page_strategy(self, category, location, page) -> int:
        """
        Builds URL, fetches HTML, parses listings, saves to DB.
        Returns total pages count.
        """
        url = self.build_url(category, location, page)
        
        try:
            # use the fetcher class to get the HTML.
            html = self.fetcher.fetch(url)
            soup = BeautifulSoup(html, "lxml")
            
            # Get listings and save
            listings = self.get_listings(soup)
            # This is also saving "alternative" listings. To avoide this dont save them if pages_count is 1
            if listings:
                self.db.set_new_listing_data(listings)
            
            # Get page count
            pages_count = self.get_pages_count(soup)
            
            self.logger.info(
                f"Listings: {len(listings):<3} \tPage: {page} of {pages_count}"
                # f"\tCategory {category} \tLocation {location}"
                f"\tURL {url}"
            )
            return pages_count

        except Exception as e:
            self.logger.error(f"Failed page {page} for {location} (URL: {url}): {e}")
            return 0

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