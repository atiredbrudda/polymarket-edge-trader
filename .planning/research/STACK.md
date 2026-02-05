# Technology Stack

**Project:** Polymarket eSports Smart Money Tracker
**Researched:** 2026-02-05
**Domain:** Prediction market analytics/intelligence tool
**Overall Confidence:** HIGH

---

## Executive Summary

The 2025-2026 Python stack for building Polymarket analytics tools has stabilized around modern, high-performance libraries. **Key recommendation: Use Python 3.10+ as the baseline**, enabling access to the latest features across all major dependencies (Polars, Pydantic, pytest, python-telegram-bot).

**Critical decision:** This project should use **Polars instead of pandas** for data analysis, given the performance benefits (3-10x faster) and the likelihood of processing thousands of market positions and trader histories.

---

## Recommended Core Stack

### Python Version
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **Python** | 3.10+ | Runtime environment | **REQUIRED:** Polars 1.38.0 requires >=3.10, python-telegram-bot 22.6 requires >=3.10, pytest 9.0.2 requires >=3.10. Using 3.10 as baseline ensures compatibility across all dependencies while providing modern type hints and pattern matching features. |

**Confidence:** HIGH (verified via PyPI)

---

## 1. Polymarket Integration

### CLOB API Client
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **py-clob-client** | 0.34.5 | Polymarket CLOB API client | **OFFICIAL LIBRARY:** Maintained by Polymarket Engineering. Latest release Jan 13, 2026. Provides read-only market data access (orderbooks, prices, market info), trading capabilities, and order management. Requires Python >=3.9.10. This is the only official Python client for Polymarket's Central Limit Order Book. |

**Installation:**
```bash
pip install py-clob-client==0.34.5
```

**Key capabilities:**
- Read market data (orderbooks, prices, market info) via public methods
- Retrieve API credentials for authenticated access
- Trade programmatically (not needed for read-only analytics)
- Supports EOA, email/Magic wallets, proxy wallets

**What NOT to use:**
- Unofficial/community clients (py-clob-client-extended): Lack official support and may lag behind API changes
- Direct API calls without client library: Reinvents signing logic and error handling

**Confidence:** HIGH (official library, actively maintained)

