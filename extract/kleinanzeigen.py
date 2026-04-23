from typing import Any

from bs4 import BeautifulSoup, Tag

from lib.cleaners import clean_text, get_html_text, is_heading
from lib.exceptions import ElementNotFoundError
from lib.models import Address, Description, ListingSource
from lib.parsers import parse_address
from .base import BaseExtractor


class KleinanzeigenExtractor(BaseExtractor):
    def __init__(self):
        super().__init__(source=ListingSource.KLEINANZEIGEN)

    def get_title(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        title_tag = soup.find("h1", {"id": "viewad-title"})
        if not title_tag or not isinstance(title_tag, Tag):
            raise ElementNotFoundError("Title tag")
        return clean_text(title_tag.get_text(strip=True)).strip("**")

    def get_price(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> float | None:
        price = json_data.get("dimension31")
        if price is None or not isinstance(price, str):
            return None
        return float(price)

    def get_address(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> Address:
        street = house_number = None
        street_data = soup.find("span", {"id": "street-address"})
        if isinstance(street_data, Tag):
            street_text = street_data.get_text(strip=True)
            street, house_number = parse_address(street_text)

        postal_code = (
            json_data.get("dimension13") or json_data.get("dimension45") or json_data.get("dimension97")
        )
        city = json_data.get("dimension95")
        state = json_data.get("dimension94")

        longitude = self._extract_meta_float(soup, "og:longitude")
        latitude = self._extract_meta_float(soup, "og:latitude")

        return Address(
            street=street,
            house_number=house_number,
            zipcode=postal_code,
            city=city,
            state=state,
            latitude=latitude,
            longitude=longitude,
            coordinates=None,
            suburb=None,
            place_ids=None,
        )

    def get_description(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> Description:
        description_tag = soup.find("p", {"id": "viewad-description-text"})
        if not description_tag or not isinstance(description_tag, Tag):
            raise ElementNotFoundError("Main description tag")
        main = clean_text(description_tag.get_text(strip=True))
        return Description(main=main, features=None, location=None, other=None)

    def get_ai_input(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        return get_html_text(soup, _kleinanzeigen_tags_to_bold, _kleinanzeigen_tags_to_filter)

    def _extract_meta_float(self, soup: BeautifulSoup, property_name: str) -> float:
        tag = soup.find("meta", {"property": property_name})
        if not tag or not isinstance(tag, Tag):
            raise ElementNotFoundError(f"{property_name} meta tag")

        content = tag.get("content")
        if not isinstance(content, str) or not content:
            raise ValueError(f"{property_name} content is missing or not a string")
        return float(content)


def _kleinanzeigen_tags_to_bold(tag: Tag) -> bool:
    return is_heading(tag) or "addetailslist--detail" in tag.get("class", [])


def _kleinanzeigen_tags_to_filter(tag: Tag) -> bool:
    if tag.name in ["script", "style", "noscript", "a", "button", "input", "form"]:
        return True

    if {"viewad-user-actions", "viewad-contact-bottom", "follow-user-button", "viewad-imprint"} & set(
        [tag.get("id", "")]
    ):
        return True

    if {"galleryimage-large", "button-share"} & set(tag.get("class", [])):
        return True

    return False


# --- Entry Point ---
if __name__ == "__main__":
    extractor = KleinanzeigenExtractor()
    ids= [
        "3240235223",
        "3284839151",
    ]
    extractor.test_run(ids=ids)
    # extractor.run()
