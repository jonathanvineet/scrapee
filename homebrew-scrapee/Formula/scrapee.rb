class Scrapee < Formula
  desc "AI-powered context engine CLI — MCP client"
  homepage "https://github.com/jonathanvineet/scrapee"
  url "https://github.com/jonathanvineet/scrapee/releases/download/v1.0.0/scrapee-darwin-x86-64"
  sha256 "REPLACE_WITH_SHA256_HASH"
  version "1.0.0"

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/jonathanvineet/scrapee/releases/download/v1.0.0/scrapee-darwin-arm64"
      sha256 "REPLACE_WITH_ARM_SHA256"
    end
  end

  def install
    bin.install "scrapee-darwin-x86-64" => "scrapee" if OS.mac? && Hardware::CPU.intel?
    bin.install "scrapee-darwin-arm64" => "scrapee" if OS.mac? && Hardware::CPU.arm?
  end

  test do
    system "#{bin}/scrapee", "--version"
  end
end