**Sources:**
- [py-clob-client PyPI](https://pypi.org/project/py-clob-client/)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
- [Polymarket Documentation](https://docs.polymarket.com/developers/CLOB/clients/methods-overview)

---

## 2. Data Storage & Analysis

### Database
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **SQLite** | Built-in | Local data persistence | **PROJECT CONSTRAINT:** Specified in requirements. Perfect for local-first architecture. No separate server required, stores everything in single file, excellent for embedded analytics tools. Python's sqlite3 module is built-in (no external dependency). |
| **SQLAlchemy** | 2.0.46 | ORM & query builder | **MODERN STANDARD:** Latest version released Jan 21, 2026. Provides clean ORM for trader/market/position models, sophisticated eager loading for relationships, and database schema generation. SQLAlchemy 2.0 brings modern type hints, asyncio support, and improved performance. Requires Python >=3.7. |

**Installation:**
```bash
pip install sqlalchemy==2.0.46
```

**Why SQLAlchemy over raw sqlite3:**
- Clean ORM for defining Trader, Market, Position, Trade models
- Relationship loading (trader → positions → markets) with minimal queries
- Schema migrations via Alembic (if needed later)
- Type-safe queries with modern 2.0 API

**Best practices for SQLite + SQLAlchemy:**
- Define clear relationships and constraints in schema
- Always close sessions to release resources
- Use SQLAlchemy 2.0 modern API (not legacy 1.x patterns)
- Enable WAL mode for better concurrency: `PRAGMA journal_mode=WAL`

**Confidence:** HIGH (official library, stable ecosystem)

**Sources:**
- [SQLAlchemy PyPI](https://pypi.org/project/SQLAlchemy/)
- [Real Python: SQLite with SQLAlchemy](https://realpython.com/python-sqlite-sqlalchemy/)
- [SQLAlchemy 2.1 Documentation](https://docs.sqlalchemy.org/en/21/dialects/sqlite.html)

---

### Data Analysis
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **Polars** | 1.38.0 | DataFrame operations | **PERFORMANCE CRITICAL:** Released Feb 4, 2026. Polars achieves 3-10x performance gains over pandas on large datasets. This project will analyze thousands of trader positions across hundreds of markets—Polars' Rust-based engine, columnar storage (Apache Arrow), and multi-threading make it ideal. Supports lazy evaluation, streaming for larger-than-RAM datasets, and powerful expression API. Requires Python >=3.10. |

**Installation:**
```bash
pip install polars==1.38.0
```

**Why Polars over pandas:**
- **Speed:** 3-10x faster for aggregations, filtering, grouping (critical for scoring traders)
- **Memory:** Columnar storage uses less RAM than pandas' row-based storage
- **Parallelism:** Uses all CPU cores automatically (pandas is single-threaded)
- **Modern API:** Cleaner query syntax, lazy evaluation for optimization

**When to use:**
- Aggregating positions across traders (groupby operations)
- Computing trader specialization scores (complex expressions)
- Filtering active markets and qualified traders
- Historical backtesting over large datasets

**What NOT to use:**
- pandas: Single-threaded, slower for large datasets, higher memory usage
- NumPy alone: Lower-level, requires more code for DataFrame operations

**Confidence:** HIGH (verified via PyPI, strong performance benchmarks)

**Sources:**
- [Polars PyPI](https://pypi.org/project/polars/)
- [Polars Official Site](https://pola.rs/)
- [HackerNoon: Pandas vs Polars 2025](https://hackernoon.com/pandas-vs-polars-in-2025-choosing-the-best-python-tool-for-big-data)
- [Real Python: Polars vs pandas](https://realpython.com/polars-vs-pandas/)

---

## 3. Task Scheduling & Background Jobs

### Job Scheduler
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **APScheduler** | 3.11.2 | Task scheduling & polling | **IN-PROCESS SCHEDULING:** Latest version released Dec 22, 2025. Perfect for polling Polymarket API at regular intervals without external infrastructure. Supports cron-style, interval-based, and one-time scheduling. Multiple job stores (memory, SQLAlchemy, Redis). Integrates seamlessly with asyncio. Requires Python >=3.8. |

**Installation:**
```bash
pip install apscheduler==3.11.2
```

**Why APScheduler over alternatives:**
- **No external dependencies:** Celery requires Redis/RabbitMQ message broker
- **In-process:** Perfect for local-first CLI tool
- **Simple setup:** Define schedules in code, start background thread
- **Flexible:** Supports both sync and async jobs
- **Persistent:** Can store jobs in SQLite via SQLAlchemy job store

**Use cases for this project:**
- Poll active markets every 5-15 minutes
- Refresh trader position data on schedule
- Periodic scoring recalculation
- Cleanup old data on cron schedule

**What NOT to use:**
- Celery: Overkill for single-process tool, requires external message broker
- cron + separate scripts: Less flexible, harder to manage in Python app
- while True + time.sleep(): Blocks main thread, no clean shutdown

**Confidence:** HIGH (official library, production-stable)

**Sources:**
- [APScheduler PyPI](https://pypi.org/project/APScheduler/)
- [Leapcell: APScheduler vs Celery Beat](https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-vs-celery-beat)
- [AIMultiple: Python Job Scheduling 2026](https://research.aimultiple.com/python-job-scheduling/)

---

## 4. CLI Framework

### Command-Line Interface
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **Typer** | 0.21.1 | CLI framework | **MODERN TYPE-SAFE CLI:** Latest version released Jan 6, 2026. Uses Python type hints for automatic argument parsing and validation. Built on Click but with cleaner API. Automatic `--help` generation, shell auto-completion, and rich error messages (via Rich library). Requires Python >=3.9. |

**Installation:**
```bash
pip install typer[all]==0.21.1  # Includes Rich for formatted output
```

**Why Typer over alternatives:**
- **Type hints:** Arguments declared with standard Python types (no decorators overload)
- **Automatic docs:** `--help` generated from docstrings and type hints
- **Developer experience:** IDE completion and type checking throughout
- **Progressive:** Start simple (single command), grow to command groups/subcommands
- **Rich integration:** Beautiful terminal output with colors, tables, progress bars

**Command structure for this project:**
```bash
polymarket-tracker discover --sport esports       # Discover active markets
polymarket-tracker track --market-id <id>          # Track specific market
polymarket-tracker score --min-trades 10           # Score traders
polymarket-tracker alert --webhook discord         # Send alerts
polymarket-tracker daemon --interval 300           # Run background poller
```

**What NOT to use:**
- argparse: Verbose boilerplate, manual type conversion, no auto-completion
- Click alone: More verbose than Typer, less type-safe
- docopt: String-based DSL, harder to maintain

**Confidence:** HIGH (verified via PyPI, mature ecosystem)

**Sources:**
- [Typer PyPI](https://pypi.org/project/typer/)
- [Typer Official Docs](https://typer.tiangolo.com/)
- [CodeCut: Comparing Python CLI Tools](https://codecut.ai/comparing-python-command-line-interface-tools-argparse-click-and-typer/)

---

## 5. Webhook Integrations

### Discord Notifications
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **discord-webhook** | 1.4.1 | Discord webhook client | **WEBHOOK-ONLY:** Latest version released Mar 5, 2025. Purpose-built for webhook operations (no bot hosting required). Supports rich embeds, file attachments, async operations, and rate limit handling. Requires Python 3.10+. Perfect for sending alerts without running a persistent Discord bot. |

**Installation:**
```bash
pip install discord-webhook==1.4.1
```

**Why discord-webhook over alternatives:**
- **No bot required:** Uses webhook URLs (no OAuth, no persistent connection)
- **Lightweight:** Single purpose library, minimal dependencies
- **Rich embeds:** Format alerts with colors, fields, timestamps
- **Async support:** Non-blocking webhook calls
- **Rate limiting:** Automatic retry on 429 responses

**Use cases:**
```python
from discord_webhook import DiscordWebhook, DiscordEmbed

webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
embed = DiscordEmbed(
    title="Smart Money Alert: eSports Market",
    description="5 expert traders converging on YES",
    color="03b2f8"
)
embed.add_embed_field(name="Market", value="Will Team Liquid win?")
embed.add_embed_field(name="Signal Strength", value="8.7/10")
webhook.add_embed(embed)
webhook.execute()
```

**What NOT to use:**
- discord.py: Full bot library, overkill for webhooks, requires hosting
- dhooks: Less actively maintained, missing latest features
- Requests + manual webhook: Reinvents embed formatting, rate limiting

**Confidence:** HIGH (verified via PyPI, webhook-specific library)

**Sources:**
- [discord-webhook PyPI](https://pypi.org/project/discord-webhook/)
- [Discord Developer Docs](https://discord.com/developers/docs/resources/webhook)

---

### Telegram Notifications
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **python-telegram-bot** | 22.6 | Telegram bot client | **OFFICIAL LIBRARY:** Latest version released Jan 24, 2026. Full async API for Telegram Bot API 9.3. Supports both polling and webhooks. Fully type-annotated with static type hints. Requires Python >=3.10. More flexible than webhook-only libraries—can start with simple message sending, grow to interactive commands if needed. |

**Installation:**
```bash
pip install python-telegram-bot==22.6
```

**Why python-telegram-bot over alternatives:**
- **Official support:** Tracks Telegram Bot API closely (currently 9.3)
- **Async-first:** Built on asyncio, non-blocking operations
- **Type-safe:** Full type hints for IDE support
- **Flexible:** Supports both simple message sending and full bot features
- **Production-ready:** Robust error handling, retry logic

**Use cases (webhook mode for alerts):**
```python
from telegram import Bot
import asyncio

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_alert(chat_id: int, message: str):
    await bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="Markdown"
    )

asyncio.run(send_alert(CHAT_ID, "**Alert:** Smart money moving"))
```

**What NOT to use:**
- Requests + manual API calls: No retry logic, manual error handling
- Older sync libraries: Don't leverage modern async patterns
- webhook-only libraries: Less flexible, harder to grow feature set

**Confidence:** HIGH (official library, actively maintained)

**Sources:**
- [python-telegram-bot PyPI](https://pypi.org/project/python-telegram-bot/)
- [python-telegram-bot Wiki: Webhooks](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Webhooks)

---

## 6. HTTP Client

### API Client
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **httpx** | 0.28.1 | HTTP client (async + sync) | **MODERN HTTP CLIENT:** Released Dec 6, 2024. Supports both sync and async APIs in single library. HTTP/2 support, full type annotations, timeout controls. Drop-in replacement for requests but with async capability. Requires Python >=3.8. |

**Installation:**
```bash
pip install httpx==0.28.1
```

**Why httpx over alternatives:**
- **Dual API:** Same codebase for sync CLI commands and async background jobs
- **HTTP/2:** Better performance for multiple requests to same host
- **Type-safe:** Full type hints, better IDE support than requests
- **Modern:** Actively developed, follows modern Python patterns
- **Familiar:** API similar to requests, easy migration

**Use cases:**
- Sync: Quick CLI commands that fetch data immediately
- Async: Background polling jobs that fetch many markets concurrently
- py-clob-client internally may use requests, but httpx for any custom API calls

**What NOT to use:**
- requests: Sync-only, no HTTP/2, not actively developed
- aiohttp: Async-only (forces async everywhere), less beginner-friendly
- urllib: Too low-level, verbose

**Confidence:** HIGH (verified via PyPI, modern standard)

**Sources:**
- [httpx PyPI](https://pypi.org/project/httpx/)
- [Speakeasy: Python HTTP Clients Comparison](https://www.speakeasy.com/blog/python-http-clients-requests-vs-httpx-vs-aiohttp)
- [Oxylabs: HTTPX vs Requests vs AIOHTTP](https://oxylabs.io/blog/httpx-vs-requests-vs-aiohttp)

---

## 7. Configuration & Environment

### Configuration Management
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **pydantic-settings** | 2.12.0 | Type-safe configuration | **TYPE-SAFE CONFIG:** Released Nov 10, 2025. Loads .env files, environment variables into validated Pydantic models. Supports TOML, JSON, YAML. Type-safe with automatic validation. Requires Python >=3.10. Perfect for managing API keys, webhook URLs, database paths with type checking. |

**Installation:**
```bash
pip install pydantic-settings==2.12.0
```

**Why pydantic-settings over alternatives:**
- **Type-safe:** Configuration errors caught at startup, not runtime
- **Validation:** Pydantic validators ensure API keys are non-empty, URLs are valid
- **Environment-aware:** Auto-loads from .env, overrides with env vars
- **Integration:** Works seamlessly with Pydantic models used elsewhere
- **Simple:** Less configuration than Dynaconf for straightforward needs

**Example:**
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    polymarket_api_key: str
    discord_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    database_path: str = "./data/tracker.db"
    polling_interval: int = 300  # seconds

settings = Settings()  # Loads from .env + env vars, validates types
```

**What NOT to use:**
- python-dotenv alone: No type checking or validation
- Dynaconf: More complex, overkill for simple config needs
- ConfigParser: Older API, no type safety

**Confidence:** HIGH (verified via PyPI, Pydantic ecosystem)

**Sources:**
- [pydantic-settings PyPI](https://pypi.org/project/pydantic-settings/)
- [Pydantic Settings Docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Leapcell: Pydantic vs Dynaconf](https://leapcell.io/blog/pydantic-basesettings-vs-dynaconf-a-modern-guide-to-application-configuration)

---

## 8. Data Validation

### Schema Validation
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **Pydantic** | 2.12.5 | Data validation & parsing | **CORE VALIDATION:** Released Nov 26, 2025. Industry-standard data validation using Python type hints. Core written in Rust for performance. Used by py-clob-client, FastAPI, many modern Python projects. Validates API responses, CLI inputs, configuration. Requires Python >=3.9. |

**Installation:**
```bash
pip install pydantic==2.12.5
```

**Why Pydantic is essential:**
- **Runtime validation:** Catches bad API data before it enters database
- **Type safety:** Models define clear contracts for data structures
- **Performance:** Rust core makes validation fast (critical for high-frequency polling)
- **Serialization:** JSON parsing/dumping with validation
- **Ecosystem:** Works with pydantic-settings, SQLAlchemy models

**Use cases:**
```python
from pydantic import BaseModel, Field, validator

class Market(BaseModel):
    market_id: str
    question: str
    category: str
    active: bool
    volume: float = Field(ge=0)  # Must be >= 0

    @validator("category")
    def validate_esports(cls, v):
        if "esports" not in v.lower():
            raise ValueError("Must be eSports category")
        return v

# Validates data from Polymarket API
market = Market(**api_response)  # Raises ValidationError if invalid
```

**Confidence:** HIGH (verified via PyPI, industry standard)

**Sources:**
- [Pydantic PyPI](https://pypi.org/project/pydantic/)
- [Pydantic Official Docs](https://docs.pydantic.dev/latest/)
- [Real Python: Pydantic](https://realpython.com/python-pydantic/)

---

## 9. Logging

### Structured Logging
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **Loguru** | 0.7.3 | Logging library | **SIMPLE & POWERFUL:** Released Dec 6, 2024. Zero-config logging with sensible defaults. Colorized output, automatic exception catching, rotation, serialization. Much simpler than Python's built-in logging module. Requires Python >=3.5. Perfect for CLI tools that need good observability without complex logging setup. |

**Installation:**
```bash
pip install loguru==0.7.3
```

**Why Loguru over alternatives:**
- **Zero config:** Import and use, no handlers/formatters setup
- **Colorized:** Beautiful terminal output with automatic color coding
- **Exception catching:** `@logger.catch` decorator logs full tracebacks
- **Rotation:** Automatic log file rotation by size/time
- **Serialization:** JSON output for structured logging
- **Simpler than stdlib:** No handler/formatter/logger hierarchy

**Example:**
```python
from loguru import logger

# Replaces standard logging with colored, formatted output
logger.info("Polling Polymarket API for active markets")
logger.warning("Trader {trader_id} has low confidence score: {score}", trader_id=123, score=0.3)
logger.error("Failed to fetch market data")

# Catch exceptions automatically
@logger.catch
def risky_operation():
    # Any exception logged with full traceback
    ...
```

**What NOT to use:**
- Python's logging module: Verbose setup, complex hierarchy
- structlog: More powerful but more complex setup
- print statements: No log levels, no file output, no structured data

**Confidence:** HIGH (verified via PyPI, popular choice)

**Sources:**
- [Loguru PyPI](https://pypi.org/project/loguru/)
- [Better Stack: Best Python Logging Libraries](https://betterstack.com/community/guides/logging/best-python-logging-libraries/)
- [Dash0: Loguru Production-Grade Logging](https://www.dash0.com/guides/python-logging-with-loguru)

---

## 10. Development Tools

### Testing Framework
| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **pytest** | 9.0.2 | Testing framework | **MODERN TESTING:** Released Dec 6, 2025. De facto standard for Python testing. Simple assertions, powerful fixtures, parameterized tests, plugin ecosystem. Less boilerplate than unittest. Requires Python >=3.10. |

**Installation:**
```bash
pip install pytest==9.0.2
pip install pytest-asyncio==0.24.0  # For async tests
pip install pytest-cov==6.0.0       # For coverage reports
```

**Why pytest over alternatives:**
- **Simple:** Plain `assert` statements, no `self.assertEqual`
- **Fixtures:** Reusable test setup with dependency injection
- **Parametrization:** Run same test with multiple inputs
- **Plugins:** Coverage, asyncio, mock, benchmarking extensions
- **Discovery:** Automatically finds tests in `test_*.py` files

**Confidence:** HIGH (verified via PyPI, industry standard)

**Sources:**
- [pytest PyPI](https://pypi.org/project/pytest/)
- [Real Python: pytest](https://realpython.com/pytest-python-testing/)
- [pytest Official Docs](https://docs.pytest.org/en/stable/explanation/goodpractices.html)

---

### Code Quality

| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **Ruff** | 0.15.0 | Linter & formatter | **MODERN TOOLING:** Released Feb 3, 2026. Rust-based linter and formatter. 10-100x faster than Black/Flake8/pylint. Combines linting (replaces Flake8, isort, pyupgrade) and formatting (Black-compatible) in single tool. Requires Python >=3.7. |

**Installation:**
```bash
pip install ruff==0.15.0
```

**Why Ruff over alternatives:**
- **Speed:** 30x faster than Black, 100x faster than pylint
- **All-in-one:** Replaces Black, isort, Flake8, pyupgrade, pydocstyle
- **Black-compatible:** >99.9% formatting compatibility with Black
- **Modern rules:** Includes rules for Python 3.10+ features
- **Single tool:** Simpler dependency graph and CI setup

**Configuration (`pyproject.toml`):**
```toml
[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]  # Error, pyflakes, isort, naming, warnings, pyupgrade
ignore = ["E501"]  # Line too long (handled by formatter)

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

**What NOT to use:**
- Black alone: Slower, separate tool
- Flake8 + isort + pyupgrade: Multiple tools, slower, more config
- pylint: Much slower, more opinionated

**Confidence:** HIGH (verified via PyPI, rapidly adopted)

**Sources:**
- [Ruff PyPI](https://pypi.org/project/ruff/)
- [Ruff Official Docs](https://docs.astral.sh/ruff/formatter/)
- [Astral: Ruff Formatter Announcement](https://astral.sh/blog/the-ruff-formatter)

---

### Package Management

| Technology | Version | Purpose | Rationale |
|------------|---------|---------|-----------|
| **uv** | Latest | Package & environment manager | **NEXT-GEN TOOLING:** Rust-based package manager, 10-100x faster than pip. Replaces pip, venv, pip-tools, and pyenv in single tool. Automatic Python version management, lock files by default, project-based workflow. Modern approach for 2025-2026. |

**Installation:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Why uv over alternatives:**
- **Speed:** 10-100x faster than pip for dependency resolution
- **All-in-one:** Replaces pip, venv, pip-tools, pyenv
- **Lock files:** `uv.lock` ensures reproducible builds by default
- **Python management:** Downloads/manages Python versions automatically
- **Modern workflow:** `uv add`, `uv sync`, `uv run` commands

**Project setup:**
```bash
uv init polymarket-tracker
cd polymarket-tracker
uv python install 3.10  # Downloads Python 3.10 if needed
uv add py-clob-client polars sqlalchemy typer  # Updates pyproject.toml + uv.lock
uv sync  # Installs all dependencies
uv run python main.py  # Runs in project environment
```

**What NOT to use:**
- pip + venv: Slower, manual environment management
- Poetry: Slower than uv, more complex for simple projects
- pip-tools: Separate tool for lock files, slower

**Confidence:** MEDIUM-HIGH (new tool but rapid adoption, from Astral/Ruff team)

**Sources:**
- [Medium: Poetry vs UV 2025](https://medium.com/@hitorunajp/poetry-vs-uv-which-python-package-manager-should-you-use-in-2025-4212cb5e0a14)
- [Analytics Vidhya: UV Ultimate Guide](https://www.analyticsvidhya.com/blog/2025/08/uv-python-package-manager/)
- [Loopwerk: Poetry vs uv](https://www.loopwerk.io/articles/2024/python-poetry-vs-uv/)

---

## Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **python-dotenv** | 1.0+ | .env file loading | If NOT using pydantic-settings (included in pydantic-settings) |
| **rich** | 13+ | Terminal formatting | Included with `typer[all]`, for tables/progress bars/panels |
| **click** | 8+ | CLI building blocks | Dependency of Typer (don't install directly) |
| **httpx[http2]** | 0.28.1 | HTTP/2 support | Install with `[http2]` extra for better performance |

---

## Installation Guide

### Recommended Setup with uv

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Initialize project
uv init polymarket-tracker
cd polymarket-tracker

# Set Python version
echo "3.10" > .python-version
uv python install 3.10

# Add dependencies
uv add py-clob-client==0.34.5 \
       polars==1.38.0 \
       sqlalchemy==2.0.46 \
       apscheduler==3.11.2 \
       "typer[all]==0.21.1" \
       discord-webhook==1.4.1 \
       python-telegram-bot==22.6 \
       "httpx[http2]==0.28.1" \
       pydantic-settings==2.12.0 \
       pydantic==2.12.5 \
       loguru==0.7.3

# Add dev dependencies
uv add --dev pytest==9.0.2 \
              pytest-asyncio==0.24.0 \
              pytest-cov==6.0.0 \
              ruff==0.15.0

# Sync environment
uv sync
```

### Alternative: Traditional pip + venv

```bash
# Create virtual environment
python3.10 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install py-clob-client==0.34.5 \
            polars==1.38.0 \
            sqlalchemy==2.0.46 \
            apscheduler==3.11.2 \
            "typer[all]==0.21.1" \
            discord-webhook==1.4.1 \
            python-telegram-bot==22.6 \
            "httpx[http2]==0.28.1" \
            pydantic-settings==2.12.0 \
            pydantic==2.12.5 \
            loguru==0.7.3

# Install dev dependencies
pip install pytest==9.0.2 \
            pytest-asyncio==0.24.0 \
            pytest-cov==6.0.0 \
            ruff==0.15.0

# Generate requirements.txt
pip freeze > requirements.txt
```

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not Alternative |
|----------|-------------|-------------|---------------------|
| **Data Analysis** | Polars 1.38.0 | pandas 2.x | Polars is 3-10x faster, uses less memory, multi-threaded. Pandas is single-threaded and slower for large aggregations. |
| **Task Scheduling** | APScheduler 3.11.2 | Celery | Celery requires external message broker (Redis/RabbitMQ), overkill for local-first tool. |
| **CLI Framework** | Typer 0.21.1 | Click | Typer builds on Click with cleaner type-hint API. Click requires more decorators and manual type handling. |
| **CLI Framework** | Typer 0.21.1 | argparse | argparse is verbose, no auto-completion, manual type conversion. Typer is more Pythonic. |
| **HTTP Client** | httpx 0.28.1 | requests | requests is sync-only, no HTTP/2, not actively developed. httpx supports async + sync in one API. |
| **HTTP Client** | httpx 0.28.1 | aiohttp | aiohttp is async-only, forces async everywhere. httpx supports both sync and async. |
| **Logging** | Loguru 0.7.3 | Python logging | stdlib logging requires verbose setup (handlers, formatters). Loguru works out of the box. |
| **Logging** | Loguru 0.7.3 | structlog | structlog is more powerful but requires more setup. Loguru is simpler for CLI tools. |
| **Config** | pydantic-settings 2.12.0 | Dynaconf | Dynaconf is more complex, overkill for straightforward config needs. pydantic-settings is simpler and type-safe. |
| **Config** | pydantic-settings 2.12.0 | python-dotenv | python-dotenv loads .env but has no validation. pydantic-settings validates types at startup. |
| **Code Quality** | Ruff 0.15.0 | Black + Flake8 + isort | Ruff combines all three tools, 10-100x faster, single dependency. |
| **Package Manager** | uv | Poetry | Poetry is slower, more complex for simple projects. uv is 10-100x faster, simpler workflow. |
| **Package Manager** | uv | pip + venv | pip is slower, requires manual lock files. uv has lock files by default, manages Python versions. |
| **Testing** | pytest 9.0.2 | unittest | unittest requires more boilerplate (test classes, `self.assertEqual`). pytest uses plain `assert`. |
| **Discord Integration** | discord-webhook 1.4.1 | discord.py | discord.py is full bot library, requires hosting. discord-webhook is purpose-built for webhooks only. |

---

## Dependency Compatibility Matrix

| Library | Python Version | Key Dependencies |
|---------|----------------|------------------|
| py-clob-client 0.34.5 | >=3.9.10 | (uses requests internally) |
| Polars 1.38.0 | **>=3.10** | None |
| SQLAlchemy 2.0.46 | >=3.7 | None (optional: greenlet for async) |
| APScheduler 3.11.2 | >=3.8 | None |
| Typer 0.21.1 | **>=3.9** | Click, Rich (with `[all]`) |
| discord-webhook 1.4.1 | **>=3.10** | requests |
| python-telegram-bot 22.6 | **>=3.10** | httpx |
| httpx 0.28.1 | >=3.8 | httpcore, certifi |
| pydantic-settings 2.12.0 | **>=3.10** | Pydantic |
| Pydantic 2.12.5 | >=3.9 | (Rust core) |
| Loguru 0.7.3 | >=3.5 | None |
| pytest 9.0.2 | **>=3.10** | pluggy, packaging |
| Ruff 0.15.0 | >=3.7 | (Rust binary) |

**Baseline: Python 3.10+** (satisfies all dependencies)

---

## Architecture Implications

### Data Flow
```
Polymarket CLOB API (py-clob-client)
    ↓
Pydantic validation (Market, Trader, Position models)
    ↓
SQLAlchemy ORM (SQLite storage)
    ↓
Polars DataFrames (aggregation, scoring)
    ↓
CLI output (Typer + Rich) / Webhooks (Discord/Telegram)
```

### Concurrency Strategy
- **APScheduler:** Background thread for polling Polymarket API
- **httpx async:** Concurrent API calls for fetching multiple markets
- **Polars:** Multi-threaded DataFrame operations (automatic)
- **SQLAlchemy:** Connection pooling for concurrent reads/writes

### Configuration Layers
1. **Defaults:** Hardcoded in `pydantic-settings` models
2. **.env file:** Local overrides for development
3. **Environment variables:** Production secrets (API keys, webhook URLs)
4. **CLI flags:** Runtime overrides (via Typer)

---

## Open Questions & Future Research

### Phase-Specific Research Needs
- **Phase 1 (Data Collection):** Test py-clob-client rate limits, pagination strategies
- **Phase 2 (Storage):** SQLAlchemy schema design for trader history, indexes for performance
- **Phase 3 (Scoring):** Polars expression API for complex trader metrics
- **Phase 4 (Alerts):** Discord/Telegram rate limits, retry strategies

### Potential Additions Later
- **Web UI:** FastAPI + React if interactive dashboard needed (beyond CLI)
- **Caching:** Redis for caching market data (if API rate limits become issue)
- **Async DB:** aiosqlite for fully async pipeline (if concurrency bottleneck)
- **Distributed:** Celery + Redis if need to scale across machines (unlikely for MVP)

---

## Confidence Assessment

| Area | Confidence | Reasoning |
|------|------------|-----------|
| **Polymarket API** | HIGH | Official py-clob-client library, verified on PyPI, actively maintained |
| **Data Analysis** | HIGH | Polars 1.38.0 verified on PyPI, strong performance benchmarks from multiple sources |
| **Storage** | HIGH | SQLite + SQLAlchemy is well-established pattern, SQLAlchemy 2.0.46 verified on PyPI |
| **Scheduling** | HIGH | APScheduler 3.11.2 verified on PyPI, proven for in-process scheduling |
| **CLI** | HIGH | Typer 0.21.1 verified on PyPI, mature ecosystem |
| **Webhooks** | HIGH | Both discord-webhook and python-telegram-bot verified on PyPI, latest versions |
| **HTTP Client** | HIGH | httpx 0.28.1 verified on PyPI, modern standard for sync+async |
| **Config/Validation** | HIGH | Pydantic ecosystem verified on PyPI, industry standard |
| **Logging** | HIGH | Loguru 0.7.3 verified on PyPI, popular choice |
| **Dev Tools** | HIGH | pytest and Ruff verified on PyPI, widely adopted |
| **Package Manager** | MEDIUM-HIGH | uv is new (2024) but from Astral (Ruff team), rapid adoption. Poetry/pip are fallback options. |

**Overall Stack Confidence: HIGH**

All core libraries verified via official PyPI pages, actively maintained with recent releases (Jan-Feb 2026). Version numbers confirmed, Python 3.10+ baseline compatible with all dependencies.

---

## Sources

### Official Documentation & Package Registries
- [py-clob-client PyPI](https://pypi.org/project/py-clob-client/)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
- [Polymarket Documentation](https://docs.polymarket.com/developers/CLOB/clients/methods-overview)
- [Polars PyPI](https://pypi.org/project/polars/)
- [Polars Official Site](https://pola.rs/)
- [SQLAlchemy PyPI](https://pypi.org/project/SQLAlchemy/)
- [APScheduler PyPI](https://pypi.org/project/APScheduler/)
- [Typer PyPI](https://pypi.org/project/typer/)
- [Typer Official Docs](https://typer.tiangolo.com/)
- [discord-webhook PyPI](https://pypi.org/project/discord-webhook/)
- [python-telegram-bot PyPI](https://pypi.org/project/python-telegram-bot/)
- [httpx PyPI](https://pypi.org/project/httpx/)
- [pydantic-settings PyPI](https://pypi.org/project/pydantic-settings/)
- [Pydantic PyPI](https://pypi.org/project/pydantic/)
- [Loguru PyPI](https://pypi.org/project/loguru/)
- [pytest PyPI](https://pypi.org/project/pytest/)
- [Ruff PyPI](https://pypi.org/project/ruff/)

### Comparison & Best Practices Articles
- [HackerNoon: Pandas vs Polars 2025](https://hackernoon.com/pandas-vs-polars-in-2025-choosing-the-best-python-tool-for-big-data)
- [Real Python: Polars vs pandas](https://realpython.com/polars-vs-pandas/)
- [Leapcell: APScheduler vs Celery Beat](https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-vs-celery-beat)
- [CodeCut: Comparing Python CLI Tools](https://codecut.ai/comparing-python-command-line-interface-tools-argparse-click-and-typer/)
- [Speakeasy: Python HTTP Clients Comparison](https://www.speakeasy.com/blog/python-http-clients-requests-vs-httpx-vs-aiohttp)
- [Leapcell: Pydantic vs Dynaconf](https://leapcell.io/blog/pydantic-basesettings-vs-dynaconf-a-modern-guide-to-application-configuration)
- [Better Stack: Best Python Logging Libraries](https://betterstack.com/community/guides/logging/best-python-logging-libraries/)
- [Real Python: pytest](https://realpython.com/pytest-python-testing/)
- [Astral: Ruff Formatter Announcement](https://astral.sh/blog/the-ruff-formatter)
- [Medium: Poetry vs UV 2025](https://medium.com/@hitorunajp/poetry-vs-uv-which-python-package-manager-should-you-use-in-2025-4212cb5e0a14)

### Technical Deep Dives
- [Real Python: SQLite with SQLAlchemy](https://realpython.com/python-sqlite-sqlalchemy/)
- [python-telegram-bot Wiki: Webhooks](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Webhooks)
- [Pydantic Settings Docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Pydantic Official Docs](https://docs.pydantic.dev/latest/)
- [Ruff Official Docs](https://docs.astral.sh/ruff/formatter/)
- [pytest Official Docs](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
