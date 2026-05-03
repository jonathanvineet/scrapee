# Windows PowerShell Installer for Scrapee
# Usage: iwr https://yourdomain/install.ps1 | iex

$ProgressPreference = 'SilentlyContinue'

$Repo = "jonathanvineet/scrapee"
$BinaryName = "scrapee.exe"
$InstallDir = "$env:LOCALAPPDATA\scrapee"

Write-Host "🦇 Installing scrapee..." -ForegroundColor Cyan

# Create install directory
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}

# Detect architecture
$Arch = if ([Environment]::Is64BitProcess) { "x86-64" } else { "x86" }

# Download binary
$BinaryUrl = "https://github.com/$Repo/releases/latest/download/scrapee-windows-$Arch.exe"
$BinaryPath = Join-Path $InstallDir $BinaryName

Write-Host "⬇️  Downloading binary..." -ForegroundColor Cyan

try {
    Invoke-WebRequest -Uri $BinaryUrl -OutFile $BinaryPath
} catch {
    Write-Host "❌ Failed to download scrapee" -ForegroundColor Red
    Write-Host "   URL: $BinaryUrl" -ForegroundColor Red
    exit 1
}

# Add to PATH if not already there
$PathVar = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User)
if ($PathVar -notlike "*$InstallDir*") {
    Write-Host "📦 Adding to PATH..." -ForegroundColor Cyan
    $NewPath = "$PathVar;$InstallDir"
    [Environment]::SetEnvironmentVariable("Path", $NewPath, [EnvironmentVariableTarget]::User)
}

Write-Host ""
Write-Host "✅ scrapee installed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "   Location: $BinaryPath" -ForegroundColor Gray
Write-Host "   Try:      scrapee --help" -ForegroundColor Gray
Write-Host ""
Write-Host "⚠️  Restart your terminal for PATH changes to take effect." -ForegroundColor Yellow
Write-Host ""
