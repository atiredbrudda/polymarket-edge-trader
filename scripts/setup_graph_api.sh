#!/bin/bash
# Setup script for The Graph API testing

set -e

echo "=================================="
echo "The Graph API Key Setup"
echo "=================================="
echo ""

# Check if .env.graph exists
if [ ! -f .env.graph ]; then
    echo "❌ .env.graph file not found!"
    echo ""
    echo "Creating template..."
    cat > .env.graph << 'EOF'
# The Graph API Configuration
#
# To get your API key:
# 1. Go to https://thegraph.com/studio/
# 2. Click "Connect Wallet" or "Sign in"
# 3. Go to "API Keys" section in dashboard
# 4. Click "Create API Key"
# 5. Copy the key and paste it below
#
THE_GRAPH_API_KEY=your-api-key-here
EOF
    echo "✅ Created .env.graph template"
    echo ""
fi

# Check if API key is set
source .env.graph 2>/dev/null || true

if [ "$THE_GRAPH_API_KEY" = "your-api-key-here" ] || [ -z "$THE_GRAPH_API_KEY" ]; then
    echo "⚠️  API key not configured yet!"
    echo ""
    echo "Follow these steps:"
    echo ""
    echo "1. Open your browser and go to:"
    echo "   👉 https://thegraph.com/studio/"
    echo ""
    echo "2. Sign in with one of these methods:"
    echo "   • Connect Wallet (MetaMask, WalletConnect, etc.)"
    echo "   • Email/social login (if available)"
    echo ""
    echo "3. Once logged in, click 'API Keys' in the sidebar"
    echo ""
    echo "4. Click 'Create API Key' or use existing key"
    echo ""
    echo "5. Copy your API key"
    echo ""
    echo "6. Edit .env.graph file and replace 'your-api-key-here' with your key:"
    echo "   nano .env.graph"
    echo "   (or use any text editor)"
    echo ""
    echo "7. Run this script again: ./setup_graph_api.sh"
    echo ""
    exit 1
fi

# API key is set - test it!
echo "✅ API key found: ${THE_GRAPH_API_KEY:0:10}..."
echo ""
echo "Testing connection to Polymarket subgraph..."
echo ""

# Export for Python script
export THE_GRAPH_API_KEY

# Run test
if [ -f test_graph_subgraph.py ]; then
    echo "Running test_graph_subgraph.py..."
    source .venv/bin/activate 2>/dev/null || true
    python test_graph_subgraph.py
else
    echo "❌ test_graph_subgraph.py not found!"
    exit 1
fi
