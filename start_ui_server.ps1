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
$preferredPort = if ($env:AUTOSUB_UI_PORT) { [int]$env:AUTOSUB_UI_PORT } else { 8777 }

# Stop old Autosub UI server processes before starting a fresh one.
$uiProcesses = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*autosub_zh.ui_server*' }
foreach ($proc in $uiProcesses) {
    try {
        Write-Host "Stopping old UI server process: $($proc.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    }
    catch {
        Write-Host "Could not stop process $($proc.ProcessId): $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

function Test-PortBindable {
    param([int]$Port)
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse('127.0.0.1'), $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

$candidatePorts = if ($env:AUTOSUB_UI_PORT) {
    @($preferredPort)
}
else {
    @($preferredPort) + (8778..8787)
}

$serverPort = $null
foreach ($port in $candidatePorts) {
    $portProcessIds = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $portProcessIds) {
        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            Write-Host "Stopping process on port ${port}: $processId ($($process.ProcessName))" -ForegroundColor Yellow
            Stop-Process -Id $processId -Force -ErrorAction Stop
        }
        catch {
            Write-Host "Could not stop PID $processId on port ${port}: $($_.Exception.Message)" -ForegroundColor DarkYellow
        }
    }

    Start-Sleep -Milliseconds 200
    if (Test-PortBindable -Port $port) {
        $serverPort = $port
        break
    }

    Write-Host "Port $port is not bindable, trying next port..." -ForegroundColor DarkYellow
}

if (-not $serverPort) {
    throw "No bindable UI port found. Set AUTOSUB_UI_PORT to another free local port."
}

$env:AUTOSUB_UI_PORT = [string]$serverPort

Write-Host "Starting Autosub UI server..." -ForegroundColor Cyan
Write-Host "Project root: $projectRoot" -ForegroundColor DarkGray
Write-Host "CUDA bin in PATH: $((($env:PATH -split ';') -contains $cudaBin))" -ForegroundColor DarkGray
Write-Host "HTTP_PROXY: $env:HTTP_PROXY" -ForegroundColor DarkGray
Write-Host "Open http://127.0.0.1:$serverPort" -ForegroundColor Green

python -m autosub_zh.ui_server
exit $LASTEXITCODE
