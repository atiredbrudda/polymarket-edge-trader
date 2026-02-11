#!/usr/bin/env python3
"""Find resolved eSports markets from trader history for testing scoring."""

import httpx
from loguru import logger

# Get a sample trader address
trader_address = "0x013246d9e5fd30d3ddd2e08246f419de3afec314"

logger.info(f"Searching for resolved markets from trader {trader_address[:8]}...")

# Use public Data API to get trader's market activity
url = f"https://data-api.polymarket.com/trades?proxyWallet={trader_address}"

try:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    trades_data = response.json()

    # Extract unique market IDs
    market_ids = list(set(trade.get("conditionId") for trade in trades_data if trade.get("conditionId")))

    logger.info(f"Found {len(market_ids)} unique markets from trader's history")

    # Check each market to find resolved ones
    resolved_markets = []

    for market_id in market_ids[:20]:  # Check first 20 to save time
        try:
            # Fetch market details
            market_url = f"https://clob.polymarket.com/markets/{market_id}"
            market_response = httpx.get(market_url, timeout=10.0)
            market_response.raise_for_status()
            market_data = market_response.json()

            # Check if market is resolved (has outcome)
            if market_data.get("outcome") is not None and not market_data.get("active"):
                # Check if it's eSports
                tags = market_data.get("tags", [])
                tags_lower = [tag.lower() for tag in tags]

                if "esports" in tags_lower:
                    resolved_markets.append({
                        "condition_id": market_id,
                        "question": market_data.get("question"),
                        "outcome": market_data.get("outcome"),
                        "tags": tags
                    })
                    logger.info(f"✓ Resolved eSports market: {market_data.get('question')[:60]}...")

        except Exception as e:
            logger.debug(f"Failed to fetch market {market_id[:8]}...: {e}")
            continue

    logger.info(f"\nFound {len(resolved_markets)} resolved eSports markets")

    if resolved_markets:
        print("\n=== RESOLVED ESPORTS MARKETS ===\n")
        for i, market in enumerate(resolved_markets[:5], 1):
            print(f"{i}. {market['question']}")
            print(f"   Condition ID: {market['condition_id']}")
            print(f"   Outcome: {market['outcome']}")
            print()

except Exception as e:
    logger.error(f"Failed to fetch trader history: {e}")
