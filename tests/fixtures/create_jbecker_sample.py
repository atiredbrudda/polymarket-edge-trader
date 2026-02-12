#!/usr/bin/env python3
"""
Generate a small test fixture with Jon Becker dataset schema.

Creates 100 trades with JBecker Parquet schema for testing purposes.
"""

import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime, timedelta


def generate_jbecker_sample():
    """Generate test fixture matching JBecker dataset schema."""

    # Schema matching JBecker's Parquet dataset
    schema = pa.schema([
        ("id", pa.string()),
        ("maker", pa.string()),
        ("taker", pa.string()),
        ("makerAmountFilled", pa.string()),
        ("takerAmountFilled", pa.string()),
        ("makerAssetId", pa.string()),
        ("takerAssetId", pa.string()),
        ("fee", pa.string()),
        ("timestamp", pa.int64()),
        ("blockNumber", pa.int64()),
        ("transactionHash", pa.string()),
        ("orderHash", pa.string()),
        ("side", pa.string()),
        ("price", pa.string()),
        ("_fetched_at", pa.timestamp("us")),
        ("_contract", pa.string()),
    ])

    # Known trader addresses for testing
    trader_xero = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trader_other = "0xeefa8eb0568f7cbd57d85e99f61c92dcc57a23b2"
    # Additional traders to avoid double-counting
    trader_3 = "0x1234567890abcdef1234567890abcdef12345678"
    trader_4 = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"

    # Base timestamp: 2024-01-01 00:00:00 UTC
    base_timestamp = 1704067200

    # Asset IDs (mock condition IDs)
    asset_ids = [
        "0xc5d563a0c9f5b3db2b0e2c8e6c8a2e3a4b5c6d7e",
        "0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "0xf1e2d3c4b5a6978869584736251423658746951",
        "0xb5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4",
    ]

    # Generate 100 trades
    trades = []
    for i in range(100):
        # First 50: trader_xero as maker, traders 3/4 as taker
        # Next 50: trader_other as maker, traders 3/4 as taker
        if i < 50:
            maker = trader_xero
            taker = trader_3 if i % 2 == 0 else trader_4
        else:
            maker = trader_other
            taker = trader_3 if i % 2 == 0 else trader_4

        # Alternating BUY/SELL
        side = "BUY" if i % 2 == 0 else "SELL"

        # Price between 0.01 and 0.99 (valid TradeResponse range)
        price = 0.01 + (i % 98) * 0.01
        price_str = f"{price:.6f}"

        # Amounts as 6-decimal integer strings (e.g., "1500000" = 1.5 USDC)
        maker_amount = (100000 + i * 10000)  # 0.1 to 1.09 USDC
        taker_amount = int(maker_amount / price)

        # Asset IDs (rotate through list)
        maker_asset = asset_ids[i % len(asset_ids)]
        taker_asset = asset_ids[(i + 1) % len(asset_ids)]

        # Timestamps: hourly starting from base
        timestamp = base_timestamp + (i * 3600)

        # Fee (2% = 0.02)
        fee = str(int(maker_amount * 0.02))

        # Block number
        block_number = 50000000 + i * 100

        # Transaction and order hashes (mock)
        tx_hash = f"0x{'a' * 63}{i:x}"
        order_hash = f"0x{'b' * 63}{i:x}"

        # Contract address (CTF Exchange)
        contract = "0x4bfb41d5b3570dece83bfc7c1cb0f028d7b3d6e"

        # Fetched timestamp
        fetched_at = datetime(2024, 1, 1) + timedelta(hours=i)

        trades.append({
            "id": f"trade_{i:04d}",
            "maker": maker,
            "taker": taker,
            "makerAmountFilled": str(maker_amount),
            "takerAmountFilled": str(taker_amount),
            "makerAssetId": maker_asset,
            "takerAssetId": taker_asset,
            "fee": fee,
            "timestamp": timestamp,
            "blockNumber": block_number,
            "transactionHash": tx_hash,
            "orderHash": order_hash,
            "side": side,
            "price": price_str,
            "_fetched_at": fetched_at,
            "_contract": contract,
        })

    # Convert to PyArrow Table
    table = pa.Table.from_pylist(trades, schema=schema)

    # Write to Parquet with snappy compression
    output_path = Path(__file__).parent / "jbecker_sample.parquet"
    pq.write_table(table, output_path, compression="snappy")

    print(f"Generated {len(trades)} trades in {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.2f} KB")
    print(f"Trader {trader_xero}: 50 trades")
    print(f"Trader {trader_other}: 50 trades")


if __name__ == "__main__":
    generate_jbecker_sample()
