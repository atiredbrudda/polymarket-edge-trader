# Worker Task: Polymarket Proxy Address Resolution

## Branch Name
`worker/proxy-address-resolution`

## Problem
Most trader addresses in our database are proxy/smart contract wallets deployed by Polymarket, not the user's actual account. When you search these addresses on polymarket.com they have no profile. We need to resolve proxy addresses to real Polymarket profiles so we can:
1. Verify traders on the Polymarket UI
2. Filter out bots/contracts without profiles
3. Store profile metadata (display name, etc.)

## The API Endpoint
```
GET https://gamma-api.polymarket.com/public-profile?address={address}
```

- Works for BOTH proxy wallet addresses AND EOA (user) addresses
- Returns profile info including `proxyWallet` field
- Returns 404 with `{"type":"not found error","error":"profile not found"}` for addresses without accounts
- No authentication required
- Rate limit: respect existing rate limiter (50 req/s)

Example successful response fields:
- `proxyWallet` — the proxy contract address (the on-chain trading address)
- `name` — display name
- `pseudonym` — auto-generated pseudonym
- `bio` — user bio
- `profileImage` — avatar URL
- `createdAt` — profile creation timestamp

## What to Build

### 1. Add columns to the `Trader` model (`src/db/models.py`)

Add these nullable columns to the `Trader` class (line ~62):
```python
proxy_wallet: Mapped[str | None] = mapped_column(String(42), nullable=True)
display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
profile_resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
has_profile: Mapped[bool] = mapped_column(default=False, nullable=False)
```

- `proxy_wallet`: The proxy address from the API (may differ from `address`)
- `display_name`: Human-readable name or pseudonym
- `profile_resolved`: Whether we've attempted to resolve this address (so we don't re-query 404s)
- `has_profile`: Whether the address has a Polymarket profile

### 2. Add profile resolution method to `GammaMarketClient` (`src/api/gamma_client.py`)

Add a method to the existing `GammaMarketClient` class:
```python
def get_public_profile(self, address: str) -> dict | None:
    """Fetch public profile for a Polymarket address.

    Works for both proxy wallet addresses and EOA addresses.
    Returns None if no profile exists (404).
    """
    url = f"{self.BASE_URL}/public-profile"
    params = {"address": address.lower()}
    # Use existing rate limiter and httpx patterns from the class
    # Return the JSON dict on success, None on 404
```

### 3. Add pipeline method (`src/pipeline/ingest.py`)

Add a method to the pipeline class:
```python
def resolve_trader_profiles(self, limit: int | None = None) -> int:
    """Resolve Polymarket profiles for traders with profile_resolved=False.

    For each unresolved trader:
    1. Call gamma API get_public_profile(address)
    2. If profile found: set has_profile=True, store display_name, proxy_wallet
    3. If 404: set has_profile=False
    4. Always set profile_resolved=True

    Returns count of profiles found.
    """
```

### 4. Add CLI command (`src/cli/commands.py`)

Add a `resolve-profiles` command:
```bash
polymarket resolve-profiles              # Resolve all unresolved traders
polymarket resolve-profiles --limit 50   # Resolve up to 50
```

Output should show progress and summary:
```
Resolving profiles... 200 traders pending
[################] 200/200
Found 45 profiles, 155 no profile
```

### 5. Integrate into discover pipeline

After `discover` finds new traders, optionally call `resolve_trader_profiles()` for the newly discovered traders. This can be a follow-up enhancement — the CLI command is the priority.

## Existing Patterns to Follow

- **Rate limiter**: `GammaMarketClient` already uses `self.rate_limiter` — follow the same pattern
- **HTTP client**: Uses `httpx` (not requests) — follow existing patterns in gamma_client.py
- **DB sessions**: Use `get_session(session_factory)` context manager pattern
- **Logging**: Use `loguru` logger, same as everywhere else
- **CLI**: Uses `click` decorators, `rich` console for output — follow existing command patterns

## Database Migration

Since we're adding columns to an existing table, you need to handle the migration. The project uses SQLAlchemy with `Base.metadata.create_all()`. Adding nullable columns with defaults should work with ALTER TABLE. Add a migration helper if needed, or rely on SQLAlchemy's `create_all()` for new DBs and a manual ALTER for existing ones.

Simple approach — add to the resolve-profiles command:
```python
# Ensure new columns exist (for existing databases)
from sqlalchemy import inspect, text
inspector = inspect(engine)
existing_cols = [c['name'] for c in inspector.get_columns('traders')]
with engine.begin() as conn:
    if 'profile_resolved' not in existing_cols:
        conn.execute(text("ALTER TABLE traders ADD COLUMN profile_resolved BOOLEAN DEFAULT 0 NOT NULL"))
    if 'has_profile' not in existing_cols:
        conn.execute(text("ALTER TABLE traders ADD COLUMN has_profile BOOLEAN DEFAULT 0 NOT NULL"))
    # etc for other columns
```

## Files to Modify
- `src/db/models.py` — Add columns to Trader model
- `src/api/gamma_client.py` — Add `get_public_profile()` method
- `src/pipeline/ingest.py` — Add `resolve_trader_profiles()` method
- `src/cli/commands.py` — Add `resolve-profiles` CLI command

## Testing
- Write tests in `tests/test_profile_resolution.py`
- Mock the gamma API responses (success + 404)
- Test the DB column migration path
- Test the CLI command output

## Important Notes
- The database is at `data/polymarket.db` (NOT `polymarket.db` in project root)
- Create your branch from `main`: `git checkout -b worker/proxy-address-resolution main`
- Do NOT commit to main — a pre-commit hook will block you
- Follow the code standards in `.planning/HANDOFF_PROTOCOL.md`
- Update `.planning/REVIEW_QUEUE.md` when done
