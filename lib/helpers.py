from lib.logger import get_logger

logger = get_logger("helpers")

BOT_DETECTION_CHAR_THRESHOLD = 10_000


def has_bot_detection(html: str, threshold: int = BOT_DETECTION_CHAR_THRESHOLD) -> bool:
    """
    Return True if the HTML is suspiciously short, indicating a bot/captcha
    verification page was served instead of real content.

    Normal pages range from ~200K to 3M+ characters.
    Bot detection pages are typically under 5K characters.
    A threshold of 10K gives a safe margin for both.
    """
    html_len = len(html)
    if html_len < threshold:
        logger.info(f"Bot detection suspected: HTML length {html_len} is below threshold {threshold}")
        return True
    return False
