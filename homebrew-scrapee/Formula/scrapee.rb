class Scrapee < Formula
  desc "🦇 Context engine CLI — Boot system + MCP orchestrator"
  homepage "https://github.com/jonathanvineet/scrapee"
  version "3.0.0"
  
  on_macos do
    if Hardware::CPU.arm?
      url "https://raw.githubusercontent.com/jonathanvineet/scrapee/main/releases/v3.0.0/scrapee"
      sha256 "74849be606c9504cf7233a1ebe27263f9cdc5b763560421c21b2bb7d2584d79a"
    else
      # Intel macOS - build from source or use precompiled
      url "https://raw.githubusercontent.com/jonathanvineet/scrapee/main/cli/scrapee.py"
      sha256 "placeholder_intel"
      # For now, require building from source on Intel
      depends_on "python@3.11"
    end
  end

  on_linux do
    url "https://raw.githubusercontent.com/jonathanvineet/scrapee/main/cli/scrapee.py"
    sha256 "placeholder_linux"
    depends_on "python@3.11"
  end

  def install
    if OS.mac? && Hardware::CPU.arm?
      bin.install "scrapee"
    else
      # Build from source on non-ARM systems
      # Copy Python CLI and wrap in executable
      system "pip install -q requests"
      bin.write_exec_script "cli/scrapee.py"
    end
  end

  test do
    system "#{bin}/scrapee", "--help"
  end
end

