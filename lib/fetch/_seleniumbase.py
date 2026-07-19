import os

from seleniumbase import sb_cdp
from tenacity import retry, stop_after_attempt, wait_fixed, before_sleep_log
from lib.config import get_config
from lib.logger import get_logger
from lib.helpers import has_bot_detection

config = get_config()
logger = get_logger("_seleniumbase")

# On a bot-detection / captcha page, how many solve+reload cycles to try before
# giving up on this IP (then the workflow re-dispatches on a fresh runner IP).
BOT_SOLVE_ATTEMPTS = 3

# --- Hard-case stealth defaults (mdmintz's advice for the toughest anti-bot) ---
# Pure CDP Mode + the unbranded Chromium browser is the most stealthy combo.
# Timezone/geolocation must match the exit IP's country, else it's a tell.
# These are read from config.seleniumbase when present, else fall back to here,
# so the deployed CONFIG_FILE variable does not have to be updated in lockstep.
DEFAULT_USE_CHROMIUM = True
DEFAULT_TZONE = "Europe/Berlin"
DEFAULT_GEOLOC = (52.520008, 13.404954)  # Berlin
DEFAULT_LANG = "de-DE"
# Silent AWS-WAF / anti-bot challenges auto-clear a few seconds after load
# (the challenge JS reloads the page once it issues a token). Wait for that
# before declaring bot detection — the initial page source is often the shim.
DEFAULT_INITIAL_WAIT = 8


def _sb_setting(name: str, default):
    """Read a value from config.seleniumbase, falling back to `default` when the
    (possibly older) deployed config.json does not define it."""
    return getattr(config.seleniumbase, name, default)


def _try_solve_captcha(sb) -> str | None:
    """Best-effort click/solve of a captcha widget. seleniumbase's solver only
    handles Cloudflare Turnstile + Google reCAPTCHA (NOT AWS WAF's interactive
    puzzle), so this is a no-op against immoscout's WAF captcha — kept only for
    immowelt / other sites that may surface a solvable challenge. Returns the
    method name used, or None."""
    for name in ("solve_captcha", "gui_click_captcha", "uc_gui_click_captcha"):
        fn = getattr(sb, name, None)
        if callable(fn):
            try:
                fn()
                return name
            except Exception as e:  # method may not apply to this captcha type
                logger.info(f"{name}() did not apply: {e}")
    return None


def _build_chrome_kwargs(proxy_url: str | None) -> dict:
    """Assemble the sb_cdp.Chrome() kwargs from config with hard-case defaults."""
    kwargs: dict = {
        "incognito": _sb_setting("incognito", True),
        "lang": _sb_setting("lang", _sb_setting("locale", DEFAULT_LANG)),
    }
    # Unbranded Chromium (mdmintz: most stealthy for the hardest cases).
    if _sb_setting("use_chromium", DEFAULT_USE_CHROMIUM):
        kwargs["use_chromium"] = True
    # Timezone + geolocation to match the exit IP.
    tzone = _sb_setting("tzone", DEFAULT_TZONE)
    if tzone:
        kwargs["tzone"] = tzone
    geoloc = _sb_setting("geoloc", DEFAULT_GEOLOC)
    if geoloc:
        # config.json parses arrays into lists; start() accepts list | tuple.
        kwargs["geoloc"] = tuple(geoloc) if isinstance(geoloc, (list, tuple)) else geoloc
    # Headed under a virtual display on Linux (CDP mode needs a real display;
    # headless is far less stealthy). Ignored on non-Linux.
    if _sb_setting("xvfb", True):
        kwargs["xvfb"] = True
    if proxy_url:
        # Pure CDP expects "host:port" or "user:pass@host:port" (no scheme).
        kwargs["proxy"] = proxy_url.split("://", 1)[-1]
    return kwargs


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
    screenshot_path: str | None = None,
) -> str:
    """Fetch a page with Pure CDP Mode (undetected Chromium) and return its HTML.

    On a suspected bot/captcha page it waits + reloads (and best-effort solves)
    up to BOT_SOLVE_ATTEMPTS times, then os._exit(42) so the workflow re-dispatches
    on a fresh runner IP. `screenshot_path`, when given, saves a PNG of the final
    page — used by the tools.fetch_url test harness (no overhead in production).
    """
    timeout = timeout if timeout is not None else config.seleniumbase.timeout
    initial_wait = _sb_setting("initial_wait", DEFAULT_INITIAL_WAIT)
    chrome_kwargs = _build_chrome_kwargs(proxy_url)

    sb = None
    try:
        sb = sb_cdp.Chrome(url, **chrome_kwargs)
        sb.sleep(initial_wait)  # let a silent WAF challenge issue its token + reload
        html = sb.get_page_source()

        if has_bot_detection(html):
            # Try to clear the challenge. Each cycle: best-effort solve, wait for
            # the WAF token / auto-reload, and if still blocked, reload + re-check.
            for solve_attempt in range(1, BOT_SOLVE_ATTEMPTS + 1):
                logger.info(
                    f"Bot detection suspected, attempting to clear "
                    f"(attempt {solve_attempt}/{BOT_SOLVE_ATTEMPTS})..."
                )
                used = _try_solve_captcha(sb)
                sb.sleep(8)  # give the challenge time to issue a token / redirect
                html = sb.get_page_source()
                if not has_bot_detection(html):
                    logger.info(
                        f"Bot detection cleared after attempt {solve_attempt} "
                        f"(method: {used or 'wait-only'})."
                    )
                    break

                sb.reload(ignore_cache=True)
                sb.sleep(4)
                html = sb.get_page_source()
                if not has_bot_detection(html):
                    logger.info(f"Bot detection cleared after reload (attempt {solve_attempt}).")
                    break
            else:
                if screenshot_path:
                    _save_screenshot(sb, screenshot_path)
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

        if screenshot_path:
            _save_screenshot(sb, screenshot_path)
        return html
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch {url} with SeleniumBase: {e}")
        raise RuntimeError(f"Failed to fetch {url} with SeleniumBase: {e}")
    finally:
        if sb is not None:
            try:
                sb.quit()
            except Exception:
                pass


def _save_screenshot(sb, path: str) -> None:
    folder = os.path.dirname(path) or "."
    name = os.path.basename(path)
    try:
        os.makedirs(folder, exist_ok=True)
        sb.save_screenshot(name, folder=folder)
        logger.info(f"Saved screenshot to {os.path.join(folder, name)}")
    except Exception as e:
        logger.info(f"Could not save screenshot: {e}")


# test fetch
if __name__ == "__main__":
    test_url = "https://www.immobilienscout24.de/expose/166611357"
    html = get_html_seleniumbase(test_url)
    print(f"Fetched {len(html)} characters from {test_url}")
