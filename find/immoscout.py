import json
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup, Tag
from lib.config import get_config, get_env
from lib.models import IMMOSCOUT_SEARCH_CATEGORIES, ListingSource, NewListing
from lib.exceptions import ElementNotFoundError, NotBeautifulSoupError
from .base import BaseFinder

config = get_config()

def extract_listing_data(listing: dict[str, Any]) -> NewListing:
    modified_at = listing.get("@modification")
    created_at = listing.get("@creation")

    if not modified_at:
        raise ValueError(f"@modification not found in listing data: {listing}")
    if not created_at:
        raise ValueError(f"@creation not found in listing data: {listing}")

    return NewListing(
        external_id=listing["@id"],
        created_at=datetime.fromisoformat(created_at),
        modified_at=datetime.fromisoformat(modified_at),
        source=ListingSource.IMMOBILIENSCOUT24,
    )

class ImmoscoutFinder(BaseFinder):
    CONCURRENT_LOCATIONS = False
    BASE_URL = "https://www.immobilienscout24.de/Suche/shape"

    def __init__(self):
        method = config.find.immoscout.method
        use_proxy = config.find.immoscout.use_proxy
        proxy_url = getattr(get_env(), "PROXY_URL__IMMOSCOUT", None) if use_proxy else None
        super().__init__(method=method, proxy_url=proxy_url)

    def get_categories(self):
        return IMMOSCOUT_SEARCH_CATEGORIES.items()

    def get_locations(self):
        return self.config.finder.locations.immoscout

    def build_url(self, category: str, location: str, page: int = 0) -> str:
        url = f"{self.BASE_URL}/{category}?shape={location}&enteredFrom=result_list&sorting=2"
        if page > 1:
            url += f"&pagenumber={page}"
        return url

    def get_json_data(self, soup: BeautifulSoup) -> dict[str, Any]:
        json_script_tag = soup.find("script", string=lambda text: text is not None and "IS24.resultList" in text)  # type: ignore

        if json_script_tag is None:
            raise ElementNotFoundError("Script tag containing JSON data")
        if type(json_script_tag) != Tag:
            raise NotBeautifulSoupError("json_script")

        json_data: str = (
            str(json_script_tag)
            .split("resultListModel: ")[1]
            .split("isUserLoggedIn")[0]
            .strip()[:-1]
            .replace(": undefined", ": null")
        )
        

        return json.loads(json_data)

    def get_listings(self, soup: BeautifulSoup) -> list[NewListing]:
        json_data = self.get_json_data(soup)
        result_list = json_data["searchResponseModel"]["resultlist.resultlist"]["resultlistEntries"][0]
        if "resultlistEntry" not in result_list:
            self.logger.warning("No listings found on this page, skipping")
            return []

        result_entries: list[dict[str, Any]] = result_list["resultlistEntry"]
        listings: list[NewListing] = []

        for entry in result_entries:
            if "@id" not in entry or "@modification" not in entry or "@creation" not in entry:
                continue
            listings.append(extract_listing_data(entry))

            if "similarObjects" in entry:
                similar_objects: list[Any] = entry["similarObjects"][0]["similarObject"]
                for similar_entry in similar_objects:
                    if not isinstance(similar_entry, dict) or "@id" not in similar_entry:
                        continue
                    listings.append(extract_listing_data(similar_entry))
        return listings

    def get_pages_count(self, soup: BeautifulSoup) -> int:
        pagination_buttons = soup.find_all(attrs={"data-testid": "pagination-button"})
        if len(pagination_buttons) < 2:
            self.logger.warning("No pagination buttons found, assuming only one page")
            return 1
        last_page_number = int(pagination_buttons[-1].get_text(strip=True))
        return last_page_number

# --- Entry Point ---
if __name__ == "__main__":
    finder = ImmoscoutFinder()
    finder.run()