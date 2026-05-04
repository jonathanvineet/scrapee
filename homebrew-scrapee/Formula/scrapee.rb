class Scrapee < Formula
  desc "🦇 Context engine CLI — Boot system + MCP orchestrator"
  homepage "https://github.com/jonathanvineet/scrapee"
  version "3.0.0"
  
  on_macos do
    if Hardware::CPU.arm?
      url "https://raw.githubusercontent.com/jonathanvineet/scrapee/main/releases/v3.0.0/scrapee"
      sha256 "98ed65f5ed970be561d68eda5717bfd67e85bd81189c66ff12a7b5dad0ffcae2"
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

