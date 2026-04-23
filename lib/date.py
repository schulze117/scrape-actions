import re
from datetime import date

from lib.regex import Patterns

REMOVABLE_PREFIXES = ["vermietet bis ", "verfügbar ab ", "ab ", "bis ", "vom ", "zum ", "per "]
IMMEDIATE_KEYWORDS = ["sofort", "kurzfristig", "immediately"]
MONTHS_MAP = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
    "jan": 1, "feb": 2, "mär": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12,
}

VALID_YEAR_RANGE = 20
CURRENT_YEAR = date.today().year
MIN_YEAR = CURRENT_YEAR - VALID_YEAR_RANGE
MAX_YEAR = CURRENT_YEAR + VALID_YEAR_RANGE


def clean_date_text(date_text: str) -> str:
    date_text = date_text.split(";")[0].strip()
    date_text = date_text.lower().strip().replace("..", ".")
    date_text = " ".join(date_text.split())

    for word in REMOVABLE_PREFIXES:
        date_text = date_text.replace(word, "")

    return date_text


def parse_date(date_text: str) -> date | None:
    if not date_text:
        return None

    if any(keyword in date_text for keyword in IMMEDIATE_KEYWORDS):
        return date.today()

    return (
        parse_specific_date(date_text)
        or parse_textual_date(date_text)
        or parse_month_year_date(date_text)
        or parse_quarter_date(date_text)
        or parse_year_only(date_text)
    )


def parse_specific_date(date_text: str) -> date | None:
    match = Patterns.DATE_SPECIFIC.search(date_text)
    if not match:
        return None

    day, month, year = map(int, match.groups())
    if year < 100:
        year += 2000
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_textual_date(date_text: str) -> date | None:
    match = Patterns.DATE_TEXTUAL.search(date_text)
    if not match:
        return None

    day = int(match.group(1))
    month = MONTHS_MAP.get(match.group(2).strip("."))
    year = int(match.group(3))
    if not (month and MIN_YEAR <= year <= MAX_YEAR):
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_month_year_date(date_text: str) -> date | None:
    match = Patterns.DATE_MONTH_YEAR.search(date_text)
    if not match:
        return None

    if match.group(1):
        month, year = int(match.group(1)), int(match.group(2))
    else:
        month = MONTHS_MAP.get(match.group(3).strip(".").lower())
        year = int(match.group(4))

    if not (month and MIN_YEAR <= year <= MAX_YEAR):
        return None

    try:
        return date(year, month, 1)
    except ValueError:
        return None


def parse_quarter_date(date_text: str) -> date | None:
    match = Patterns.DATE_QUARTER.search(date_text)
    if not match:
        return None

    quarter = match.group(1)
    if not quarter:
        return None

    quarter = int(quarter.replace("q", ""))
    if not (1 <= quarter <= 4):
        return None

    year = int(match.group(2))
    if year < 100:
        year += 2000
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None

    month = (quarter - 1) * 3 + 1
    try:
        return date(year, month, 1)
    except ValueError:
        return None


def parse_year_only(date_text: str) -> date | None:
    year_match = re.match(r"^(\d{4})$", date_text)
    if not year_match:
        return None

    year = int(year_match.group(1))
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None

    try:
        return date(year, 1, 1)
    except ValueError:
        return None
