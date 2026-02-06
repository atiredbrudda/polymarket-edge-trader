"""Logging configuration using Loguru with rotation and compression."""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    """Configure Loguru logging with console and rotating file handlers.

    Features:
    - Console output with colored, formatted messages
    - Rotating file logs (50 MB per file, keep last 10, compress to zip)
    - Debug-level file logs, configurable console level

    Args:
        level: Logging level for console output (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files (created if doesn't exist)
    """
    # Remove default handler
    logger.remove()

    # Add console handler with custom format
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        level=level,
        colorize=True,
    )

    # Create log directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Add file handler with rotation and compression
    logger.add(
        log_path / "polymarket_{time:YYYY-MM-DD}.log",
        rotation="50 MB",
        retention=10,
        compression="zip",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )

    logger.info(f"Logging configured: console={level}, file=DEBUG, dir={log_dir}")
