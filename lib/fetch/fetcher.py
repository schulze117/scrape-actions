import atexit

from lib.fetch._curl_cffi import get_html_curlcffi
# from lib.fetch._playwright import get_html_playwright
from lib.fetch._seleniumbase import get_html_seleniumbase
from lib.proxy import FirewallManager

from lib.config import get_config
from lib.logger import get_logger

config = get_config()
logger = get_logger("fetcher")

class Fetcher:
    def __init__(self, method: str, proxy_url: str | None = None):
        """
        :param method: "curl_cffi", "playwright", etc.
        :param proxy_url: The full proxy string (e.g. http://user:pass@ip:port) or None
        """
        self.method = method
        self.proxy_url = proxy_url
        
        # --- FIREWALL INTEGRATION ---
        self._fw_manager = None
        if self.proxy_url:
            try:
                logger.info("Proxy detected. initializing firewall...")
                self._fw_manager = FirewallManager()
                self._fw_manager.authorize_current_ip()
            except Exception as e:
                logger.warning(f"Could not update firewall rules: {e}")
                # We don't raise here, in case the rule already exists 
                # or we want to try fetching anyway.

    def fetch(self, url: str) -> str:
        """
        Determines proxy, selects method, and returns HTML string.
        """
        
        if self.method == "curl_cffi":
            return get_html_curlcffi(url, proxy_url=self.proxy_url)
            
        elif self.method == "playwright":
            # return get_html_playwright(url, proxy_url=proxy_url)
            raise NotImplementedError("Playwright fetcher is not yet implemented.")
            
        elif self.method == "seleniumbase":
            return get_html_seleniumbase(url, proxy_url=self.proxy_url)
            
        else:
            raise ValueError(f"Unknown fetching method in config: {self.method}")
        
# TODO: Add bot detection detection

def has_bot_detection(html: str, keywords: list[str] | None = None) -> bool:
    """
    Return True if the HTML indicates that a bot / captcha verification
    page was shown instead of the real content.

    Detection is done via simple case-insensitive keyword search.
    """
    default_keywords = [
        "ich bin kein roboter",   # German reCAPTCHA text
        "i am not a robot",
        "i’m not a robot",
        "captcha",
        "unusual traffic",
        "verify you are a human",
        "verify that you are human",
    ]

    patterns = keywords or default_keywords
    text = html.lower()

    for phrase in patterns:
        if phrase.lower() in text:
            logger.info(f"Bot detection pattern found in HTML: {phrase!r}")
            return True

    return False