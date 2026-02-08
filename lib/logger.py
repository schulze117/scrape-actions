import logging
from lib.config import get_config

LEVEL_MAPPING = {"DEBUG": "DEBG", "INFO": "INFO", "WARNING": "WARN", "ERROR": "ERRO", "CRITICAL": "CRIT"}


class LogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.levelname = LEVEL_MAPPING.get(record.levelname, record.levelname[:4])

        if hasattr(record, "id") and getattr(record, "id", None):
            self._style._fmt = "%(asctime)s - %(levelname)s - %(name)s (%(id)s) - %(message)s"
        else:
            self._style._fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

        return super().format(record)


def get_logger(name: str, loglevel: str = None) -> logging.Logger:
    config = get_config()
    # Use config.log_level if not provided
    loglevel = loglevel or getattr(config, "log_level", "INFO")
    logger = logging.getLogger(name)

    if not logger.hasHandlers():
        logger.setLevel(logging.DEBUG)
        datefmt = "%Y-%m-%d %H:%M:%S"
        formatter = LogFormatter(datefmt=datefmt)

        sh = logging.StreamHandler()
        sh.setLevel(loglevel.upper())
        sh.setFormatter(formatter)
        logger.addHandler(sh)

        # fh = logging.FileHandler(f"{name}.log", mode="a", encoding="utf-8")
        # fh.setLevel(logging.DEBUG)
        # fh.setFormatter(formatter)
        # logger.addHandler(fh)

    return logger
