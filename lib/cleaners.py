import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from lib.types import JSONType


def deep_remove_keys(data: JSONType, keys_to_remove: set[str]) -> JSONType:
    if isinstance(data, dict):
        return {k: deep_remove_keys(v, keys_to_remove) for k, v in data.items() if k not in keys_to_remove}
    elif isinstance(data, list):
        return [deep_remove_keys(item, keys_to_remove) for item in data]
    return data


def filter_values(data: JSONType, filters: list[Callable[[Any], bool]]) -> JSONType:
    if isinstance(data, dict):
        result = {k: filter_values(v, filters) for k, v in data.items()}
        return {k: v for k, v in result.items() if not any(f(v) for f in filters)}
    elif isinstance(data, list):
        result = [filter_values(item, filters) for item in data]
        return [item for item in result if not any(f(item) for f in filters)]
    return data


def get_html_text(
    soup: BeautifulSoup, tags_to_bold: Callable[[Tag], bool], tags_to_filter: Callable[[Tag], bool]
) -> str:
    for tag in soup.find_all(tags_to_filter):
        assert isinstance(tag, Tag), "Expected tag to be of type bs4.Tag"
        tag.decompose()

    for tag in soup.find_all(tags_to_bold):
        assert isinstance(tag, Tag), "Expected tag to be of type bs4.Tag"
        tag_text = tag.find(string=True, recursive=False)

        if not tag_text or not isinstance(tag_text, str):
            continue

        if tag_text.strip():
            new_text = f"**{tag_text.strip()}**"
            tag_text.replace_with(new_text)

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"[ ­\t]+", " ", text)
    return text


def clean_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[ ]+", " ", text)
    return text


def filter_urls(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("http") or value.startswith("www")
    return False


def filter_none_values(value: Any) -> bool:
    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, list) and not value)
        or (isinstance(value, dict) and len(value.keys()) == 0)  # type: ignore
    )


def is_heading(tag: Tag) -> bool:
    return tag.name in ["h1", "h2", "h3", "h4", "h5", "h6"]


def clean_base_url(url: str) -> str:
    url = url.strip().lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed_url = urlparse(url)
    return f"{parsed_url.scheme}://{parsed_url.netloc}"
