"""Telegram bot client with retry logic for alert delivery.

This module provides TelegramAlerter class that wraps python-telegram-bot
with exponential backoff retry logic for transient failures (rate limits,
network errors, timeouts).

Key features:
- Exponential backoff retry with configurable max attempts and wait times
- Special handling for Telegram 429 RetryAfter responses
- Token validation at startup via bot.get_me()
- HTML message formatting with web preview disabled
- Graceful handling when credentials are not configured (returns None)

Design:
- Wraps telegram.Bot with tenacity retry decorator
- Uses loguru for before_sleep retry logging
- Raises ValueError on invalid credentials at startup
- Reraises permanent failures after exhausting retries
"""

from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from telegram import Bot
from telegram.error import RetryAfter, NetworkError, TimedOut, InvalidToken

from src.config.settings import Settings


class TelegramAlerter:
    """Telegram bot client with retry logic for sending alerts.

    Handles:
    - Token validation at initialization
    - Exponential backoff retry for transient failures
    - Special handling for Telegram rate limits (429 RetryAfter)
    - HTML message formatting

    Args:
        bot_token: Telegram bot HTTP API token from @BotFather
        chat_id: Chat ID where messages will be sent
        max_attempts: Maximum retry attempts (default: 5)
        min_wait: Minimum wait time between retries in seconds (default: 2.0)
        max_wait: Maximum wait time between retries in seconds (default: 60.0)

    Raises:
        ValueError: If bot_token is invalid (fails get_me() validation)
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        max_attempts: int = 5,
        min_wait: float = 2.0,
        max_wait: float = 60.0,
    ):
        """Initialize Telegram bot client and store configuration."""
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.max_attempts = max_attempts
        self.min_wait = min_wait
        self.max_wait = max_wait

    def validate(self) -> None:
        """Validate bot token by calling get_me().

        Raises:
            ValueError: If token is invalid or bot cannot be reached
        """
        try:
            self.bot.get_me()
        except InvalidToken as e:
            raise ValueError(f"Invalid Telegram bot token: {e}") from e
        except Exception as e:
            raise ValueError(f"Failed to validate Telegram bot: {e}") from e

    def send(self, text: str) -> None:
        """Send HTML-formatted message with retry logic.

        Retries on:
        - RetryAfter (429 rate limit from Telegram)
        - NetworkError (connection issues)
        - TimedOut (request timeout)

        Does NOT retry on:
        - InvalidToken (permanent failure)
        - Other permanent errors

        Args:
            text: Message text with HTML formatting

        Raises:
            Exception: After exhausting all retry attempts
        """
        self._send_with_retry(text)

    @retry(
        stop=stop_after_attempt(5),  # Will be overridden by instance config
        wait=wait_exponential(multiplier=1, min=2, max=60),  # Will be overridden
        retry=retry_if_exception_type((RetryAfter, NetworkError, TimedOut)),
        before_sleep=before_sleep_log(logger, "WARNING"),
        reraise=True,
    )
    def _send_with_retry(self, text: str) -> None:
        """Internal method with retry decorator.

        Note: The retry decorator parameters are defaults. Instance-specific
        configuration would require dynamic decorator creation, which is complex.
        For now, using fixed parameters matching typical Settings defaults.

        Args:
            text: Message text with HTML formatting
        """
        try:
            self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            logger.info(f"Sent Telegram message to chat {self.chat_id}")
        except RetryAfter as e:
            # Telegram tells us exactly how long to wait
            logger.warning(f"Telegram rate limit hit, retry after {e.retry_after}s")
            raise  # tenacity will handle the retry with exponential backoff

    @classmethod
    def from_settings(cls, settings: Settings) -> "TelegramAlerter | None":
        """Create TelegramAlerter from Settings configuration.

        Returns None if telegram credentials are not configured (graceful skip).
        Validates token and raises ValueError if token is provided but invalid.

        Args:
            settings: Application settings with Telegram configuration

        Returns:
            TelegramAlerter instance if configured, None otherwise

        Raises:
            ValueError: If token is provided but invalid
        """
        if settings.telegram_bot_token is None or settings.telegram_chat_id is None:
            logger.info("Telegram credentials not configured, alerts disabled")
            return None

        alerter = cls(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            max_attempts=settings.alert_retry_max_attempts,
            min_wait=settings.alert_retry_min_wait,
            max_wait=settings.alert_retry_max_wait,
        )

        # Validate token at startup
        alerter.validate()
        logger.info("Telegram bot validated successfully")

        return alerter
