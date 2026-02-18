"""Query Jon-Becker's pre-indexed Polymarket dataset for trader history.

This uses the 36GB Parquet dataset instead of scanning the blockchain.
Query time: seconds instead of hours!

Prerequisites:
1. Download dataset: cd /tmp/prediction-market-analysis && make setup (36GB download)
2. Install pyarrow: pip install pyarrow pandas

Usage:
    python query_jbecker_dataset.py <trader_address>
"""

import sys
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq


def query_trader_trades(trader_address: str, dataset_path: Path):
    """Query all trades for a trader from Parquet dataset.

    Args:
        trader_address: Ethereum address (0x...)
        dataset_path: Path to data/polymarket/trades/ directory

    Returns:
        DataFrame with all trades where trader was maker OR taker
    """
    trader_address = trader_address.lower()

    print(f"Querying trades for {trader_address[:8]}...")
    print(f"Dataset path: {dataset_path}")

    # List all parquet files in trades directory
    trade_files = list(dataset_path.glob("*.parquet"))
    print(f"Found {len(trade_files)} parquet files")

    all_trades = []

    for file_path in trade_files:
        # Read parquet with filters for this trader
        # Filter: (maker == address) OR (taker == address)
        try:
            table = pq.read_table(
                file_path,
                filters=[
                    ('maker', '=', trader_address),
                    ('taker', '=', trader_address),
                ]
            )

            if table.num_rows > 0:
                df = table.to_pandas()
                all_trades.append(df)
                print(f"  {file_path.name}: {len(df)} trades")

        except Exception as e:
            print(f"  Error reading {file_path.name}: {e}")
            continue

    if not all_trades:
        print("No trades found!")
        return pd.DataFrame()

    # Combine all trades
    combined = pd.concat(all_trades, ignore_index=True)

    # Sort by block number
    combined = combined.sort_values('block_number')

    print(f"\nTotal trades: {len(combined)}")
    return combined


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    trader_address = sys.argv[1].strip()

    # Validate address
    if not trader_address.startswith("0x") or len(trader_address) != 42:
        print(f"Error: Invalid Ethereum address: {trader_address}")
        sys.exit(1)

    # Default dataset path (from Jon-Becker's structure)
    dataset_path = Path("/tmp/prediction-market-analysis/data/polymarket/trades")

    if not dataset_path.exists():
        print(f"Dataset not found at {dataset_path}")
        print("\nTo download:")
        print("  cd /tmp/prediction-market-analysis")
        print("  make setup")
        print("\nThis will download 36GB (compressed) from https://s3.jbecker.dev/data.tar.zst")
        sys.exit(1)

    # Query trades
    trades = query_trader_trades(trader_address, dataset_path)

    if len(trades) > 0:
        print("\nSample trades:")
        print(trades.head(10))

        # Save to CSV
        output_file = f"trader_{trader_address[:8]}_trades.csv"
        trades.to_csv(output_file, index=False)
        print(f"\nSaved all trades to: {output_file}")


if __name__ == "__main__":
    main()
