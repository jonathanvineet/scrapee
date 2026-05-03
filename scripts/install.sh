#!/bin/bash
# Scrapee CLI installer for macOS and Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/jonathanvineet/scrapee/main/scripts/install.sh | sh

set -e

REPO="jonathanvineet/scrapee"
BINARY_NAME="scrapee"
INSTALL_DIR="/usr/local/bin"
VERSION="v3.0.0"

echo "🦇 Installing scrapee..."

# Detect OS
OS=$(uname -s)
ARCH=$(uname -m)

# For now, use the repository binary directly (Darwin arm64 supported)
# In production, build multi-platform binaries and push to releases
case "$OS" in
  Darwin)
    if [ "$ARCH" = "arm64" ]; then
      # Download from GitHub raw content (v3.0.0 binary)
      BINARY_URL="https://raw.githubusercontent.com/${REPO}/main/releases/v3.0.0/scrapee"
    else
      echo "⚠️  Intel macOS support coming soon. Please build locally:"
      echo "   pip install PyInstaller && pyinstaller --onefile cli/scrapee.py --name scrapee"
      exit 1
    fi
    ;;
  Linux)
    echo "⚠️  Linux support coming soon. Please build locally:"
    echo "   pip install PyInstaller && pyinstaller --onefile cli/scrapee.py --name scrapee"
    exit 1
    ;;
  *)
    echo "❌ Unsupported OS: $OS"
    exit 1
    ;;
esac

# Create temp directory
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Download
echo "⬇️  Downloading binary..."
if ! curl -fsSL "$BINARY_URL" -o "$TEMP_DIR/$BINARY_NAME"; then
  echo "❌ Failed to download scrapee. Check your connection or retry."
  exit 1
fi

# Make executable
chmod +x "$TEMP_DIR/$BINARY_NAME"

# Install to system path (requires sudo)
echo "📦 Installing to $INSTALL_DIR..."
if ! sudo mv "$TEMP_DIR/$BINARY_NAME" "$INSTALL_DIR/$BINARY_NAME"; then
  echo "❌ Failed to install. Do you have sudo access?"
  exit 1
fi

# Verify installation
if ! command -v $BINARY_NAME &> /dev/null; then
  echo "❌ Installation failed. Check $INSTALL_DIR"
  exit 1
fi

echo ""
echo "✅ scrapee installed successfully!"
echo ""
echo "   Try:  scrapee --help"
echo ""
