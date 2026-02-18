"""Test Polymarket's The Graph subgraph for trader history queries.

This checks if we can query trades by trader address without downloading 36GB!

Prerequisites:
1. Get free API key from The Graph Studio: https://thegraph.com/studio/
2. Add to .env file: THE_GRAPH_API_KEY=your_key

Usage:
    python test_graph_subgraph.py
"""

import os
import sys
import requests
import json
from pathlib import Path


# Polymarket Orderbook subgraph on Polygon - has OrderFilledEvent with maker/taker
SUBGRAPH_ID = "7fu2DWYK93ePfzB24c2wrP94S3x4LGHUrQxphhoEypyY"


def load_env():
    """Load environment variables from .env file."""
    env_file = Path(".env")
    if not env_file.exists():
        return None

    env_vars = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()

    return env_vars.get("THE_GRAPH_API_KEY")


def get_schema(api_key):
    """Fetch GraphQL schema to see what queries are available."""
    url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{SUBGRAPH_ID}"

    # Introspection query to get schema
    query = """
    {
      __schema {
        types {
          name
          fields {
            name
            type {
              name
              kind
            }
          }
        }
      }
    }
    """

    response = requests.post(url, json={"query": query})
    return response.json()


def test_trader_query(api_key, trader_address):
    """Test if we can query trades by trader address."""
    url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{SUBGRAPH_ID}"

    # Try different potential query structures for OrderFilledEvent
    queries_to_test = [
        # Option 1: OrderFilledEvents by maker
        {
            "name": "orderFilledEvents by maker",
            "query": """
            {
              orderFilledEvents(first: 10, where: {maker: "%s"}) {
                id
                maker
                taker
                makerAmountFilled
                takerAmountFilled
                timestamp
                blockNumber
              }
            }
            """ % trader_address.lower()
        },
        # Option 2: OrderFilledEvents by taker
        {
            "name": "orderFilledEvents by taker",
            "query": """
            {
              orderFilledEvents(first: 10, where: {taker: "%s"}) {
                id
                maker
                taker
                makerAmountFilled
                takerAmountFilled
                timestamp
                blockNumber
              }
            }
            """ % trader_address.lower()
        },
        # Option 3: All OrderFilledEvents (limit to see structure)
        {
            "name": "recent orderFilledEvents",
            "query": """
            {
              orderFilledEvents(first: 3, orderBy: timestamp, orderDirection: desc) {
                id
                maker
                taker
                makerAmountFilled
                takerAmountFilled
                timestamp
                blockNumber
              }
            }
            """
        },
    ]

    results = []
    for test in queries_to_test:
        print(f"\nTesting: {test['name']}")
        print(f"Query: {test['query'][:100]}...")

        response = requests.post(url, json={"query": test["query"]})
        result = response.json()

        if "errors" in result:
            print(f"  ❌ Error: {result['errors'][0]['message']}")
        elif "data" in result and result["data"]:
            print(f"  ✅ Success! Got data:")
            print(f"     {json.dumps(result['data'], indent=2)[:200]}...")
        else:
            print(f"  ⚠️  No data returned")

        results.append({"test": test["name"], "result": result})

    return results


def main():
    # Try to load from .env file first
    api_key = load_env()

    # Fallback to environment variable
    if not api_key:
        api_key = os.getenv("THE_GRAPH_API_KEY")

    if not api_key:
        print("Error: THE_GRAPH_API_KEY not found")
        print("\nPlease add to .env file:")
        print("THE_GRAPH_API_KEY=your_key")
        print("\nOr set environment variable:")
        print("export THE_GRAPH_API_KEY=your_key")
        print("\nGet a free API key at: https://thegraph.com/studio/")
        sys.exit(1)

    print("="*60)
    print("Testing Polymarket Graph Subgraph")
    print("="*60)

    # Test with @Xero100i's address
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    print(f"\nTrader: {trader_address}")

    # First, get the schema
    print("\n1. Fetching schema...")
    schema = get_schema(api_key)

    if "errors" in schema:
        print(f"❌ Schema fetch failed: {schema['errors']}")
        return

    # Find relevant types
    print("\n2. Looking for relevant entity types...")
    types = schema.get("data", {}).get("__schema", {}).get("types", [])

    relevant_types = [
        t for t in types
        if t["name"] and not t["name"].startswith("_")
        and any(keyword in t["name"].lower() for keyword in ["trade", "user", "account", "position"])
    ]

    print(f"   Found {len(relevant_types)} relevant types:")
    for t in relevant_types[:10]:  # Show first 10
        print(f"     - {t['name']}")
        if t.get("fields"):
            for field in t["fields"][:5]:  # Show first 5 fields
                print(f"       └─ {field['name']}")

    # Try to query trader data
    print("\n3. Testing trader queries...")
    results = test_trader_query(api_key, trader_address)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    successful = [r for r in results if "data" in r["result"] and r["result"]["data"]]

    if successful:
        print(f"✅ SUCCESS: {len(successful)}/{len(results)} query patterns worked!")
        print("\nThe Graph subgraph CAN query trader history!")
        print("Recommended: Build integration to replace blockchain scanning")
    else:
        print("❌ No successful queries")
        print("The subgraph may not support trader address filtering")
        print("Recommended: Use Jon-Becker's dataset or cloud VM")

    # Save full results
    with open("graph_test_results.json", "w") as f:
        json.dump({
            "schema": schema,
            "query_tests": results
        }, f, indent=2)

    print(f"\nFull results saved to: graph_test_results.json")


if __name__ == "__main__":
    main()
