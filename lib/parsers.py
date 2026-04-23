from lib.regex import Patterns

INVALID_STREET_NAMES = ["h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"]


def is_invalid_street_name(street: str | None) -> bool:
    if not street:
        return True

    street = street.strip().lower()

    if any(char in ":,*#@!\\|/" for char in street):
        return True

    if street in [*INVALID_STREET_NAMES, "xx", "xxx"]:
        return True

    if len(street) > 50:
        return True

    try:
        int(street)
        return True
    except ValueError:
        pass

    return False


def is_invalid_house_number(house_number: str | None) -> bool:
    if not house_number:
        return True

    if any(char.lower() in "x*#" for char in house_number) or house_number in {"0", "00", "000"}:
        return True

    if not any(char.isdigit() for char in house_number):
        return True

    try:
        if int(house_number) > 2000:
            return True
    except ValueError:
        pass

    return False


def preprocess_address(string: str) -> str:
    string = Patterns.STRASSE.sub("straße ", string, ignore_case=True)
    string = Patterns.MULTI_SPACE.sub(" ", string)
    return string.title()


def extract_street_and_house(string: str) -> tuple[str, str | None]:
    match = Patterns.STREET_HOUSE.match(string)
    if not match:
        return string, None

    street = match.group(1).strip()
    house_number = match.group(2).strip()

    if is_invalid_house_number(house_number):
        house_number = None

    return street, house_number


def normalize_street_name(street: str) -> str:
    street = street.strip().lower()
    if street.endswith("str."):
        street = street[:-4].strip() + "straße"
    elif street.endswith("str"):
        street = street[:-3].strip() + "straße"
    elif street.endswith("strasse"):
        street = street[:-7].strip() + "straße"
    return street.title()


def parse_address(string: str) -> tuple[str | None, str | None]:
    cleaned_string = string.strip().strip(",")
    preprocessed_string = preprocess_address(cleaned_string)
    street, house_number = extract_street_and_house(preprocessed_string)

    if is_invalid_street_name(street):
        return None, None

    street = normalize_street_name(street)
    return street, house_number
