import re
from enum import Enum
from functools import cached_property


class Patterns(str, Enum):
    NON_DIGIT = r"\D+"
    NON_ALPHA = r"\W+"
    MULTI_SPACE = r"\s+"

    STREET_HOUSE = r"^(.+?)\s+(\d+\s?-\s?\d+|\d+\s?[a-zA-Z]?|[xX*#0]+)$"
    STRASSE = r"(?<=[a-zA-ZäöüÄÖÜß\s])str\s?\.?(?=\.?\s?\d|\.?\d|$)"

    DATE_SPECIFIC = r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})"
    DATE_TEXTUAL = r"(\d{1,2})\.\s*([a-zä]+)\.?\s+(\d{4})"
    DATE_MONTH_YEAR = r"(\d{1,2})[./-](\d{4})$|^([a-zä.]+)\s+(\d{4})"
    DATE_QUARTER = r"(\d?[q]\d?)[ \/.]+(\d{4}|\d{2})"

    @cached_property
    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.value)

    @cached_property
    def compiled_ignore_case(self) -> re.Pattern[str]:
        return re.compile(self.value, flags=re.IGNORECASE)

    def match(self, text: str) -> re.Match[str] | None:
        return self.compiled.match(text)

    def search(self, text: str) -> re.Match[str] | None:
        return self.compiled.search(text)

    def sub(self, repl: str, string: str, ignore_case: bool = True) -> str:
        if ignore_case:
            return self.compiled_ignore_case.sub(repl, string)
        return self.compiled.sub(repl, string)
