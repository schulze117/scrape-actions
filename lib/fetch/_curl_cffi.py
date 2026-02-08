from curl_cffi import requests
from tenacity import retry, stop_after_attempt, wait_fixed, before_sleep_log
from lib.config import get_config
from lib.logger import get_logger

config = get_config()
logger = get_logger("_curl_cffi")

@retry(
    stop=stop_after_attempt(config.curl_cffi.max_retries),
    wait=wait_fixed(config.curl_cffi.retry_delay),
    reraise=True,
    before_sleep=before_sleep_log(logger, config.log_level)
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
        raise RuntimeError(f"Failed to fetch {url} with proxy {proxy_url or 'None'}: {e}")

# test fetch_html
if __name__ == "__main__":
    test_url = "https://www.kleinanzeigen.de/"
    proxy_url = None
    html = get_html_curlcffi(test_url, proxy_url)
    print(f"Fetched {len(html)} characters from {test_url}")