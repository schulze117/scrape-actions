from lib.logger import get_logger

logger = get_logger("helpers")


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