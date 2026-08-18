import random
import re

from lib.logger import get_logger

logger = get_logger("helpers")

BOT_DETECTION_CHAR_THRESHOLD = 10_000

# High-confidence markers of a bot/captcha BLOCK page. These must appear ONLY on
# the challenge page, never on real content — otherwise they'd false-positive.
# (Deliberately excludes generic vendor tokens like "datadome"/"px-captcha":
# those load on normal pages of sites that use them, so they aren't block-only.)
# Needed because a *rendered* interactive captcha page (e.g. immoscout's AWS WAF
# image puzzle) balloons past the length threshold and would otherwise slip through.
#
# These are page *text*, not script includes. The awswaf SDK <script> tags used
# to be listed here and turned out not to be block-only: immoscout embeds the
# WAF SDK on real search pages too (to refresh its token), so a fully-loaded
# 842K result page was being rejected as a block page — the finder fetched real
# listings and threw them away. The block page, silent or interactive, always
# carries the title/heading below.
BOT_DETECTION_MARKERS = (
    "ich bin kein roboter",     # immoscout AWS WAF block-page title (both tiers)
    "gleich geht",              # "Gleich geht's weiter" — silent WAF interstitial
    "just a moment...",         # Cloudflare interstitial title (block-only)
)

# Chromium's built-in network-error page ("This site can't be reached"). It is
# ~186K of inlined CSS/JS, so it sails past the bot-detection length check, and
# it carries none of the block-page markers — it looked to us exactly like a
# real page whose parse failed. That is how a dead proxy tunnel masqueraded as
# "immoscout changed their HTML" for two days in August 2026. Detecting it is
# what separates "we could not reach the site" from "the site blocked us".
_NETWORK_ERROR_RE = re.compile(r"\bERR_[A-Z0-9_]{3,}\b")
_CHROME_ERROR_MARKER = "the chromium authors"


_PORT_RANGE_RE = re.compile(r":(\d+)-(\d+)(/?)$")


def expand_proxy_url(proxy_url: str) -> str:
    """Resolve a `host:START-END` port range down to one randomly picked port.

    Residential providers (DataImpulse here) map each port in a range to an
    independent *sticky* session — one exit IP, held for the life of the session
    — while the base port rotates the IP on every single request. Rotation is
    fatal against AWS WAF: the challenge issues a token bound to the client IP,
    so if the token request and the retry leave via different IPs the token
    never validates and the page loops through the interstitial forever.

    Picking one port per process gives each run a fresh IP that then stays put
    for the whole run, which is what the challenge needs to clear. A plain
    `host:port` is returned unchanged.
    """
    match = _PORT_RANGE_RE.search(proxy_url)
    if not match:
        return proxy_url
    start, end = int(match.group(1)), int(match.group(2))
    if start > end:
        start, end = end, start
    port = random.randint(start, end)
    expanded = proxy_url[: match.start()] + f":{port}" + match.group(3)
    logger.info(f"Proxy sticky session: port {port} (from range {start}-{end})")
    return expanded


def redact_proxy(proxy_url: str) -> str:
    """Strip proxy credentials before logging. This repo is public — Action logs
    must never carry the user:pass part of a proxy string."""
    host = proxy_url.rsplit("@", 1)[-1]
    return f"***@{host}" if "@" in proxy_url else host


def has_bot_detection(html: str, threshold: int = BOT_DETECTION_CHAR_THRESHOLD) -> bool:
    """
    Return True if the HTML looks like a bot/captcha verification page instead of
    real content.

    Two independent signals:
    1. Suspiciously short HTML (silent challenge shims are typically <5K chars;
       normal pages are ~200K–3M+). A 10K threshold gives a safe margin.
    2. Known anti-bot block-page markers (see BOT_DETECTION_MARKERS) — catches
       *rendered* interactive captcha pages that exceed the length threshold.
    """
    html_len = len(html)
    if html_len < threshold:
        logger.info(f"Bot detection suspected: HTML length {html_len} is below threshold {threshold}")
        return True

    lowered = html.lower()
    for marker in BOT_DETECTION_MARKERS:
        if marker in lowered:
            logger.info(f"Bot detection suspected: block-page marker '{marker}' found (len {html_len})")
            return True

    return False


def get_network_error(html: str) -> str | None:
    """Return the Chromium error code if `html` is the browser's error page.

    A failed navigation still yields a large, well-formed document, so this must
    be checked explicitly — neither the length threshold nor the block-page
    markers catch it. Returns e.g. "ERR_TUNNEL_CONNECTION_FAILED" (proxy could
    not reach the host) or None when the page is real content.
    """
    if _CHROME_ERROR_MARKER not in html[:400_000].lower():
        return None
    match = _NETWORK_ERROR_RE.search(html)
    return match.group(0) if match else "ERR_UNKNOWN"
