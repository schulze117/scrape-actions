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
