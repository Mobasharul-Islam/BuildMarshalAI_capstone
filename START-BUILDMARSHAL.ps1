param(
    [switch]$SkipPreparation,
    [switch]$StartBackend
)

$ErrorActionPreference = "Stop"
$packageRoot = $PSScriptRoot
$repoRoot = Join-Path $packageRoot "BuildMarshalAI_capstone"
$venvPython = Join-Path $repoRoot ".venv-gpu\Scripts\python.exe"
$proxyExe = Join-Path $packageRoot "cliproxyapi\cli-proxy-api.exe"
$proxyConfig = Join-Path $packageRoot "cliproxyapi\config.yaml"
$homeProxyConfig = Join-Path $env:USERPROFILE ".cli-proxy-api\config.yaml"
$notebook = Join-Path $repoRoot "backend\Local_Working_with_Document_Generation_CLIProxyAPI.ipynb"
$backendScript = Join-Path $repoRoot "backend\run_backend.py"
$frontendDir = Join-Path $repoRoot "frontend"
$logDir = Join-Path $packageRoot "logs"

if (-not $SkipPreparation) {
    & (Join-Path $packageRoot "PREPARE-TEAMMATE-PC.ps1")
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

# ==========================================================================
# Ports
# ==========================================================================
# Windows hands blocks of low TCP ports to Hyper-V's NAT driver at every boot.
# A port inside such a block cannot be bound by anything else -- bind() fails
# with WSAEACCES -- even though nothing is listening on it, and the blocks move
# from boot to boot. So "is anything listening?" is not the question to ask
# before starting a service; "can this port actually be bound?" is. Asking the
# wrong one is what made an unbindable port look like a service that had failed
# to start, and sent people off to re-authenticate something that was fine.

function Test-PortListening([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-PortBindable([int]$Port) {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start(); $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Get-ReservingRange([int]$Port) {
    foreach ($line in (netsh int ipv4 show excludedportrange protocol=tcp)) {
        if ($line -match '^\s*(\d+)\s+(\d+)') {
            $start = [int]$Matches[1]
            $end = [int]$Matches[2]
            if ($Port -ge $start -and $Port -le $end) { return "$start-$end" }
        }
    }
    return $null
}

function Find-FreePort([int[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        if (-not (Test-PortListening $candidate) -and (Test-PortBindable $candidate)) {
            return $candidate
        }
    }
    return 0
}

function Show-PortReservation([int]$Port, [string]$Service) {
    $range = Get-ReservingRange $Port
    $script = Join-Path $packageRoot "RESERVE-PORTS.ps1"
    Write-Host ""
    Write-Host "Port $Port is reserved by Windows, so $Service cannot bind to it." -ForegroundColor Yellow
    if ($range) {
        Write-Host "  Windows has excluded $range for Hyper-V/WSL on this boot." -ForegroundColor Yellow
    }
    Write-Host "  Nothing is listening on it, and nothing is wrong with the service" -ForegroundColor Yellow
    Write-Host "  or with its login. To claim the standard ports for good, run once" -ForegroundColor Yellow
    Write-Host "  as Administrator:" -ForegroundColor Yellow
    Write-Host "      powershell -ExecutionPolicy Bypass -File $script" -ForegroundColor Yellow
}

# Windows PowerShell's -Encoding UTF8 means "with a byte order mark", which a
# YAML parser is entitled to choke on and a <script> tag should not have to skip.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Set-YamlPort([string]$Path, [int]$Port) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $text = Get-Content -LiteralPath $Path -Raw
    $updated = [regex]::Replace($text, '(?m)^(\s*port:\s*)\d+', ('${1}' + $Port))
    if ($updated -ne $text) {
        [System.IO.File]::WriteAllText($Path, $updated, $utf8NoBom)
    }
}

function Show-LogTail([string]$Path, [string]$Label) {
    if ((Test-Path -LiteralPath $Path) -and (Get-Item -LiteralPath $Path).Length -gt 0) {
        Write-Host "  --- $Label ---" -ForegroundColor DarkGray
        Get-Content -LiteralPath $Path -Tail 15 | ForEach-Object {
            Write-Host "  $_" -ForegroundColor DarkGray
        }
    }
}

# ==========================================================================
# CLIProxyAPI
# ==========================================================================
# The configured port is the source of truth, not a number repeated here.
$proxyPort = 8317
if (Test-Path -LiteralPath $proxyConfig) {
    $match = [regex]::Match((Get-Content -LiteralPath $proxyConfig -Raw), '(?m)^\s*port:\s*(\d+)')
    if ($match.Success) { $proxyPort = [int]$match.Groups[1].Value }
}

if (-not (Test-PortListening $proxyPort)) {
    if (-not (Test-PortBindable $proxyPort)) {
        Show-PortReservation $proxyPort "CLIProxyAPI"
        # Only the backend talks to the proxy, and it is told the address below,
        # so moving the proxy costs nothing and needs no Administrator.
        $movedPort = Find-FreePort @(8787, 8822, 9317, 9787, 11317, 18317)
        if ($movedPort -eq 0) {
            throw "No free port for CLIProxyAPI. Run RESERVE-PORTS.ps1 as Administrator, or reboot."
        }
        Write-Host "  Moving CLIProxyAPI to port $movedPort." -ForegroundColor Cyan
        Set-YamlPort $proxyConfig $movedPort
        Set-YamlPort $homeProxyConfig $movedPort
        $proxyPort = $movedPort
    }

    # The proxy's own output is the only thing that explains a failed start, so
    # it is kept rather than thrown away with the hidden window.
    $proxyLog = Join-Path $logDir "cliproxyapi.out.log"
    $proxyErr = Join-Path $logDir "cliproxyapi.err.log"
    Start-Process -FilePath $proxyExe -ArgumentList @("-config", $proxyConfig) `
        -WorkingDirectory (Split-Path -Parent $proxyExe) -WindowStyle Hidden `
        -RedirectStandardOutput $proxyLog -RedirectStandardError $proxyErr

    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-PortListening $proxyPort) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }

    if (-not (Test-PortListening $proxyPort)) {
        Write-Host ""
        Write-Host "CLIProxyAPI did not reach port $proxyPort within 20 seconds." -ForegroundColor Red
        Show-LogTail $proxyErr "cliproxyapi.err.log"
        Show-LogTail $proxyLog "cliproxyapi.out.log"
        Write-Host "  Full logs: $logDir" -ForegroundColor Red
        Write-Host "  If the logs mention an expired or missing login, see START-HERE.md" -ForegroundColor Red
        Write-Host "  for the Antigravity re-authentication step." -ForegroundColor Red
        throw "CLIProxyAPI did not start on port $proxyPort."
    }
}

# Everything downstream reads this rather than assuming 8317.
$env:CLIPROXY_BASE_URL = "http://127.0.0.1:$proxyPort/v1"

# ==========================================================================
# Frontend and backend
# ==========================================================================
$frontendPort = 5500
if (-not (Test-PortListening $frontendPort)) {
    if (-not (Test-PortBindable $frontendPort)) {
        Show-PortReservation $frontendPort "the frontend"
        $movedPort = Find-FreePort @(5501, 5600, 5800, 15500)
        if ($movedPort -eq 0) { throw "No free port for the frontend." }
        Write-Host "  Serving the frontend on port $movedPort." -ForegroundColor Cyan
        $frontendPort = $movedPort
    }
    Start-Process -FilePath $venvPython `
        -ArgumentList @("-m", "http.server", "$frontendPort", "--directory", $frontendDir) `
        -WorkingDirectory $repoRoot -WindowStyle Hidden
}

$backendPort = 8000
if (-not (Test-PortListening $backendPort) -and -not (Test-PortBindable $backendPort)) {
    Show-PortReservation $backendPort "the backend"
    $movedPort = Find-FreePort @(8900, 8901, 9000, 9100, 18000)
    if ($movedPort -eq 0) { throw "No free port for the backend." }
    Write-Host "  Moving the backend to port $movedPort." -ForegroundColor Cyan
    $backendPort = $movedPort
}
$env:BUILDMARSHAL_PORT = "$backendPort"

# The browser cannot read an environment variable, so the port the backend was
# actually given is written where the frontend picks it up. It is written every
# time, so a move back to 8000 clears a stale one.
$localConfig = Join-Path $frontendDir "local-config.js"
$localConfigLines = @(
    "// Written by START-BUILDMARSHAL.ps1 -- do not edit.",
    "// The backend port this machine ended up with, for when Windows has",
    "// reserved 8000. A URL entered on the sign-in screen still wins over it.",
    ("window.BMARSHAL_API_URL = 'http://127.0.0.1:" + $backendPort + "';")
)
[System.IO.File]::WriteAllLines($localConfig, $localConfigLines, $utf8NoBom)

if ($StartBackend -and -not (Test-PortListening $backendPort)) {
    $backendLog = Join-Path $logDir "backend.out.log"
    $backendErr = Join-Path $logDir "backend.err.log"
    Start-Process -FilePath $venvPython -ArgumentList @($backendScript) `
        -WorkingDirectory (Split-Path -Parent $backendScript) -WindowStyle Hidden `
        -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr
    # Loading ColPali onto the GPU takes a couple of minutes, so wait for the
    # port instead of reporting "not running" the instant after launching it.
    Write-Host "Starting backend (loading ColPali onto the GPU, this takes a minute or two)..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddMinutes(5)
    while (-not (Test-PortListening $backendPort) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
    }
    if (-not (Test-PortListening $backendPort)) {
        Write-Host "The backend did not reach port $backendPort within 5 minutes." -ForegroundColor Yellow
        Show-LogTail $backendErr "backend.err.log"
        Write-Host "  Full logs: $logDir" -ForegroundColor Yellow
        Write-Host "  To watch it start, run it in the foreground:" -ForegroundColor Yellow
        Write-Host "    BUILDMARSHAL_PORT=$backendPort  CLIPROXY_BASE_URL=$env:CLIPROXY_BASE_URL" -ForegroundColor Yellow
        Write-Host "    & '$venvPython' '$backendScript'" -ForegroundColor Yellow
    }
}

$code = Get-Command code -ErrorAction SilentlyContinue
if ($code -and -not $StartBackend -and -not (Test-PortListening $backendPort)) {
    # Launched from here so the notebook kernel inherits the ports chosen above.
    Start-Process -FilePath $code.Source -ArgumentList @($notebook) -WorkingDirectory $repoRoot
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "BuildMarshalAI Services Status" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "CLIProxyAPI : http://127.0.0.1:$proxyPort/v1" -ForegroundColor Green
Write-Host "Frontend    : http://localhost:$frontendPort" -ForegroundColor Green
if (Test-PortListening $backendPort) {
    Write-Host "Backend API : http://127.0.0.1:$backendPort" -ForegroundColor Green
    Write-Host "API Docs    : http://127.0.0.1:$backendPort/docs" -ForegroundColor Green
    Write-Host "Health      : http://127.0.0.1:$backendPort/api/health" -ForegroundColor Green
} else {
    Write-Host "Backend     : not running - open the notebook and Run All, or rerun with -StartBackend" -ForegroundColor Yellow
    Write-Host "              (it will use port $backendPort)" -ForegroundColor Yellow
}
if ($backendPort -ne 8000) {
    Write-Host ""
    Write-Host "Note: Windows has reserved port 8000, so the backend is on $backendPort." -ForegroundColor Yellow
    Write-Host "The frontend picks this up by itself. If you have ever set a backend URL" -ForegroundColor Yellow
    Write-Host "by hand, clear it on the sign-in screen or set it to http://127.0.0.1:$backendPort." -ForegroundColor Yellow
    Write-Host "RESERVE-PORTS.ps1, run once as Administrator, gets the usual ports back." -ForegroundColor Yellow
}
Write-Host "Sign in at http://localhost:$frontendPort (each account has its own data)." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
