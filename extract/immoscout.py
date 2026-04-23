import json
from typing import Any

from bs4 import BeautifulSoup, Tag

from lib.cleaners import clean_text, get_html_text, is_heading
from lib.coordinates import to_box
from lib.exceptions import ElementNotFoundError
from lib.models import Address, Description, ListingSource
from lib.parsers import parse_address
from .base import BaseExtractor


class ImmoscoutExtractor(BaseExtractor):
    def __init__(self):
        super().__init__(source=ListingSource.IMMOBILIENSCOUT24)

    def get_title(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        title_tag = soup.find("h1", {"id": "expose-title"})
        if not title_tag or not isinstance(title_tag, Tag):
            raise ElementNotFoundError("Title tag")
        return clean_text(title_tag.get_text(strip=True)).strip("**")

    def get_price(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> float:
        price = json_data.get("propertyPrice")
        if price is None or not isinstance(price, str):
            raise ValueError(f"Price data is missing or not a string. Received: {price}, type: {type(price)}")
        return float(price)

    def get_address(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> Address:
        location = json_data["locationAddress"]

        street = location.get("street")
        house_number = location.get("houseNumber")
        if street:
            street, house_number = parse_address(f"{street} {house_number}")

        postal_code = location.get("zip")
        city = location.get("city")
        state_tag = soup.find("div", {"class": "finance-widget", "data-region": True})
        state = str(state_tag.get("data-region")) if isinstance(state_tag, Tag) else None

        coordinates_data = location.get("coordinates")
        latitude = longitude = coordinates = None
        if "reference-price" in coordinates_data:
            latitude = float(coordinates_data.split("latitude\\/")[1].split("\\/longitude")[0].strip())
            longitude = float(coordinates_data.split("longitude\\/")[1].split("?realEstateType")[0].strip())
        elif "southWest" in coordinates_data and "northEast" in coordinates_data:
            envelope = _envelope_from_bounds(coordinates_data)
            coordinates = to_box(envelope)
        else:
            latitude, longitude = map(float, coordinates_data.split(","))

        return Address(
            street=street.strip() if street else None,
            house_number=house_number,
            zipcode=postal_code,
            city=city,
            state=state,
            latitude=latitude,
            longitude=longitude,
            coordinates=coordinates,
            suburb=None,
            place_ids=None,
        )

    def get_description(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> Description:
        main_description = soup.find("pre", {"class": "is24qa-objektbeschreibung"})
        main = main_description.get_text(strip=True) if isinstance(main_description, Tag) else None

        features_tag = soup.find("pre", {"class": "is24qa-ausstattung"})
        features = features_tag.get_text(strip=True) if isinstance(features_tag, Tag) else None

        location_tag = soup.find("pre", {"class": "is24qa-lage"})
        location = location_tag.get_text(strip=True) if isinstance(location_tag, Tag) else None

        other_tag = soup.find("pre", {"class": "is24qa-sonstiges"})
        other = other_tag.get_text(strip=True) if isinstance(other_tag, Tag) else None

        return Description(main=main, features=features, location=location, other=other)

    def get_ai_input(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        return get_html_text(soup, _immoscout_tags_to_bold, _immoscout_tags_to_filter)


def _envelope_from_bounds(json_str: str) -> tuple[float, float, float, float]:
    coords = json.loads(json_str)
    sw = coords["southWest"]
    ne = coords["northEast"]
    return sw["longitude"], sw["latitude"], ne["longitude"], ne["latitude"]


def _immoscout_tags_to_filter(tag: Tag) -> bool:
    if tag.name in ["a", "button", "input", "select", "textarea"]:
        return True

    if tag.get("id") in [
        "is24-gallery-entry-point",
        "counter-offer-button",
        "is24-expose-premium-stats-widget",
        "is24-expose-travel-time",
    ]:
        return True

    if set(tag.get("class", [])) & {
        "palm-hide",
        "lap-hide",
        "finance-widget",
        "verifiedBox",
        "consultationTextContainer",
        "cursor-pointer",
        "dsaNote",
        "main-criteria-container",
    }:
        return True

    return False


def _immoscout_tags_to_bold(tag: Tag) -> bool:
    if is_heading(tag):
        return True

    classes = set(tag.get("class", []))
    if any(class_.endswith("label") for class_ in classes):
        return True
    return False


# --- Entry Point ---
if __name__ == "__main__":
    extractor = ImmoscoutExtractor()
    ids= [
        "161993637",
        "162857841",
    ]
    extractor.test_run(ids=ids)
    # extractor.run()
