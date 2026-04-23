from typing import Any

from bs4 import BeautifulSoup

from lib.cleaners import deep_remove_keys, filter_none_values, filter_urls, filter_values
from lib.coordinates import to_multipolygon, to_polygon
from lib.models import Address, Description, ListingSource
from lib.parsers import parse_address
from .base import BaseExtractor

IMMOWELT_JSON_KEY_FILTERS: set[str] = {
    "error",
    "seo",
    "metadata",
    "key",
    "gallery",
    "geometry",
    "locationDescription",
    "texts",
    "enrichedMedia",
    "sellerLeadLink",
    "areaDescription",
    "mainDescription",
    "extendedInfoDescription",
    "tracking",
    "advertising",
    "partnerAd",
}


class ImmoweltExtractor(BaseExtractor):
    def __init__(self):
        super().__init__(source=ListingSource.IMMOWELT)

    def get_title(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        sections = json_data["app_cldp"]["data"]["classified"]["sections"]
        title = sections["mainDescription"].get("headline", None) or sections["description"].get("headline", None)

        if not title:
            raise ValueError("Title data is missing or empty.")
        return title

    def get_price(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> float | None:
        price = json_data["app_cldp"]["data"]["classified"]["sections"]["hardFacts"]["price"].get("ariaLabel")

        if price is None or not isinstance(price, str) or not price.strip():
            self.logger.warning("Price data is missing or empty.")
            return None

        price = price.replace("€", "").replace("Euro", "").replace("pro Quadratmeter", "").replace(",", ".").strip()
        return float(price)

    def get_address(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> Address:
        sections = json_data["app_cldp"]["data"]["classified"]["sections"]
        location = sections["location"]
        address = location["address"]

        street = house_number = None
        if "street" in address:
            street, house_number = parse_address(address["street"])

        postal_code = address.get("zipCode")
        city = address.get("city")
        state = sections["mortgage"].get("region")

        longitude = latitude = coordinates = None

        if "geometry" in location:
            raw_coordinates = location["geometry"]["coordinates"]

            if location["geometry"]["type"] == "Point":
                longitude = raw_coordinates[0]
                latitude = raw_coordinates[1]
            elif location["geometry"]["type"] == "MultiPolygon":
                if len(raw_coordinates) == 1:
                    coordinates = to_polygon(raw_coordinates[0])
                else:
                    coordinates = to_multipolygon(raw_coordinates)

        return Address(
            street=street,
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
        sections = json_data["app_cldp"]["data"]["classified"]["sections"]
        main_description = sections.get("mainDescription", {})
        main: str | None = main_description.get("description") or main_description.get("headline", None)

        area_description = sections.get("areaDescription", {})
        location: str | None = area_description.get("description", None)

        extended_info: dict[str, Any] = sections.get("extendedInfoDescription", {})
        other: str | None = extended_info.get("description", None)

        return Description(main=main, features=None, location=location, other=other)

    def get_ai_input(self, soup: BeautifulSoup, json_data: dict[str, Any]) -> str:
        cleaned_data = filter_values(
            deep_remove_keys(json_data, IMMOWELT_JSON_KEY_FILTERS), [filter_urls, filter_none_values]
        )
        return str(cleaned_data)


# --- Entry Point ---
if __name__ == "__main__":
    extractor = ImmoweltExtractor()
    ids= [
        "2566ST4KMRR2",
        "23W5S6STYCEU",
    ]
    extractor.test_run(ids=ids)
    # extractor.run()
