#!/bin/bash

# Setup Lark CLI for Executor
# This script installs and configures lark-cli for use with Executor

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Setup Feishu/Lark CLI for Executor                    ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Check if npm is installed
echo "📦 Step 1: Checking npm..."
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install Node.js and npm first."
    echo "   Visit: https://nodejs.org/"
    exit 1
fi
echo "✅ npm is installed: $(npm --version)"
echo ""

# Step 2: Install lark-cli globally
echo "📦 Step 2: Installing lark-cli globally..."
npm install -g @larksuite/cli
echo "✅ lark-cli installed"
echo ""

# Step 3: Verify installation
echo "📦 Step 3: Verifying installation..."
if ! command -v lark-cli &> /dev/null; then
    echo "❌ lark-cli installation failed"
    exit 1
fi
echo "✅ lark-cli is available: $(lark-cli --version)"
echo ""

# Step 4: Initialize configuration
echo "📦 Step 4: Initialize lark-cli configuration..."
echo "   This will open a browser for OAuth authentication."
echo ""
echo "   If you want to use an existing application, you can run:"
echo "   $ lark-cli config init"
echo ""
echo "   For a new application setup, press Enter:"
read -p "Press Enter to continue with 'lark-cli config init --new'..."

lark-cli config init --new

echo ""
echo "✅ Configuration completed!"
echo ""

# Step 5: Verify connection
echo "📦 Step 5: Verifying connection..."
if lark-cli im ls-chats > /dev/null 2>&1; then
    echo "✅ Successfully connected to Feishu!"
    echo ""
    echo "Your chat groups:"
    lark-cli im ls-chats
else
    echo "⚠️  Could not verify connection. Please check your configuration:"
    echo "   $ cat ~/.lark/config.json"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Setup Complete! ✅                                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Available Feishu Skills in Executor:"
echo "  • lark-im         — Send Feishu messages"
echo "  • lark-doc        — Create/manage Feishu documents"
echo "  • lark-calendar   — Create calendar events"
echo ""
echo "For more information, see:"
echo "  📖 LARK_SKILLS_SETUP.md"
echo ""
echo "Test the integration:"
echo "  $ python3 demo_brain_executor_skills.py"
echo ""
