from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, ClassVar, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from shapely import MultiPolygon, Polygon

from lib.cleaners import clean_base_url
from lib.date import clean_date_text, parse_date


class EnergySource(str, Enum):
    GAS = "gas"
    OIL = "oil"
    ELECTRICITY = "electricity"
    DISTRICT_HEATING = "district_heating"
    HEAT_PUMP = "heat_pump"
    SOLAR = "solar"
    WOOD = "wood"
    COAL = "coal"
    OTHER = "other"
    NONE = "none"


class EnergyEfficiencyClass(str, Enum):
    A_PLUS_PLUS = "A_PLUS_PLUS"
    A_PLUS = "A_PLUS"
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"
    H = "H"


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


@dataclass
class Address:
    street: str | None
    house_number: str | None
    zipcode: str | None
    city: str | None
    state: str | None
    suburb: str | None
    latitude: float | None
    longitude: float | None
    coordinates: Polygon | MultiPolygon | None
    place_ids: list[str] | None


T = TypeVar("T", bound=BaseModel)


class CaseInsensitiveEnumMixin:
    @staticmethod
    def v(field: str) -> Callable[[type[BaseModel], Any], Any]:
        @field_validator(field, mode="before")
        @classmethod
        def _normalize(cls: type[T], v: Any) -> Any:
            if isinstance(v, str):
                return v.lower()
            return v

        return _normalize


class NewListing(BaseModel):
    external_id: str
    source: ListingSource
    modified_at: datetime | None = None
    created_at: datetime | None = None


class Description(BaseModel):
    main: str | None
    features: str | None
    location: str | None
    other: str | None


