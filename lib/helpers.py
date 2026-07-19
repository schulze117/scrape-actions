from lib.logger import get_logger

logger = get_logger("helpers")

BOT_DETECTION_CHAR_THRESHOLD = 10_000

# High-confidence markers of a bot/captcha block page. These are specific to the
# challenge pages (AWS WAF / Imperva, Cloudflare, DataDome/PerimeterX, Google) and
# do NOT appear on real listing content, so they are safe from false positives.
# Needed because a *rendered* interactive captcha page (e.g. immoscout's AWS WAF
# image puzzle) balloons past the length threshold and would otherwise slip through.
BOT_DETECTION_MARKERS = (
    "captcha-sdk.awswaf.com",   # AWS WAF captcha SDK (immoscout)
    "sdk.awswaf.com",           # AWS WAF challenge SDK
    "awswafcaptcha",            # <awswaf-captcha> widget / AwsWafCaptcha API
    "ich bin kein roboter",     # immoscout AWS WAF block-page title
    "/challenge-platform/",     # Cloudflare challenge
    "just a moment...",         # Cloudflare interstitial title
    "px-captcha",               # PerimeterX
    "datadome",                 # DataDome
)


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
