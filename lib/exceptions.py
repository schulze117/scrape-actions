class ScrapeError(Exception):
    """Base class for all scrape-related exceptions."""


class GoneError(ScrapeError):
    """Raised when a listing is no longer available."""

    def __init__(self, item_name: str):
        super().__init__(f'Listing "{item_name}" is gone')


class ElementNotFoundError(ScrapeError):
    """Raised when a required element is not found in the HTML content."""

    def __init__(self, item_name: str):
        super().__init__(f'Element "{item_name}" not found')


class ElementDisabledError(ScrapeError):
    """Raised when an element is found but is disabled."""

    def __init__(self, item_name: str):
        super().__init__(f'Element "{item_name}" is disabled')


class NotBeautifulSoupError(ScrapeError):
    """Raised when an expected BeautifulSoup object is not found."""

    def __init__(self, item_name: str):
        super().__init__(f'Element "{item_name}" is not a BeautifulSoup object')


class InactiveListingError(ScrapeError):
    """Raised when a listing is inactive."""

    def __init__(self, external_id: str):
        super().__init__(f'Listing "{external_id}" is inactive')


class ExecutionStoppedError(Exception):
    """Raised when the execution is stopped."""

    def __init__(self, message: str = "Execution stopped"):
        super().__init__(message)


class ServerError(Exception):
    """Raised when a server error occurs."""

    def __init__(self, url: str, status_code: int, message: str = "Server error occurred"):
        super().__init__(f'"{message}" for URL {url} with status code {status_code}')
        self.url = url
        self.status_code = status_code


class HTMLValidationError(Exception):
    """Raised when the HTML content is invalid or empty."""

    def __init__(self, message: str = "HTML content is invalid or empty"):
        super().__init__(message)
