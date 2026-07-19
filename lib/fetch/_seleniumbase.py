import os

from seleniumbase import SB
from tenacity import retry, stop_after_attempt, wait_fixed, before_sleep_log
from lib.config import get_config
from lib.logger import get_logger
from lib.helpers import has_bot_detection

config = get_config()
logger = get_logger("_seleniumbase")

# On a bot-detection / captcha page, how many solve+reload cycles to try before
# giving up on this IP (then the workflow re-dispatches on a fresh runner IP).
BOT_SOLVE_ATTEMPTS = 3


def _try_solve_captcha(sb) -> str | None:
    """Best-effort click/solve of the captcha widget (AWS WAF / Imperva / Cloudflare
    / reCAPTCHA). Uses whichever method the installed SeleniumBase version exposes;
    requires uc=True + a display (xvfb=True). Returns the method name used, or None."""
    for name in ("solve_captcha", "gui_click_captcha", "uc_gui_click_captcha"):
        fn = getattr(sb, name, None)
        if callable(fn):
            try:
                fn()
                return name
            except Exception as e:  # method may not apply to this captcha type
                logger.info(f"{name}() did not apply: {e}")
    return None


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
            sb.sleep(2)
            html = sb.get_page_source()

            if has_bot_detection(html):
                # Try to actively clear the captcha (AWS WAF / Imperva). Each cycle:
                # click/solve the captcha, wait for the WAF token, and if still
                # blocked, reload and re-check. Only then give up (workflow rotates IP).
                for solve_attempt in range(1, BOT_SOLVE_ATTEMPTS + 1):
                    logger.info(
                        f"Bot detection suspected, attempting captcha solve "
                        f"(attempt {solve_attempt}/{BOT_SOLVE_ATTEMPTS})..."
                    )
                    used = _try_solve_captcha(sb)
                    sb.sleep(8)  # give the WAF challenge time to issue a token / redirect
                    html = sb.get_page_source()
                    if not has_bot_detection(html):
                        logger.info(
                            f"Bot detection cleared after solve attempt {solve_attempt} "
                            f"(method: {used or 'wait-only'})."
                        )
                        break

                    # Fallback: reload the page and re-check.
                    sb.refresh()
                    sb.wait_for_ready_state_complete(timeout=timeout)
                    sb.sleep(4)
                    html = sb.get_page_source()
                    if not has_bot_detection(html):
                        logger.info(f"Bot detection cleared after reload (attempt {solve_attempt}).")
                        break
                else:
                    logger.error(
                        f"Bot detection persists after {BOT_SOLVE_ATTEMPTS} solve+reload attempts "
                        f"for {url}. HTML length: {len(html)}. Stopping program."
                    )
                    print(f"\n{'='*80}")
                    print(f"BOT DETECTION PAGE HTML ({url}):")
                    print(f"{'='*80}")
                    print(html)
                    print(f"{'='*80}\n")
                    os._exit(42)

        return html
    except Exception as e:
        logger.error(f"Failed to fetch {url} with SeleniumBase: {e}")
        raise RuntimeError(f"Failed to fetch {url} with SeleniumBase: {e}")

# test fetch_html
if __name__ == "__main__":
    test_url = "https://www.immobilienscout24.de/expose/166611357"
    proxy_url = "http://35.243.132.55:8888"
    html = get_html_seleniumbase(test_url, proxy_url=proxy_url)