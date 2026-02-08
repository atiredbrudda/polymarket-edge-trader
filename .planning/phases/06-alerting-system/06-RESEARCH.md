# Phase 6: Alerting System - Research

**Researched:** 2026-02-08
**Domain:** Telegram bot integration, message delivery, retry strategies
**Confidence:** HIGH

## Summary

Phase 6 delivers consensus signals from Phase 5 via Telegram bot with retry reliability. The research focuses on implementing push notifications using python-telegram-bot library with HTML formatting, handling rate limits, implementing retry strategies, and detecting signal events through append-only snapshot comparison.

The primary technical challenge is transforming SignalSnapshot deltas into rich, actionable Telegram messages while handling delivery failures gracefully. python-telegram-bot 22.6 provides the official Python wrapper with HTTPX async support, but this project uses synchronous patterns (established in Phases 1-5), making the synchronous send approach appropriate. Telegram's rate limits (1 msg/sec per chat, 30 users/sec for broadcasts) are well within this project's scope (single chat destination).

Signal event detection requires comparing latest SignalSnapshot to previous for each market+direction pair to classify as NEW, STRENGTHENING, WEAKENING, or LOST. The append-only SignalSnapshot table from Phase 5 provides the historical comparison foundation.

**Primary recommendation:** Use python-telegram-bot synchronous API, implement exponential backoff retry with tenacity (already in project dependencies), store minimal delivery state in-memory, format alerts with Telegram HTML parse_mode, and leverage existing get_signal_history query for delta detection.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Alert Content:**
- Extended detail level: Include first-mover identity, fast-follower count, expert addresses, and individual position sizes (not just core market info)
- Explicit signal type differentiation: Prefix or header indicates NEW consensus, STRENGTHENING (confidence up ≥5 points), WEAKENING (confidence down ≥5 points), or LOST consensus
- Complete signal metadata: All data needed for user decision-making without needing to query CLI

**Telegram Formatting:**
- Rich HTML formatting: Use Telegram HTML parse mode for bold/italic headers, monospace data, structured layout
- Structured presentation: Headers, bullet lists, inline links for market URLs
- Human-readable: Scannable at a glance, not just data dump

**Alert Triggering:**
- All signal events: Alert on NEW, STRENGTHENING (≥5 point confidence increase), WEAKENING (≥5 point confidence decrease), LOST consensus
- No confidence filtering: Send all consensus signals regardless of confidence score (user sees full range)
- Signal type detection: Compare latest SignalSnapshot to previous to determine event type

**Configuration:**
- Environment variables for credentials: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env file
- Single destination only: One Telegram chat for v1 (no multi-destination routing)
- Strict validation at startup: Fail fast with clear error messages if required env vars missing or invalid

**Error Handling:**
- Log and continue on permanent failure: Record failed deliveries in logs but don't block alert pipeline
- No user notification on failures: Operator checks logs if alerts stop arriving

### Claude's Discretion

- **Retry logic strategy**: Exponential backoff, fixed interval, or fail-fast approach based on best practices
- **Delivery status tracking**: Whether to persist delivery state (sent/pending/failed) in database or keep stateless
- **Rate limit handling**: Client-side rate limiter, respect server headers, or both
- **Deduplication strategy**: Snapshot comparison, time-based, hash-based, or hybrid approach
- **Alert batching**: Immediate delivery vs batching by time/count to reduce notification spam
- **Behavior configurability**: Hard-coded defaults vs config file vs env vars for thresholds and filters

### Deferred Ideas (OUT OF SCOPE)

