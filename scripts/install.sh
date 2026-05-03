#!/bin/bash
# Scrapee CLI installer for macOS and Linux
# Usage: curl -fsSL https://yourdomain/install.sh | sh

set -e

REPO="jonathanvineet/scrapee"
BINARY_NAME="scrapee"
INSTALL_DIR="/usr/local/bin"

echo "🦇 Installing scrapee..."

# Detect OS
OS=$(uname -s)
ARCH=$(uname -m)

case "$OS" in
  Darwin)
    if [ "$ARCH" = "arm64" ]; then
      BINARY_URL="https://github.com/${REPO}/releases/latest/download/scrapee-darwin-arm64"
    else
      BINARY_URL="https://github.com/${REPO}/releases/latest/download/scrapee-darwin-x86"
    fi
    ;;
  Linux)
    if [ "$ARCH" = "aarch64" ]; then
      BINARY_URL="https://github.com/${REPO}/releases/latest/download/scrapee-linux-arm64"
    else
      BINARY_URL="https://github.com/${REPO}/releases/latest/download/scrapee-linux-x86"
    fi
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
