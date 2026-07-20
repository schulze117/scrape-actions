import logging

from curl_cffi import requests
from tenacity import retry, stop_after_attempt, wait_fixed, before_sleep_log
from lib.config import get_config
from lib.helpers import redact_proxy
from lib.logger import get_logger

config = get_config()
logger = get_logger("_curl_cffi")

# tenacity's before_sleep_log needs an int level; config.log_level is a string.
_LOG_LEVEL_INT = getattr(logging, str(getattr(config, "log_level", "INFO")).upper(), logging.INFO)

@retry(
    stop=stop_after_attempt(config.curl_cffi.max_retries),
    wait=wait_fixed(config.curl_cffi.retry_delay),
    reraise=True,
    before_sleep=before_sleep_log(logger, _LOG_LEVEL_INT)
)
def get_html_curlcffi(url: str, proxy_url: str | None = None) -> str:
    try: 
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        response = requests.get(
            url,
            proxies=proxies,
            impersonate="chrome",
            timeout=config.curl_cffi.timeout
        )
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch {url}: Status code {response.status_code}")
        return response.text
    except Exception as e:
        # Never interpolate the raw proxy_url here — it carries credentials and
        # this repo's Action logs are public.
        proxy_desc = redact_proxy(proxy_url) if proxy_url else "None"
        raise RuntimeError(f"Failed to fetch {url} with proxy {proxy_desc}: {e}")

# test fetch_html
if __name__ == "__main__":
    test_url = "https://www.kleinanzeigen.de/"
    proxy_url = None
    html = get_html_curlcffi(test_url, proxy_url)
    print(f"Fetched {len(html)} characters from {test_url}")