$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Split-Path -Parent $projectRoot)

$cudaBin = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin'
if (Test-Path $cudaBin) {
    if (-not (($env:PATH -split ';') -contains $cudaBin)) {
        $env:PATH = $cudaBin + ';' + $env:PATH
    }
}

$env:HTTP_PROXY = 'http://127.0.0.1:7890'
$env:HTTPS_PROXY = 'http://127.0.0.1:7890'

Write-Host "Starting Autosub UI server..." -ForegroundColor Cyan
Write-Host "Project root: $projectRoot" -ForegroundColor DarkGray
Write-Host "CUDA bin in PATH: $((($env:PATH -split ';') -contains $cudaBin))" -ForegroundColor DarkGray
Write-Host "HTTP_PROXY: $env:HTTP_PROXY" -ForegroundColor DarkGray
Write-Host "Open http://127.0.0.1:8777" -ForegroundColor Green

python -m autosub_zh.ui_server
