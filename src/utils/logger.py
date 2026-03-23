"""Logging configuration for PRAS.

Uses Python's built-in logging module as required by the course.
"""

import logging
import sys


def setup_logger(
    name: str = "pras",
    level: int = logging.INFO,
    log_file: str | None = None,
) -> logging.Logger:
    """Configure and return a logger instance.

    Args:
        name: Logger name (default: "pras")
        level: Logging level (default: INFO)
        log_file: Optional file path for logging to file

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


logger = setup_logger()