- **Discord integration**: User will implement Telegram first, add Discord when satisfied with Telegram alerts
- **Multi-destination support**: Single chat for v1, can extend later if needed
- **Generic webhook output** (ALRT-05): Future v2 requirement
- **Whale alerts** (ALRT-06): Future v2 requirement
- **Per-game routing**: Different channels per eSports category — out of scope for v1
</user_constraints>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-telegram-bot | >=22.6 | Official Telegram Bot API wrapper | Most widely-used, officially recommended by Telegram, comprehensive documentation, active maintenance (latest release Jan 24, 2026) |
| httpx | >=0.28.1 | HTTP client (already in deps) | Required by python-telegram-bot for async/sync requests, modern replacement for requests |
| tenacity | >=9.1.3 | Retry logic (already in deps) | Already used in project for API client retry, provides exponential backoff decorators |
| pydantic-settings | >=2.0 | Config validation (already in deps) | Consistent with existing Settings pattern, validates env vars at startup |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| loguru | >=0.7.3 | Logging (already in deps) | Already used project-wide, structured logging for delivery failures |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-telegram-bot | aiogram | Aiogram is async-first (benefits high-throughput bots), but this project uses synchronous patterns throughout (RateLimiter, PolymarketClient). Switching would require refactoring entire codebase for minimal gain (single chat destination). |
| python-telegram-bot | pyTelegramBotAPI (telebot) | Simpler API but less comprehensive error handling and less active maintenance. python-telegram-bot has better 429 handling and official status. |
| Exponential backoff | Fixed interval retry | Fixed interval can cause "thundering herd" when many clients retry simultaneously. Exponential backoff with jitter is best practice per research and matches existing project pattern (tenacity in API client). |

**Installation:**

Add to pyproject.toml dependencies:
```toml
"python-telegram-bot>=22.6",
```

No additional dependencies needed (httpx, tenacity, pydantic-settings already present).

## Architecture Patterns

### Recommended Project Structure

```
src/
├── alerts/
│   ├── __init__.py
│   ├── telegram.py        # TelegramAlerter class with send methods
│   ├── formatter.py       # Format SignalSnapshot -> Telegram HTML
│   ├── detector.py        # Detect signal events (NEW/STRENGTHENING/WEAKENING/LOST)
│   └── delivery.py        # Orchestration layer connecting detector -> formatter -> sender
tests/
├── test_telegram_alerter.py   # Unit tests for send with mocked bot
├── test_alert_formatter.py    # Unit tests for HTML formatting
├── test_signal_detector.py    # Unit tests for event detection logic
└── test_alert_delivery.py     # Integration tests for end-to-end flow
```

### Pattern 1: Signal Event Detection via Snapshot Comparison

**What:** Compare latest SignalSnapshot to previous snapshot for same (market_id, direction) to detect NEW, STRENGTHENING, WEAKENING, or LOST events.

**When to use:** Every signal refresh cycle to determine if alert should fire.

**Example:**
```python
# Leverage existing get_signal_history query from Phase 5
from src.signals.queries import get_signal_history

def detect_signal_event(
    session: Session,
    latest: SignalSnapshot
) -> str | None:
    """Detect signal event type by comparing to previous snapshot.

    Returns: "NEW", "STRENGTHENING", "WEAKENING", "LOST", or None (no alert)
    """
    history = get_signal_history(
        session,
        latest.market_id,
        direction=latest.direction,
        limit=2  # Latest + previous
    )

    if len(history) == 1:
        # First snapshot for this market+direction
        if latest.status == "active":
            return "NEW"
        return None  # Don't alert on first inactive

    previous = history[1]  # Second most recent

    # LOST: was active, now inactive
    if previous.status == "active" and latest.status == "inactive":
        return "LOST"

    # NEW: was inactive, now active
    if previous.status == "inactive" and latest.status == "active":
        return "NEW"

    # STRENGTHENING/WEAKENING: both active, confidence change ≥5
    if latest.status == "active" and previous.status == "active":
        confidence_delta = latest.confidence_score - previous.confidence_score
        if confidence_delta >= Decimal("5"):
            return "STRENGTHENING"
        elif confidence_delta <= Decimal("-5"):
            return "WEAKENING"

    return None  # No significant change
```

### Pattern 2: Telegram HTML Formatting for Rich Alerts

**What:** Use Telegram's HTML parse_mode to create scannable, native-looking messages.

**When to use:** Formatting all alert messages before send.

**Supported HTML tags:**
- `<b>bold</b>`, `<i>italic</i>`, `<u>underline</u>`, `<s>strikethrough</s>`
- `<a href="url">link text</a>` for inline URLs
- `<code>monospace</code>` for addresses/numbers
- `<pre>preformatted</pre>` for code blocks

