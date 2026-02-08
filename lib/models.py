from datetime import datetime
from enum import Enum
from typing import Any

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel


class PropertyType(str, Enum):
    APARTMENT = "apartment"
    HOUSE = "house"
    ROOM = "room"
    COMMERCIAL = "commercial"
    LAND = "land"
    OTHER = "other"


class ListingSource(Enum):
    KLEINANZEIGEN = "kleinanzeigen"
    IMMOBILIENSCOUT24 = "immoscout"
    IMMOWELT = "immowelt"


class SearchCategory(str, Enum):
    WOHNUNG_MIETEN = "WOHNUNG_MIETEN"
    WOHNUNG_KAUFEN = "WOHNUNG_KAUFEN"
    HAUS_MIETEN = "HAUS_MIETEN"
    HAUS_KAUFEN = "HAUS_KAUFEN"
    NEUBAUWOHNUNG_KAUFEN = "NEUBAUWOHNUNG_KAUFEN"


IMMOSCOUT_SEARCH_CATEGORIES: dict[SearchCategory, str] = {
    SearchCategory.WOHNUNG_MIETEN: "wohnung-mieten",
    SearchCategory.WOHNUNG_KAUFEN: "wohnung-kaufen",
    SearchCategory.HAUS_MIETEN: "haus-mieten",
    SearchCategory.HAUS_KAUFEN: "haus-kaufen",
    SearchCategory.NEUBAUWOHNUNG_KAUFEN: "neubauwohnung-kaufen",
}

IMMOWELT_SEARCH_CATEGORIES: dict[SearchCategory, str] = {
    SearchCategory.WOHNUNG_MIETEN: "estateTypes=Apartment&distributionTypes=Rent&projectTypes=Stock,Flatsharing,New_Build", # Exclude Tauschwohnungen
    SearchCategory.WOHNUNG_KAUFEN: "estateTypes=Apartment&distributionTypes=Buy",
    SearchCategory.HAUS_MIETEN: "estateTypes=House&distributionTypes=Rent",
    SearchCategory.HAUS_KAUFEN: "estateTypes=House&distributionTypes=Buy",
}

KLEINANZEIGEN_SEARCH_CATEGORIES: dict[SearchCategory, str] = {
    SearchCategory.WOHNUNG_MIETEN: "203",
    SearchCategory.WOHNUNG_KAUFEN: "196",
    SearchCategory.HAUS_MIETEN: "205",
    SearchCategory.HAUS_KAUFEN: "208",
}


@dataclass
class NextListingModel:
    id: UUID
    source: str
    external_id: str
    created_at: datetime
    last_scraped_at: datetime | None
    modified_at: datetime | None


@dataclass
class NextRawDataModel:
    id: UUID
    external_id: str
    last_scraped_at: datetime
    html: str
    json: dict[str, Any]



class NewListing(BaseModel):
    external_id: str
    source: ListingSource
    modified_at: datetime | None = None
    created_at: datetime | None = None