class General(BaseModel):
    PROPERTY_TYPE_ALIASES: ClassVar[dict[str, str]] = {
        "loft": PropertyType.APARTMENT.value,
        "wohnung": PropertyType.APARTMENT.value,
    }

    title: str | None
    type: PropertyType | None = Field(description="ENUM: apartment|house|room|commercial|land|other")
    occupied: bool | None = Field(description="Ist die Immobilie aktuell oder beim Kauf vermietet?")
    available_from: date | None = Field(
        description="Ab wann ist die Immobilie fertiggestellt oder einzugsbereit? Beispiel: 18.03.2024, kurzfristig, sofort, 3Q 2024, ..."
    )
    forced_sale: bool | None = Field(description="Zwangsversteigerung, Gerichtlich, ... ?")
    for_sale: bool | None = Field(description="Geht es um einen Verkauf?")
    for_rent: bool | None = Field(description="Geht es um eine Vermietung?")
    trade: bool | None = Field(description="Tauschimmobilie, Immobilie zum Tauschen, ... ?")
    is_property: bool = Field(
        description="`true` wenn es sich um eine echte Immobilie, ein Objekt oder ein Zimmer handelt und zum Verkauf oder zur Miete ANGEBOTEN wird, und `false` falls es sich bei dem Listing nicht um eine Immobilie handelt sondern z.B. 'Staubsauger zu verkaufen' oder eine Immobilie gesucht statt angeboten wird z.B. 'Wir kaufen dein Objekt', 'Haus zum Kaufen gesucht', 'Wohnung gesucht', 'Immobilienbewertung' ..."
    )
    bidding: bool | None = Field(description="Wird die Immobilie versteigert?")
    social_housing: bool | None = Field(description="Sozialwohnung, Staatlich, WBS (Wohnberechtigungsschein), ... ?")
    leasehold: bool | None = Field(description="Handelt es sich um eine Erbpacht?")

    @field_validator("available_from", mode="before")
    def _parse_available_from(cls, v: str | None) -> date | None:
        if isinstance(v, str):
            return parse_date(clean_date_text(v))
        return v

    @field_validator("type", mode="before")
    def _normalize_type(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.lower()
            v = cls.PROPERTY_TYPE_ALIASES.get(v, v)
            try:
                PropertyType(v)
                return v
            except ValueError:
                return PropertyType.OTHER.value
        return v


class Features(BaseModel):
    balcony: bool | None = Field(description="Balkon, Terrasse, ... ?")
    garden: bool | None = Field(description="Garten, Gartenbeteiligung, ... ?")
    kitchen: bool | None = Field(description="Küche, eine Küche, Einbauküche, ... ?")
    elevator: bool | None = Field(description="Aufzug, ... ?")
    barrier_free_access: bool | None = Field(description="Barrierefreier Zugang, Behindertengerecht, ... ?")
    vacation_suitable: bool | None = Field(description="Ferienwohnung, Ferienwohnung geeignet... ?")
    furnished: bool | None = Field(description="Ist die Immobile möbeliert?")
    is_shared_flat: bool | None = Field(
        description="Handelt es sich bei dem Listing um eine Wohngemeinschaft (WG) oder shared living?"
    )
    number_of_roommates: int | None = Field(description="Gesamte Anzahl der WG Mitglieder")


class Building(CaseInsensitiveEnumMixin, BaseModel):
    rooms: float | None = Field(description="Gesamtanzahl der Zimmer")
    living_area_sqm: float | None = Field(description="Wohnfläche in m²")
    ground_area_sqm: float | None = Field(description="Grundstücksfläche in m² (bspw. bei Häusern)")
    storing_area_sqm: float | None = Field(
        description="Kellerzelle in m² (bspw. bei Wohnungen in Städten). Kellerzelle, Abstellraum, ... ?"
    )
    year_built: int | None = Field(description="Baujahr")
    condition: Literal["new_construction", "renovated", "used", "needs_renovation", "other"] | None = Field(
        description="ENUM: new_construction(Neubau)|renovated(renoviert, saniert)|used (gut erhalten, gebraucht, ...)|needs_renovation(benötigt renovierung, starke gebrauchspruen)|other"
    )
    modernization_year: int | None = Field(description="Jahr der letzten Modernisierung oder Renovierung")
    monument_protection: bool | None = Field(description="Denkmalschutz, ... ?")
    outdoor_parking: int | None = Field(
        description="Anzahl Außenstellplätze, Stellplätze, Carport, Duplexstellplätze, ... ?"
    )
    indoor_parking: int | None = Field(
        description="Anzahl Garagen, Tiefgaragenstellplätze, Duplex in der Tiefgarage, ... ?"
    )
    bathrooms: float | None = Field(
        description='Anzahl Badezimmer. bspw. "Bad" = 1 or "einem Luxusbad, zwei Bäder" = 3'
    )
    bedrooms: float | None = Field(description="Anzahl Schlafzimmer + Kinderzimmer")
    floor: int | None = Field(
        description="Etage einer Wohnung als Zahl. Erdgeschoss = 0, 1. OG = 1, Keller = -1, 2 von 3 = 2, ... ?"
    )
    floor_max: int | None = Field(description="Anzahl Etagen im Gebäude. 2 von 3 = 3, ... ?")
    internet_mbps: int | None = Field(description="Internetgeschwindigkeit in Mbps")
    guest_bathrooms: int | None = Field(
        description='Anzahl der Gäste WCs. bspw. "2 Gäste-WCs" = 2, "Gäste-Bad" = 1, "eine Toilette" = 1'
    )
    basement: bool | None = Field(description="Hat das Objekt einen Keller ?")

    @field_validator("condition", mode="before")
    def _normalize_condition(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.lower().replace(" ", "_")
            if v not in ["new_construction", "renovated", "used", "needs_renovation", "other"]:
                return "other"
        return v

    @field_validator("rooms", mode="before")
    def _limit_rooms(cls, v: float | None) -> float | None:
        if isinstance(v, (int, float)):
            return min(v, 999.0)
        return v


class Heating(CaseInsensitiveEnumMixin, BaseModel):
    ENERGY_SOURCE_ALIASES: ClassVar[dict[str, str]] = {
        "pellets": EnergySource.WOOD.value,
        "geothermal": EnergySource.HEAT_PUMP.value,
        "fernwärme": EnergySource.DISTRICT_HEATING.value,
    }

    energy_certificate_available: bool | None = Field(description="Ist der Energieausweis vorhanden?")
    main_energy_source: EnergySource | None = Field(
        description="Energieträger oder Heizungsart ...? :ENUM gas|oil|heat_pump|district_heating|wood|solar|electricity|coal|other|none Wenn mehrere genannt werden versuche den primären Energieträger anzugeben"
    )
    energy_efficiency_class: EnergyEfficiencyClass | None = Field(
        description="Ausgeschriebene Energieeffizienzklasse. ENUM A++|A+|A|B|C|D|E|F|G|H"
    )
    energy_demand_in_kwh_per_qm_per_a: float | None = Field(
        description="Energiebedarf, Verbrauch oder Kennwert in kWh/(m²*a)"
    )

    _normalize_type = CaseInsensitiveEnumMixin.v("main_energy_source")

    @field_validator("energy_efficiency_class", mode="before")
    def _normalize_energy_efficiency_class(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            plus_count = v.count("+")
            if plus_count > 2:
                for _ in range(plus_count - 2):
                    v = v.replace("+", "", 1)
            v = v.upper().replace("+", "_PLUS").strip()
            try:
                EnergyEfficiencyClass(v)
                return v
            except ValueError:
                return None
        return v

    @field_validator("main_energy_source", mode="before")
    def _normalize_main_energy_source(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.lower().replace(" ", "_")
            v = cls.ENERGY_SOURCE_ALIASES.get(v, v)
            try:
                EnergySource(v)
                return v
            except ValueError:
                return EnergySource.OTHER.value
        return v


class Contact(BaseModel):
    first_name: str | None = Field(description="Vorname der Kontaktperson")
    last_name: str | None = Field(description="Nachname der Kontaktperson")
    company: str | None = Field(description='Nur Firmenname und Gesellschaftsform. Bspw. "Müller Immobilien GmbH"')
    phone: str | None = Field(description="Telefonnummer")
    email: str | None = Field(description="E-Mail-Adresse")
    website: str | None = Field(description="Webseite")
    is_private: bool | None = Field(description="Privater Anbieter oder Makler/Firma?")

    @field_validator("first_name", "last_name", mode="before")
    def _normalize_name(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip().title()

    @field_validator("website", mode="before")
    def _normalize_website(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.strip()
            if v:
                v = clean_base_url(v)
                if not v.startswith(("http://", "https://")):
                    v = "https://" + v
            else:
                v = None
        return v


class Financial(BaseModel):
    price: float | None = Field(
        description='Kaufpreis oder Miete (Kaltmiete ohne Nebenkosten) der Immobilie. Beachte dass die Dezimalstellen in Deutschland mit "," und nicht mit "." getrennt werden. Beispiel: 1.500,00 = 1500.00'
    )
    price_per_sqm: float | None
    house_fee: float | None = Field(
        description="Hausgeld das der Vermieter zahlt. Hier sind NICHT die Nebenkosten für den Mieter gemeint"
    )
    utility_fee: float | None = Field(
        description="Nebenkosten die der Mieter zahlt. Hier ist NICHT das Hausgeld gemeint"
    )
    buyer_commission: float | None = Field(
        description="Käuferprovision in Prozent. Möglicherweise auch als Courtage oder Maklergebühr bezeichnet. Beispiel: 3,57%"
    )
    buyer_commission_amount: float | None = Field(
        description="Käuferprovision in Euro, wenn sie nicht in % angegeben ist. Kommt selten vor."
    )
    garage_price: float | None = Field(description="Zusätzlicher Preis oder monatliche Miete für Garage/Stellplatz")


class Location(BaseModel):
    suburb: str | None = Field(description="Stadtteil oder Ortsteil in dem sich die Immobilie befindet")


class PropertyData(BaseModel):
    general: General
    financial: Financial
    heating: Heating
    features: Features
    building: Building
    contact: Contact
    location: Location

    def get_buyer_commission(self) -> float | None:
        if self.financial.buyer_commission_amount is None:
            return self.financial.buyer_commission

        if self.financial.price is None or self.financial.price == 0:
            return None

        return (self.financial.buyer_commission_amount / self.financial.price) * 100

    def get_price_per_sqm(self) -> float | None:
        if self.building.living_area_sqm is None or self.financial.price is None or self.financial.price == 0:
            return None

        if self.building.living_area_sqm == 0:
            return 0.0

        return self.financial.price / self.building.living_area_sqm
