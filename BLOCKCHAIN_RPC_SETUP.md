# Blockchain RPC Provider Setup Guide

This guide helps you configure a Polygon RPC provider for blockchain data fetching.

## Quick Start

1. Choose a provider below
2. Sign up and get your API key
3. Copy `.env.example` to `.env` if you haven't already
4. Add your `POLYGON_RPC_URL` to `.env`

## Provider Options

### 1. Alchemy
**Free Tier:** 300M compute units/month

⚠️ **IMPORTANT**: Free tier limited to **10 blocks per `eth_getLogs` request**!

**Steps:**
1. Sign up at https://www.alchemy.com/
2. Create a new app, select "Polygon" and "Mainnet"
3. Copy your API key from the dashboard
4. Add to `.env`:
   ```bash
   POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_API_KEY
   BLOCKCHAIN_BATCH_SIZE=10  # Required for free tier!
   ```

**Example:**
```bash
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/abc123def456ghi789
BLOCKCHAIN_BATCH_SIZE=10
```

**Note:** For production use, consider upgrading to Alchemy's PAYG plan to remove the 10-block restriction.

---

### 2. Infura
**Free Tier:** 100k requests/day

**Steps:**
1. Sign up at https://www.infura.io/
2. Create a new project
3. Add Polygon Mainnet to your project
4. Copy your Project ID
5. Add to `.env`:
   ```bash
   POLYGON_RPC_URL=https://polygon-mainnet.infura.io/v3/YOUR_PROJECT_ID
   ```

**Example:**
```bash
POLYGON_RPC_URL=https://polygon-mainnet.infura.io/v3/1234567890abcdef1234567890abcdef
```

---

### 3. QuickNode
**Free Tier:** Limited (check their pricing)

**Steps:**
1. Sign up at https://www.quicknode.com/
2. Create a new endpoint, select "Polygon Mainnet"
3. Copy your full endpoint URL (includes API key)
4. Add to `.env`:
   ```bash
   POLYGON_RPC_URL=https://your-endpoint-name.polygon-mainnet.quiknode.pro/YOUR_API_KEY/
   ```

**Example:**
```bash
POLYGON_RPC_URL=https://polished-winter-fog.polygon-mainnet.quiknode.pro/abc123def456/
```

---

### 4. Ankr (Free Public)
**Free Tier:** Public endpoint (rate-limited)

No signup required, but rate-limited:
```bash
POLYGON_RPC_URL=https://rpc.ankr.com/polygon
```

---

### 5. Public RPC (Not Recommended)
**Last Resort:** Heavily rate-limited, unreliable

```bash
POLYGON_RPC_URL=https://polygon-rpc.com
```

---

## Testing Your Setup

After configuring your RPC URL, test the connection:

```bash
source .venv/bin/activate
python -c "from src.blockchain.client import PolygonBlockchainClient; client = PolygonBlockchainClient(); print(f'Connected! Current block: {client.get_block_number()}')"
```

**Expected output:**
```
Connected! Current block: 12345678
```

## Configuration Files

- **`.env.example`** - Template with all provider formats (committed to git)
- **`.env`** - Your actual config with API keys (gitignored, never commit this!)

## Rate Limits & Recommendations

| Provider | Free Tier | eth_getLogs Limit | Best For |
|----------|-----------|-------------------|----------|
| **Infura** | 100k req/day | 10k results per request | **Production** (recommended) |
| **Alchemy Free** | 300M CU/month | **10 blocks per request** | Light testing only |
| **Alchemy PAYG** | Pay per request | Expanded limits | Heavy production use |
| **QuickNode** | Limited | Varies by plan | Professional use |
| **Ankr** | Rate-limited | Limited | Light testing |
| **Public RPC** | Very limited | Unreliable | Initial testing only |

**Recommendation:** Use **Infura** for production (100 block batches work great). Alchemy free tier is too restrictive (10 blocks = very slow).

## Troubleshooting

**Connection failed:**
- Verify your API key is correct
- Check if you selected "Polygon Mainnet" (not testnet)
- Ensure the URL format matches exactly (no extra spaces)

**Rate limit errors:**
- Upgrade your provider plan
- Reduce `BLOCKCHAIN_BATCH_SIZE` in `.env`
- Switch to a provider with higher limits

## Current Defaults

If `POLYGON_RPC_URL` is not set, the system falls back to:
```python
polygon_rpc_url: str = "https://polygon-rpc.com"  # Public RPC (unreliable)
```

**Always configure a proper RPC provider for production use.**
