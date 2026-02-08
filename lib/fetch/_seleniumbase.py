from seleniumbase import SB
from tenacity import retry, stop_after_attempt, wait_fixed, before_sleep_log
from lib.config import get_config
from lib.logger import get_logger

config = get_config()
logger = get_logger("_seleniumbase")


@retry(
    stop=stop_after_attempt(config.seleniumbase.max_retries),
    wait=wait_fixed(config.seleniumbase.retry_delay),
    reraise=True,
    before_sleep=before_sleep_log(logger, config.log_level)
)
def get_html_seleniumbase(
    url: str,
    proxy_url: str | None = None,
    timeout: int | None = None,
    uc: bool | None = None,
    xvfb: bool | None = None,
    headless: bool | None = None,
    locale: str | None = None,
    incognito: bool | None = None,
    block_images: bool | None = None,
) -> str:
    # Use config defaults if not provided
    timeout = timeout if timeout is not None else config.seleniumbase.timeout
    uc = uc if uc is not None else config.seleniumbase.uc
    xvfb = xvfb if xvfb is not None else config.seleniumbase.xvfb
    headless = headless if headless is not None else config.seleniumbase.headless
    locale = locale if locale is not None else config.seleniumbase.locale
    incognito = incognito if incognito is not None else config.seleniumbase.incognito
    block_images = block_images if block_images is not None else config.seleniumbase.block_images

    try:
        with SB(
            uc=uc,
            proxy=proxy_url if proxy_url else None,
            xvfb=xvfb,
            headless=headless,
            locale=locale,
            incognito=incognito,
            block_images=block_images,
        ) as sb:
            sb.activate_cdp_mode(url)
            sb.wait_for_ready_state_complete(timeout=timeout)
            sb.sleep(1)
            html = sb.get_page_source()
        return html
    except Exception as e:
        logger.error(f"Failed to fetch {url} with SeleniumBase: {e}")
        raise RuntimeError(f"Failed to fetch {url} with SeleniumBase: {e}")

# test fetch_html
if __name__ == "__main__":
    test_url = "https://www.immobilienscout24.de/expose/165390369"
    proxy_url = "http://35.234.92.79:8888"
    html = get_html_seleniumbase(test_url, proxy_url=proxy_url)
    print(f"Fetched {len(html)} characters from {test_url}")