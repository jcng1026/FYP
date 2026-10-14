<#
    setup_ollama.ps1 - install the local AI feedback runtime for MarkAssist.

    Ollama is a native application (not a Python/pip package), so it cannot be
    installed through requirements.txt. This script downloads and installs it
    with terminal commands, then pulls the llama3.2 model MarkAssist uses for
    Kertas 2 natural-language feedback.

    Ollama is OPTIONAL: without it, feedback falls back to built-in offline
    templates and marking, review and results are unaffected.

    Usage (from a PowerShell prompt):
        powershell -ExecutionPolicy Bypass -File scripts\setup_ollama.ps1
#>

$ErrorActionPreference = "Stop"
$Model = "llama3.2"

function Test-Ollama {
    if (Get-Command ollama -ErrorAction SilentlyContinue) { return $true }
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe")) {
        if (Test-Path $p) { return $true }
    }
    return $false
}

Write-Host "== MarkAssist local AI (Ollama) setup ==" -ForegroundColor Cyan

# 1) Install Ollama if it is not already present -----------------------------
if (Test-Ollama) {
    Write-Host "Ollama is already installed - skipping install." -ForegroundColor Green
}
else {
    Write-Host "Installing Ollama..." -ForegroundColor Yellow
    $installed = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
            $installed = $true
        } catch { Write-Host "winget install failed, falling back to the installer download..." }
    }
    if (-not $installed) {
        $setup = Join-Path $env:TEMP "OllamaSetup.exe"
        Write-Host "Downloading the Ollama installer..."
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup
        Write-Host "Running the installer..."
        Start-Process -FilePath $setup -ArgumentList "/silent" -Wait
    }
    # make the freshly-installed ollama.exe reachable in this session
    $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama;$env:ProgramFiles\Ollama"
}

# 2) Pull the feedback model -------------------------------------------------
Write-Host "Pulling the '$Model' model (~2 GB, one-time download)..." -ForegroundColor Yellow
ollama pull $Model

Write-Host ""
Write-Host "Done. MarkAssist will start Ollama automatically and use '$Model' for feedback." -ForegroundColor Green
