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

function Test-PythonInterpreter {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    if (-not $Command) {
        return $false
    }

    try {
        & $Command @Arguments *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

$pythonCandidates = @(
    @{
        Command  = (Get-Command python -ErrorAction SilentlyContinue).Source
        Arguments = @('-c', 'import yt_dlp')
    },
    @{
        Command  = 'C:\Users\bulbel\AppData\Local\Programs\Python\Python311\python.exe'
        Arguments = @('-c', 'import yt_dlp')
    },
    @{
        Command  = 'py'
        Arguments = @('-3.11', '-c', 'import yt_dlp')
    }
)

$pythonCommand = $null
$pythonArgs = @()
foreach ($candidate in $pythonCandidates) {
    if (-not (Test-PythonInterpreter -Command $candidate.Command -Arguments $candidate.Arguments)) {
        continue
    }

    $pythonCommand = $candidate.Command
    if ($candidate.Command -eq 'py') {
        $pythonArgs = @('-3.11')
    }
    break
}

if (-not $pythonCommand) {
    throw 'No suitable Python interpreter with yt_dlp found. Install the project dependencies first.'
}

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
Write-Host "Python: $pythonCommand $($pythonArgs -join ' ')" -ForegroundColor DarkGray
Write-Host "CUDA bin in PATH: $((($env:PATH -split ';') -contains $cudaBin))" -ForegroundColor DarkGray
Write-Host "HTTP_PROXY: $env:HTTP_PROXY" -ForegroundColor DarkGray
Write-Host "Open http://127.0.0.1:$serverPort" -ForegroundColor Green

if ($pythonCommand -eq 'py') {
    & $pythonCommand @pythonArgs -m autosub_zh.ui_server
}
else {
    & $pythonCommand -m autosub_zh.ui_server
}
exit $LASTEXITCODE
