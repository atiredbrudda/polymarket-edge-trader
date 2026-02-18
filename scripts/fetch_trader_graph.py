"""Fetch complete trader history from The Graph (Polymarket Orderbook subgraph).

This is the ZERO STORAGE solution - queries The Graph instead of downloading 36GB!

Usage:
    python fetch_trader_graph.py <trader_address>
    python fetch_trader_graph.py 0xeffd76b6a4318d50c6f71a16b276c5b279445a86
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime


SUBGRAPH_ID = "7fu2DWYK93ePfzB24c2wrP94S3x4LGHUrQxphhoEypyY"


def load_api_key():
    """Load API key from .env file."""
    env_file = Path(".env")
    if not env_file.exists():
        return None

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() == "THE_GRAPH_API_KEY":
                    return value.strip()
    return None


def query_graph(api_key, query):
    """Execute GraphQL query against Polymarket subgraph."""
    url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{SUBGRAPH_ID}"
    response = requests.post(url, json={"query": query})
    return response.json()


def fetch_all_trades(api_key, trader_address, max_per_query=1000):
    """Fetch ALL trades for a trader (both maker and taker).

    Uses pagination to get complete history.
    """
    trader_address = trader_address.lower()

    print(f"Fetching trades for {trader_address}...")
    print("="*80)

    all_trades = []

    # Query 1: Trades where address is MAKER
    print("\n1. Fetching trades where address is MAKER...")
    skip = 0
    while True:
        query = f"""
        {{
          orderFilledEvents(
            first: {max_per_query}
            skip: {skip}
            where: {{maker: "{trader_address}"}}
            orderBy: timestamp
            orderDirection: desc
          ) {{
            id
            maker
            taker
            makerAmountFilled
            takerAmountFilled
            timestamp
            blockNumber
            transactionHash
          }}
        }}
        """

        result = query_graph(api_key, query)

        if "errors" in result:
            print(f"   ❌ Error: {result['errors']}")
            break

        events = result.get("data", {}).get("orderFilledEvents", [])
        if not events:
            break

        all_trades.extend(events)
        print(f"   Fetched {len(events)} trades (total: {len(all_trades)})")

        if len(events) < max_per_query:
            break

        skip += max_per_query

    maker_count = len(all_trades)

    # Query 2: Trades where address is TAKER
    print("\n2. Fetching trades where address is TAKER...")
    skip = 0
    while True:
        query = f"""
        {{
          orderFilledEvents(
            first: {max_per_query}
            skip: {skip}
            where: {{taker: "{trader_address}"}}
            orderBy: timestamp
            orderDirection: desc
          ) {{
            id
            maker
            taker
            makerAmountFilled
            takerAmountFilled
            timestamp
            blockNumber
            transactionHash
          }}
        }}
        """

        result = query_graph(api_key, query)

        if "errors" in result:
            print(f"   ❌ Error: {result['errors']}")
            break

        events = result.get("data", {}).get("orderFilledEvents", [])
        if not events:
            break

        all_trades.extend(events)
        print(f"   Fetched {len(events)} trades (total: {len(all_trades)})")

        if len(events) < max_per_query:
            break

        skip += max_per_query

    taker_count = len(all_trades) - maker_count

    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"  Trades as MAKER: {maker_count}")
    print(f"  Trades as TAKER: {taker_count}")
    print(f"  TOTAL TRADES: {len(all_trades)}")
    print(f"{'='*80}\n")

    return all_trades


def analyze_trades(trades):
    """Analyze and display trade statistics."""
    if not trades:
        print("No trades found!")
        return

    # Sort by timestamp
    trades.sort(key=lambda t: int(t.get("timestamp", 0)))

    # Calculate stats
    first_trade = datetime.fromtimestamp(int(trades[0]["timestamp"]))
    last_trade = datetime.fromtimestamp(int(trades[-1]["timestamp"]))

    # Convert amounts (6 decimals for USDC)
    total_maker_volume = sum(int(t["makerAmountFilled"]) for t in trades) / 1e6
    total_taker_volume = sum(int(t["takerAmountFilled"]) for t in trades) / 1e6

    print("TRADE STATISTICS:")
    print(f"  First trade: {first_trade}")
    print(f"  Last trade:  {last_trade}")
    print(f"  Duration:    {(last_trade - first_trade).days} days")
    print(f"  Total maker volume: ${total_maker_volume:,.2f}")
    print(f"  Total taker volume: ${total_taker_volume:,.2f}")
    print()

    # Show first 10 trades
    print("FIRST 10 TRADES (chronological):")
    print("-" * 150)
    print(f"{'Date':<20} {'Block':<12} {'Role':<6} {'Maker Amt':<15} {'Taker Amt':<15} {'TX Hash':<66}")
    print("-" * 150)

    for trade in trades[:10]:
        dt = datetime.fromtimestamp(int(trade["timestamp"]))
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        block = trade["blockNumber"]

        # Determine role (maker or taker)
        role = "MAKER" if trade["maker"].lower() == trades[0]["maker"].lower() else "TAKER"

        maker_amt = int(trade["makerAmountFilled"]) / 1e6
        taker_amt = int(trade["takerAmountFilled"]) / 1e6
        tx_hash = trade["transactionHash"][:20] + "..."

        print(f"{date_str:<20} {block:<12} {role:<6} ${maker_amt:<14,.2f} ${taker_amt:<14,.2f} {tx_hash:<66}")

    print("-" * 150)
    print()

    # Show last 10 trades
    print("LAST 10 TRADES (most recent):")
    print("-" * 150)
    print(f"{'Date':<20} {'Block':<12} {'Role':<6} {'Maker Amt':<15} {'Taker Amt':<15} {'TX Hash':<66}")
    print("-" * 150)

    for trade in trades[-10:]:
        dt = datetime.fromtimestamp(int(trade["timestamp"]))
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        block = trade["blockNumber"]

        role = "MAKER" if trade["maker"].lower() == trades[0]["maker"].lower() else "TAKER"

        maker_amt = int(trade["makerAmountFilled"]) / 1e6
        taker_amt = int(trade["takerAmountFilled"]) / 1e6
        tx_hash = trade["transactionHash"][:20] + "..."

        print(f"{date_str:<20} {block:<12} {role:<6} ${maker_amt:<14,.2f} ${taker_amt:<14,.2f} {tx_hash:<66}")

    print("-" * 150)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nExample: @Xero100i")
        print("python fetch_trader_graph.py 0xeffd76b6a4318d50c6f71a16b276c5b279445a86")
        sys.exit(1)

    trader_address = sys.argv[1].strip()

    # Validate address
    if not trader_address.startswith("0x") or len(trader_address) != 42:
        print(f"Error: Invalid Ethereum address: {trader_address}")
        sys.exit(1)

    # Load API key
    api_key = load_api_key()
    if not api_key:
        print("Error: THE_GRAPH_API_KEY not found in .env file")
        sys.exit(1)

    print(f"Using API key: {api_key[:10]}...")
    print()

    # Fetch all trades
    trades = fetch_all_trades(api_key, trader_address)

    # Save to file
    output_file = f"trader_{trader_address[:8]}_graph_trades.json"
    with open(output_file, "w") as f:
        json.dump(trades, f, indent=2)
    print(f"✅ Saved {len(trades)} trades to: {output_file}\n")

    # Analyze and display
    analyze_trades(trades)

    print("\n" + "="*80)
    print("COMPARISON WITH OTHER METHODS:")
    print("="*80)
    print("The Graph (this):      Instant query, 0 GB storage, always up-to-date")
    print("Jon-Becker dataset:    36 GB download, stale data, fast once downloaded")
    print("Blockchain scanning:   6-7 hours, 100k RPC calls, always up-to-date")
    print("API limit:             Instant, 0 GB, but only 100 most recent trades")
    print("="*80)


if __name__ == "__main__":
    main()
