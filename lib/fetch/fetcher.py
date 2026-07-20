import atexit

from lib.fetch._curl_cffi import get_html_curlcffi
# from lib.fetch._playwright import get_html_playwright
from lib.fetch._seleniumbase import get_html_seleniumbase
from lib.proxy import FirewallManager

from lib.config import get_config, env_bool
from lib.helpers import redact_proxy
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
        # Only for the self-hosted GCP proxy, which allow-lists the caller's IP.
        # Third-party proxies (e.g. DataImpulse) need none of this, and running
        # it without GCP credentials present just throws — hence opt-in.
        self._fw_manager = None
        if self.proxy_url and env_bool("PROXY_MANAGE_FIREWALL", False):
            try:
                logger.info("Proxy detected. initializing firewall...")
                self._fw_manager = FirewallManager()
                self._fw_manager.authorize_current_ip()
            except Exception as e:
                logger.warning(f"Could not update firewall rules: {e}")
                # We don't raise here, in case the rule already exists
                # or we want to try fetching anyway.
        elif self.proxy_url:
            logger.info(f"Using proxy {redact_proxy(self.proxy_url)}")

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
