#!/usr/bin/env python3
"""Verify that get_market_trades() now properly filters trades by market."""

from loguru import logger

from src.api.client import PolymarketClient
from src.config.settings import get_settings

# Setup
settings = get_settings()
client = PolymarketClient(settings)

# Test with the LoL market
lol_market = "0xd6f59f7f6dd3fa5e30e20b12cb13579dad60f4c61243e4dfd40636c3112fab1d"

logger.info(f"Testing get_market_trades() with market {lol_market[:8]}...")

# Fetch trades using the fixed method
trades = client.get_market_trades(lol_market)

# Verify all trades are from the requested market
logger.info(f"Fetched {len(trades)} trades")

# Check if all trades match the requested market
mismatched = [t for t in trades if t.market.lower() != lol_market.lower()]

if mismatched:
    logger.error(f"FAIL: Found {len(mismatched)} trades from wrong markets!")
    for t in mismatched[:5]:
        logger.error(f"  - Trade {t.id[:8]}... is from market {t.market[:8]}...")
else:
    logger.info("✓ SUCCESS: All trades are from the requested market")

# Extract unique traders
trader_addresses = list(set(t.trader for t in trades))
logger.info(f"Found {len(trader_addresses)} unique traders")

# Show first 5
logger.info("First 5 traders:")
for i, addr in enumerate(trader_addresses[:5], 1):
    print(f"{i}. {addr}")