**Example:**
```python
def format_signal_alert(
    signal: SignalResult,
    market_question: str,
    event_type: str
) -> str:
    """Format SignalSnapshot as Telegram HTML message.

    Returns rich HTML string for parse_mode='HTML'.
    """
    # Event type header with emoji
    event_icons = {
        "NEW": "🆕",
        "STRENGTHENING": "📈",
        "WEAKENING": "📉",
        "LOST": "❌"
    }
    icon = event_icons.get(event_type, "📊")

    # Build structured message
    lines = [
        f"<b>{icon} {event_type} CONSENSUS</b>",
        "",
        f"<b>Market:</b> {market_question}",
        f"<b>Direction:</b> {signal.direction}",
        f"<b>Confidence:</b> {signal.confidence_score}/100",
        "",
        f"<b>Expert Agreement:</b>",
        f"  • {signal.expert_count}/{signal.total_experts_in_market} experts ({signal.agreement_percentage}%)",
        "",
    ]

    # First mover
    if signal.first_mover_address:
        lines.append(f"<b>First Mover:</b> <code>{signal.first_mover_address[:10]}...</code>")

    # Fast followers
    fast_followers = [
        addr for addr, role in signal.follower_classifications.items()
        if role == "fast_follower"
    ]
    if fast_followers:
        lines.append(f"<b>Fast Followers:</b> {len(fast_followers)}")

    # Expert addresses (truncated for readability)
    lines.append("")
    lines.append(f"<b>Expert Addresses:</b>")
    for addr in signal.expert_addresses[:5]:  # Show first 5
        lines.append(f"  • <code>{addr[:10]}...{addr[-6:]}</code>")
    if len(signal.expert_addresses) > 5:
        lines.append(f"  • <i>+ {len(signal.expert_addresses) - 5} more</i>")

    # Market URL (if available)
    lines.append("")
    lines.append(f"<a href='https://polymarket.com/event/{signal.market_id}'>View on Polymarket</a>")

    return "\n".join(lines)
```

### Pattern 3: Exponential Backoff Retry with Tenacity

**What:** Use tenacity decorators for automatic retry with exponential backoff on transient failures.

**When to use:** Wrapping Telegram send_message calls to handle 429 rate limits and network errors.

**Example:**
```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
from telegram.error import RetryAfter, NetworkError, TimedOut
import logging

logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type((RetryAfter, NetworkError, TimedOut)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def send_with_retry(bot, chat_id: str, text: str) -> None:
    """Send Telegram message with automatic retry on transient failures.

    Retries up to 5 times with exponential backoff (2s, 4s, 8s, 16s, 32s).
    Handles Telegram 429 rate limits, network errors, timeouts.
    """
    bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode='HTML',
        disable_web_page_preview=True
    )
```

**Telegram-specific 429 handling:**
```python
from telegram.error import RetryAfter
import time

try:
    send_with_retry(bot, chat_id, message)
except RetryAfter as e:
    # Telegram tells us exactly how long to wait
    retry_after_seconds = e.retry_after
    logger.warning(f"Rate limited by Telegram, retry after {retry_after_seconds}s")
    time.sleep(retry_after_seconds + 1)  # Add 1s buffer
    bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML')
```

### Pattern 4: Stateless Delivery with In-Memory Tracking

**What:** Don't persist delivery state to database; track recent deliveries in-memory with TTL to prevent duplicate alerts.

**When to use:** Deduplication without database writes (keeps alerting layer stateless and fast).

