"""OrderFilled event decoder using web3.py."""

from typing import Any

from web3 import Web3

from src.blockchain.models import BlockchainTrade

# Contract addresses
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEGRISK_CTF_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

# OrderFilled event topic (keccak256 of event signature)
ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"

# ABI for OrderFilled event (simplified)
ORDER_FILLED_ABI = {
    "anonymous": False,
    "inputs": [
        {"indexed": True, "name": "orderHash", "type": "bytes32"},
        {"indexed": True, "name": "maker", "type": "address"},
        {"indexed": True, "name": "taker", "type": "address"},
        {"indexed": False, "name": "makerAssetId", "type": "uint256"},
        {"indexed": False, "name": "takerAssetId", "type": "uint256"},
        {"indexed": False, "name": "makerAmountFilled", "type": "uint256"},
        {"indexed": False, "name": "takerAmountFilled", "type": "uint256"},
        {"indexed": False, "name": "fee", "type": "uint256"},
    ],
    "name": "OrderFilled",
    "type": "event",
}

# Polymarket CTF Exchange deployment block
POLYMARKET_START_BLOCK = 33605403


def decode_order_filled(log: dict[str, Any], w3: Web3) -> BlockchainTrade:
    """Decode an OrderFilled event log using web3.py.

    Args:
        log: Raw log dict from w3.eth.get_logs()
        w3: Web3 instance with loaded contract

    Returns:
        BlockchainTrade instance with decoded data

    Raises:
        ValueError: If log cannot be decoded
    """
    # Create contract instance for decoding
    contract = w3.eth.contract(address=log["address"], abi=[ORDER_FILLED_ABI])

    # Decode the event
    decoded = contract.events.OrderFilled().process_log(log)
    args = decoded["args"]

    return BlockchainTrade(
        block_number=log["blockNumber"],
        transaction_hash=log["transactionHash"].hex(),
        log_index=log["logIndex"],
        order_hash=args["orderHash"].hex(),
        maker=args["maker"],
        taker=args["taker"],
        maker_asset_id=args["makerAssetId"],
        taker_asset_id=args["takerAssetId"],
        maker_amount=args["makerAmountFilled"],
        taker_amount=args["takerAmountFilled"],
        fee=args["fee"],
    )
