# The Graph API Setup Guide

Quick guide to get your API key and test Polymarket subgraph queries (zero storage needed!)

---

## Step 1: Get Your API Key

### Option A: Without Crypto Wallet (Easiest)
1. Go to **https://thegraph.com/studio/**
2. Look for "Sign in with email" or similar option
3. Create account with email

### Option B: With Crypto Wallet (MetaMask, etc.)
1. Go to **https://thegraph.com/studio/**
2. Click **"Connect Wallet"**
3. Connect MetaMask or other Web3 wallet
4. Sign the message to authenticate

### Create API Key
1. Once logged in, click **"API Keys"** in left sidebar
2. Click **"Create API Key"** button
3. Give it a name (e.g., "Polymarket Trader Analysis")
4. Copy the generated API key (long string like: `abc123def456...`)

---

## Step 2: Configure Your API Key

You have **two options** - choose one:

### Option A: Use Setup Script (Recommended)
```bash
# Run the setup script
./setup_graph_api.sh

# It will prompt you to:
# 1. Edit .env.graph file
# 2. Paste your API key
# 3. Save and run script again
```

### Option B: Manual Setup
```bash
# 1. Open the config file
nano .env.graph

# 2. Replace 'your-api-key-here' with your actual key:
THE_GRAPH_API_KEY=abc123def456...

# 3. Save and exit (Ctrl+X, Y, Enter in nano)

# 4. Load the key and run test
source .env.graph
export THE_GRAPH_API_KEY
python test_graph_subgraph.py
```

---

## Step 3: Test It!

### Quick Test
```bash
./setup_graph_api.sh
```

This will:
- ✅ Verify your API key is set
- ✅ Test connection to Polymarket subgraph
- ✅ Try different query patterns
- ✅ Save results to `graph_test_results.json`

### Expected Output
```
==================================
Testing Polymarket Graph Subgraph
==================================

Trader: 0xeffd76b6a4318d50c6f71a16b276c5b279445a86

1. Fetching schema...
2. Looking for relevant entity types...
   Found X relevant types:
     - Trade
     - User
     - Account
     ...

3. Testing trader queries...

Testing: trades by maker
Query: {...}
  ✅ Success! Got data: {...}

==================================
SUMMARY
==================================
✅ SUCCESS: The Graph subgraph CAN query trader history!
```

---

## What Happens Next?

### ✅ If Queries Work
**You've solved the storage problem!**
- Zero storage needed
- Instant trader history queries
- Always up-to-date data
- Free tier available

Next steps:
1. Review `graph_test_results.json` to see what queries work
2. Build integration into our pipeline
3. Replace blockchain scanning with Graph queries

### ❌ If Queries Fail
The subgraph might not support trader address filtering.

Alternatives:
1. **Accept API limits** - 100 trades might be enough
2. **Cloud VM** - Rent $8/mo server for Jon-Becker's dataset
3. **Download → Delete** - Temp storage in `/tmp`

---

## Troubleshooting

### "API key not configured"
- Check `.env.graph` file exists
- Verify you replaced `your-api-key-here` with actual key
- No spaces or quotes around the key
- Format: `THE_GRAPH_API_KEY=abc123...`

### "Schema fetch failed"
- Verify API key is valid
- Check internet connection
- Try in browser: `https://thegraph.com/studio/apikeys/`

### "No successful queries"
This is actually OKAY - it means we need to use a different approach:
- See `graph_test_results.json` for details
- Check `STORAGE_ALTERNATIVES.md` for other options

---

## Files Created

- **.env.graph** - Your API key (private, in .gitignore)
- **setup_graph_api.sh** - Automated setup script
- **test_graph_subgraph.py** - Test queries
- **graph_test_results.json** - Query results (created after test)

---

## Security Notes

⚠️ **Keep your API key private!**
- Never commit `.env.graph` to git (already in .gitignore)
- Don't share your API key publicly
- Rotate keys if accidentally exposed

The Graph has usage limits on free tier:
- Check their pricing: https://thegraph.com/pricing/
- Free tier should be plenty for development/testing

---

## Quick Reference

```bash
# Get API key
open https://thegraph.com/studio/

# Setup
./setup_graph_api.sh

# Manual test
source .env.graph
export THE_GRAPH_API_KEY
python test_graph_subgraph.py

# View results
cat graph_test_results.json | python -m json.tool
```

---

**Ready?** Run `./setup_graph_api.sh` and let's test it!