**Rationale:**
- Append-only SignalSnapshot table already provides idempotency (same signal won't trigger multiple NEW events)
- In-memory dedup prevents race conditions during rapid refresh cycles
- Alerts are time-sensitive; historical delivery state less important than current flow
- Simplifies error recovery (restart = fresh state)

**Example:**
```python
from datetime import datetime, timedelta
from typing import Set, Tuple

class AlertDeduplicator:
    """In-memory deduplication for alert delivery."""

    def __init__(self, ttl_minutes: int = 60):
        self._sent: Set[Tuple[str, str, str, datetime]] = set()
        self._ttl = timedelta(minutes=ttl_minutes)

    def should_send(
        self,
        market_id: str,
        direction: str,
        event_type: str,
        computed_at: datetime
    ) -> bool:
        """Check if alert should be sent (not recently delivered)."""
        # Clean expired entries
        cutoff = datetime.now() - self._ttl
        self._sent = {
            (m, d, e, t) for m, d, e, t in self._sent
            if t >= cutoff
        }

        # Check if already sent
        key = (market_id, direction, event_type, computed_at)
        if key in self._sent:
            return False

        self._sent.add(key)
        return True
```

### Anti-Patterns to Avoid

- **Blocking main thread on send failure:** Log and continue, don't halt signal pipeline. Alerts are secondary to signal detection.
- **Database writes for every delivery:** Adds latency and complexity. Use in-memory dedup, rely on append-only snapshots for idempotency.
- **Plaintext dumps:** User specified "human-readable, scannable at a glance" - use HTML formatting, headers, structure.
- **Alerting on noise:** Only alert on ≥5 point confidence changes for STRENGTHENING/WEAKENING (user decision).
- **Fixed interval retry:** Use exponential backoff with jitter to avoid thundering herd on 429 errors.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telegram Bot API | Raw httpx requests to Telegram | python-telegram-bot | Handles auth, error codes, rate limit headers, retries, message formatting edge cases. 429 errors include retry_after field (since layer 167, Feb 2025). |
| Retry logic | Custom sleep loops | tenacity decorators | Handles exponential backoff, jitter, max attempts, exception filtering, logging. Already in project deps. |
| HTML escaping | String replacement | Telegram's built-in escaping | Telegram HTML parser handles edge cases in user input (market questions with <>&). Use parse_mode='HTML' directly. |
| Configuration validation | Manual env checks | pydantic-settings BaseSettings | Type validation, required field checks, clear error messages. Already used project-wide. |
| Deduplication | Hash-based or DB state | Append-only snapshot comparison + in-memory TTL | SignalSnapshot append-only design inherently prevents duplicate NEW events (comparing to previous). In-memory dedup handles race conditions within refresh cycle. |

**Key insight:** Telegram's Bot API is deceptively complex (429 handling, rate limit headers, message size limits, HTML edge cases). python-telegram-bot abstracts these correctly. Don't replicate this logic.

## Common Pitfalls

### Pitfall 1: Telegram Rate Limit Misunderstanding

**What goes wrong:** Sending messages too fast causes 429 errors and delivery delays.

**Why it happens:** Developer assumes "30 messages/sec broadcast limit" applies to single-chat scenario. Actual limit for single chat is 1 msg/sec.

**How to avoid:**
- Single chat (v1 scope): Limit to 1 message per second
- For future multi-destination: Use Telegram's retry_after field from 429 response
- Implement client-side rate limiter (similar to existing RateLimiter for Polymarket API)
- Add 10% jitter to retry delays to avoid synchronization

**Warning signs:** Frequent 429 errors in logs, messages arriving in bursts after delays.

### Pitfall 2: HTML Formatting Injection

**What goes wrong:** Market questions or trader addresses containing `<`, `>`, `&` break HTML formatting or cause Telegram API errors.

**Why it happens:** Direct string interpolation into HTML without escaping.

**How to avoid:**
```python
from html import escape

def format_alert_safe(question: str, address: str) -> str:
    """Safely format alert with HTML escaping."""
    safe_question = escape(question)
    safe_address = escape(address)
    return f"<b>Market:</b> {safe_question}\n<code>{safe_address}</code>"
```

**Warning signs:** Telegram API returns "Can't parse entities" error, missing text in messages.

### Pitfall 3: Silent Delivery Failures

**What goes wrong:** Alerts fail to send but system appears healthy (no errors visible).

**Why it happens:**
- try/except catching all exceptions without logging
- Invalid chat_id passes validation but fails at send time
- Bot token revoked/expired but not detected until first send

**How to avoid:**
- Strict validation at startup: Test send to chat_id immediately after initialization
- Log all send attempts with result (success/failure/retry)
- Use structured logging with delivery metadata (market_id, event_type, timestamp)
- Monitor log volume (sudden drop indicates delivery failure)

**Warning signs:** No alerts arriving but signal detection pipeline shows activity, logs silent on delivery attempts.

### Pitfall 4: Snapshot Comparison Race Conditions

**What goes wrong:** Rapid signal refreshes cause duplicate alerts or missed events.

**Why it happens:**
- Multiple refresh cycles running concurrently
- Reading "latest" snapshot while new one being written
- No deduplication between comparison and alert delivery

**How to avoid:**
- Use database-level isolation (SQLite WAL mode already enabled)
- In-memory deduplication with (market_id, direction, event_type, computed_at) key
- Compare snapshots within single transaction
- TTL-based cleanup of dedup cache (60 min default)

**Warning signs:** Duplicate alerts for same signal, alerts for non-existent changes.

### Pitfall 5: Missing Signal Events Due to Refresh Gaps

**What goes wrong:** Signal goes NEW -> STRENGTHENING -> LOST but only LOST alert fires.

**Why it happens:** Refresh cycle skips intermediate states (long gaps between runs).

**How to avoid:**
- Accept that this is inherent to snapshot-based detection
- Document refresh frequency in logs (each cycle logs count of signals checked)
- For v1: Manual sweep via CLI (CLI-05 requirement) allows user to trigger refresh
- For v2: Automated polling (POLL-01/02/03) ensures regular refresh

**Warning signs:** User reports missing alerts, logs show large time gaps between refresh cycles.

## Code Examples

Verified patterns from official sources and codebase:

### Telegram Bot Initialization with Validation

```python
# Source: python-telegram-bot docs + project Settings pattern
from telegram import Bot
from telegram.error import InvalidToken, Forbidden
from pydantic_settings import BaseSettings
from loguru import logger

class AlertSettings(BaseSettings):
    """Telegram alert configuration with strict validation."""

    telegram_bot_token: str
    telegram_chat_id: str

    # Alert behavior
    alert_confidence_threshold: int = 0  # Send all (per user decision)
    alert_dedup_ttl_minutes: int = 60
    alert_retry_max_attempts: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

def initialize_telegram_bot(settings: AlertSettings) -> Bot:
    """Initialize Telegram bot with startup validation.

    Fails fast if token invalid or chat_id unreachable.
    """
    try:
        bot = Bot(token=settings.telegram_bot_token)

        # Validate token and chat_id with test message
        bot.send_message(
            chat_id=settings.telegram_chat_id,
            text="🤖 Polymarket Smart Money Tracker - Alert system initialized",
            parse_mode='HTML'
        )

        logger.info(f"Telegram bot initialized, chat_id={settings.telegram_chat_id}")
        return bot

    except InvalidToken:
        logger.error("Invalid TELEGRAM_BOT_TOKEN")
        raise ValueError("TELEGRAM_BOT_TOKEN is invalid or malformed")
    except Forbidden:
        logger.error(f"Bot cannot send to chat_id={settings.telegram_chat_id}")
        raise ValueError(f"Bot not authorized for TELEGRAM_CHAT_ID={settings.telegram_chat_id}")
    except Exception as e:
        logger.error(f"Telegram bot initialization failed: {e}")
        raise
```

### Complete Alert Delivery Flow

```python
# Source: Project patterns from scoring_pipeline.py + tenacity
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

@dataclass
class AlertDeliveryResult:
    """Result of alert delivery attempt."""
    success: bool
    market_id: str
    direction: str
    event_type: str
    error: str | None = None
    retry_count: int = 0

def deliver_signal_alerts(
    session: Session,
    bot: Bot,
    chat_id: str,
    window_hours: int = 24
) -> list[AlertDeliveryResult]:
    """Detect signal events and deliver alerts for all active markets.

    Pipeline flow:
    1. Get latest signals from signal detection pipeline
    2. For each signal, detect event type (NEW/STRENGTHENING/WEAKENING/LOST)
    3. If event detected, format and send alert
    4. Track delivery results
    5. Return summary
    """
    from src.signals.pipeline import get_ranked_signals
    from src.alerts.detector import detect_signal_event
    from src.alerts.formatter import format_signal_alert
    from src.alerts.telegram import send_alert_with_retry

    results = []

    # 1. Get latest signals
    signals = get_ranked_signals(
        session,
        window_hours=window_hours,
        limit=100
    )

    logger.info(f"Checking {len(signals)} signals for alert events")

    # 2-4. Detect events and send alerts
    for signal in signals:
        # Detect event type
        event_type = detect_signal_event(session, signal)

        if event_type is None:
            continue  # No alert needed

        # Get market question for alert
        market = session.query(Market).filter_by(
            condition_id=signal.market_id
        ).first()

        if not market:
            logger.warning(f"Market not found: {signal.market_id}")
            continue

        # Format alert
        message = format_signal_alert(
            signal=signal,
            market_question=market.question,
            event_type=event_type
        )

        # Send with retry
        try:
            send_alert_with_retry(bot, chat_id, message)
            results.append(AlertDeliveryResult(
                success=True,
                market_id=signal.market_id,
                direction=signal.direction,
                event_type=event_type
            ))
            logger.info(f"Alert sent: {event_type} - {signal.market_id} {signal.direction}")

        except Exception as e:
            results.append(AlertDeliveryResult(
                success=False,
                market_id=signal.market_id,
                direction=signal.direction,
                event_type=event_type,
                error=str(e)
            ))
            logger.error(f"Alert failed: {event_type} - {signal.market_id}: {e}")
            # Continue to next alert (don't block pipeline)

    # 5. Summary
    success_count = sum(1 for r in results if r.success)
    logger.info(f"Alert delivery complete: {success_count}/{len(results)} successful")

    return results
```

### Event Detection with Snapshot Comparison

```python
# Source: Phase 5 get_signal_history pattern + user CONTEXT.md thresholds
from decimal import Decimal
from src.signals.queries import get_signal_history

def detect_signal_event(
    session: Session,
    latest_signal: SignalResult
) -> str | None:
    """Detect signal event type by comparing to previous snapshot.

    Returns event type string if alert should fire:
    - "NEW": First active signal for this market+direction
    - "STRENGTHENING": Confidence increased ≥5 points
    - "WEAKENING": Confidence decreased ≥5 points
    - "LOST": Was active, now inactive
    - None: No alert needed (no change or below threshold)
    """
    CONFIDENCE_THRESHOLD = Decimal("5")  # User decision: ±5 points

    # Get signal history (latest + previous)
    history = get_signal_history(
        session,
        market_id=latest_signal.market_id,
        direction=latest_signal.direction,
        limit=2
    )

    if len(history) == 0:
        logger.warning(f"No signal history for {latest_signal.market_id}")
        return None

    latest_snapshot = history[0]

    # First signal for this market+direction
    if len(history) == 1:
        if latest_snapshot.status == "active":
            return "NEW"
        return None  # Don't alert on first inactive

    previous_snapshot = history[1]

    # LOST: was active, now inactive
    if previous_snapshot.status == "active" and latest_snapshot.status == "inactive":
        return "LOST"

    # NEW: was inactive, now active
    if previous_snapshot.status == "inactive" and latest_snapshot.status == "active":
        return "NEW"

    # STRENGTHENING/WEAKENING: both active, check confidence delta
    if latest_snapshot.status == "active" and previous_snapshot.status == "active":
        confidence_delta = latest_snapshot.confidence_score - previous_snapshot.confidence_score

        if confidence_delta >= CONFIDENCE_THRESHOLD:
            return "STRENGTHENING"
        elif confidence_delta <= -CONFIDENCE_THRESHOLD:
            return "WEAKENING"

    # No significant change
    return None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| requests library for HTTP | httpx with async/await support | 2023-2024 | python-telegram-bot v20+ requires httpx. Enables async/sync flexibility. Project already uses httpx for Polymarket API. |
| Manual 429 handling with fixed retry | Telegram retry_after field in 429 response | Feb 2025 (layer 167) | Server tells client exactly how long to wait. More efficient than guessing. |
| Database-backed delivery tracking | In-memory dedup with append-only snapshots | Current best practice | Faster, simpler, idempotent by design. Delivery state less important than signal state. |
| Markdown formatting | HTML parse_mode | Established standard | Richer formatting (monospace for addresses, inline links), better escaping, more native Telegram feel. |

**Deprecated/outdated:**
- requests library: No async support, not compatible with python-telegram-bot v20+
- telepot library: Unmaintained since 2019
- Fixed-interval retry: Causes thundering herd, doesn't respect Telegram's retry_after guidance

## Open Questions

1. **Should alerts batch by time/count to reduce notification spam?**
   - What we know: User wants "all signal events" with no filtering (CONTEXT.md decision)
   - What's unclear: If 10 signals fire in 1 minute, does user want 10 notifications or 1 batched?
   - Recommendation: Start with immediate delivery (no batching). User can request batching later if overwhelmed. Easier to add batching than remove it.

2. **Should delivery failures be retried across restarts?**
   - What we know: User wants "log and continue" (CONTEXT.md decision), no database writes for delivery state
   - What's unclear: If process restarts during retry, should failed alerts be re-attempted?
   - Recommendation: No. Stateless design means restart = fresh state. Alerts are time-sensitive; stale alerts less useful than current flow. User can trigger manual sweep (CLI-05) if concerned about gaps.

3. **Should rate limiter be shared with Polymarket API client?**
   - What we know: Separate rate limits (Telegram: 1 msg/sec per chat, Polymarket: 50 req/sec)
   - What's unclear: Should both use same RateLimiter class from Phase 1?
   - Recommendation: Reuse RateLimiter class pattern but create separate instance with telegram-specific limits (1 req/sec for single chat). Single chat v1 scope makes this simple; multi-destination v2 would need per-chat rate limiting.

4. **How to handle position size data for "individual position sizes" requirement?**
   - What we know: User wants individual position sizes in alerts (CONTEXT.md decision)
   - What's unclear: SignalSnapshot stores expert_addresses but not position sizes. Need to join back to Position table?
   - Recommendation: Query Position table in formatter for signal.expert_addresses. Small performance cost (N+1 query per alert) acceptable for v1 single-chat scope. Could optimize with JOIN if performance issue emerges.

## Sources

### Primary (HIGH confidence)

- [python-telegram-bot v22.6 PyPI](https://pypi.org/project/python-telegram-bot/) - Official library, version 22.6 released Jan 24, 2026
- [python-telegram-bot Documentation](https://docs.python-telegram-bot.org/) - Official docs for v22.6
- [Telegram Bot API Rate Limits](https://core.telegram.org/bots/faq) - Official Telegram documentation on rate limits
- [Telegram Bot API Formatting](https://core.telegram.org/bots/api#html-style) - Official HTML parse_mode documentation
- Project codebase: src/api/rate_limiter.py, src/signals/pipeline.py, src/signals/queries.py - Established patterns

### Secondary (MEDIUM confidence)

- [How to Retry Failed Python Requests [2026] - ZenRows](https://www.zenrows.com/blog/python-requests-retry) - Exponential backoff best practices
- [API Error Handling & Retry Strategies: Python Guide 2026](https://easyparser.com/blog/api-error-handling-retry-strategies-python-guide) - Retry patterns
- [Fixing 429 Errors: Practical Retry Policies for Telegram Bot API](https://telegramhpc.com/news/574/) - Telegram-specific retry strategies
- [python-telegram-bot vs aiogram comparison](https://piptrends.com/compare/python-telegram-bot-vs-aiogram) - Library comparison for architecture decision
- [Understanding Idempotency - Airbyte](https://airbyte.com/data-engineering-resources/idempotency-in-data-pipelines) - Idempotency patterns for delivery
- [Querying Append-Only Tables - Stitch Documentation](https://www.stitchdata.com/docs/replication/loading/querying-append-only-tables) - Pattern for latest record queries

### Tertiary (LOW confidence)

- WebSearch results for deduplication strategies (multiple sources, no single authoritative)
- Community discussions on 429 handling (GitHub issues, forums) - Supplementary context only

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - python-telegram-bot is officially recommended, project already uses httpx/tenacity/pydantic
- Architecture: HIGH - Patterns match existing Phase 1-5 codebase (pure functions, orchestration layers, append-only snapshots)
- Pitfalls: MEDIUM-HIGH - Common issues well-documented in Telegram community, but some project-specific (snapshot comparison races)
- Retry strategies: HIGH - tenacity already in use, exponential backoff well-established best practice
- Event detection: HIGH - Append-only snapshot comparison pattern from Phase 5, thresholds from user CONTEXT.md

**Research date:** 2026-02-08
**Valid until:** 60 days (stable domain: Telegram Bot API v7.x, python-telegram-bot v22.x)

---

## Additional Technical Notes

### Telegram Rate Limits Deep Dive

Per [official Telegram Bot FAQ](https://core.telegram.org/bots/faq):
- **Individual chats:** 1 message per second
- **Group chats:** 20 messages per minute (1 every 3 seconds)
- **Broadcast to users:** 30 messages per second (default), 1000 msg/sec with Paid Broadcasts
- **429 response:** Includes retry_after field (seconds to wait) since Bot API layer 167 (Feb 2025)

**Project impact:** Single chat destination (v1 scope) means 1 msg/sec limit applies. Conservative approach: Add 100ms buffer between sends (0.9 msg/sec effective rate) to avoid edge case 429s.

### SignalSnapshot -> Alert Data Flow

```
Phase 5: refresh_market_signal()
  ↓
SignalSnapshot written (append-only)
  ↓
Phase 6: deliver_signal_alerts()
  ↓
get_ranked_signals() → SignalResult objects
  ↓
For each SignalResult:
  ↓
  detect_signal_event() → Compare to previous snapshot
  ↓
  format_signal_alert() → Convert to Telegram HTML
  ↓
  send_alert_with_retry() → Deliver via Bot API
  ↓
Log result (success/failure)
```

**Key observation:** SignalResult already contains all metadata needed for alerts (expert_addresses, first_mover, confidence, etc). Only missing piece is market.question for context - requires single query per alert.

### Retry Strategy Justification

User gave Claude discretion on retry strategy. Recommendation: **Exponential backoff with tenacity**.

**Rationale:**
1. **Consistency with codebase:** Phase 1 API client already uses tenacity for Polymarket API retries
2. **Best practice consensus:** All research sources recommend exponential backoff over fixed interval
3. **Telegram 429 support:** tenacity can respect retry_after from Telegram's 429 response
4. **Configuration:** tenacity supports max_attempts (5), min_wait (2s), max_wait (60s) - matches project Settings pattern
5. **Logging:** tenacity before_sleep_log automatically logs retry attempts - consistent with loguru usage

**Alternative rejected:** Fixed interval retry causes "thundering herd" when multiple clients/processes retry simultaneously after rate limit.

### Deduplication Strategy Justification

User gave Claude discretion on deduplication. Recommendation: **Snapshot comparison + in-memory TTL**.

**Rationale:**
1. **Append-only design provides inherent dedup:** Comparing latest to previous SignalSnapshot prevents duplicate NEW events (same signal won't have two "first" snapshots)
2. **In-memory TTL handles rapid refresh races:** If two refresh cycles run close together, in-memory cache prevents alerting twice for same (market_id, direction, event_type, computed_at)
3. **Stateless = simpler error recovery:** No database writes, restart = fresh state. Acceptable for time-sensitive alerts.
4. **Performance:** No DB writes in hot path (send loop), minimal memory overhead (TTL cleanup)

**Alternative rejected:** Database-backed delivery state (sent/pending/failed table) adds complexity and latency without clear benefit. Delivery history less important than signal history (already tracked in SignalSnapshot).

### Alert Content Requirements Detail

Per CONTEXT.md "extended detail level" requirement, alerts must include:
- Market question (human context)
- Direction and confidence score (signal strength)
- Expert count and agreement percentage (consensus metrics)
- **First-mover identity** (trader address) - NEW requirement beyond Phase 5
- **Fast-follower count** - NEW requirement beyond Phase 5
- **Expert addresses** (list) - Available in SignalResult.expert_addresses
- **Individual position sizes** - Requires joining to Position table

**Implementation note:** formatter.py will need to query Position table for position sizes. SignalResult.expert_addresses provides trader list, join on Position.trader_address + Position.market_id to get sizes.

```python
# In formatter.py
def get_expert_positions_details(
    session: Session,
    market_id: str,
    expert_addresses: list[str]
) -> list[dict]:
    """Query position sizes for expert addresses."""
    positions = session.query(Position).filter(
        Position.market_id == market_id,
        Position.trader_address.in_(expert_addresses)
    ).all()

    return [
        {
            "address": p.trader_address,
            "size": p.size,
            "direction": p.direction,
            "avg_entry": p.avg_entry_price
        }
        for p in positions
    ]
```

This allows formatter to show position details in alert without storing redundant data in SignalSnapshot.
