#!/usr/bin/env python3
"""Find ANY resolved eSports markets from Polymarket API."""

import httpx
from loguru import logger
from py_clob_client.client import ClobClient

logger.info("Searching for resolved eSports markets...")

client = ClobClient("https://clob.polymarket.com")

# Fetch markets (will get paginated results)
next_cursor = "MA=="
resolved_esports = []
total_checked = 0

while total_checked < 500:  # Check first 500 markets
    try:
        response = client.get_simplified_markets(next_cursor=next_cursor)

        if isinstance(response, dict):
            markets_data = response.get("data", [])
            next_cursor = response.get("next_cursor")
        else:
            markets_data = response
            next_cursor = None

        for market in markets_data:
            total_checked += 1

            # Check if resolved (has outcome and not active)
            if market.get("outcome") is not None and not market.get("active", True):
                # Check if eSports
                tags = market.get("tags", [])
                tags_lower = [tag.lower() for tag in tags]

                if "esports" in tags_lower:
                    resolved_esports.append({
                        "condition_id": market.get("condition_id"),
                        "question": market.get("question"),
                        "outcome": market.get("outcome"),
                        "tags": tags
                    })
                    logger.info(f"✓ Found: {market.get('question')[:60]}...")

                    if len(resolved_esports) >= 5:
                        break

            if len(resolved_esports) >= 5:
                break

        if not next_cursor or next_cursor == "LTE" or len(resolved_esports) >= 5:
            break

    except Exception as e:
        logger.error(f"Error: {e}")
        break

logger.info(f"\nChecked {total_checked} markets, found {len(resolved_esports)} resolved eSports markets")

if resolved_esports:
    print("\n=== RESOLVED ESPORTS MARKETS ===\n")
    for i, market in enumerate(resolved_esports, 1):
        print(f"{i}. {market['question']}")
        print(f"   Condition ID: {market['condition_id']}")
        print(f"   Outcome: {market['outcome']}")
        print()
else:
    logger.warning("No resolved eSports markets found in first 500 markets")
    logger.info("This might mean:")
    logger.info("1. eSports markets resolve slowly (games haven't finished yet)")
    logger.info("2. Resolved markets are archived/not in recent API results")
    logger.info("3. Need to check more markets (increase limit)")
