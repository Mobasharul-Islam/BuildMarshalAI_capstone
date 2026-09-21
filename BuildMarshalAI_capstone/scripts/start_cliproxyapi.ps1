$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$handoverRoot = Split-Path -Parent $repoRoot
$bundledExecutable = Join-Path $handoverRoot "cliproxyapi\cli-proxy-api.exe"
$bundledConfig = Join-Path $handoverRoot "cliproxyapi\config.yaml"
$executable = if (Test-Path -LiteralPath $bundledExecutable) {
    $bundledExecutable
} else {
    Join-Path $env:USERPROFILE "BuildMarshalAI\CLIProxyAPI\cli-proxy-api.exe"
}
$config = if (Test-Path -LiteralPath $bundledConfig) {
    $bundledConfig
} else {
    Join-Path $env:USERPROFILE ".cli-proxy-api\config.yaml"
}

if (-not (Test-Path -LiteralPath $executable)) {
    throw "CLIProxyAPI is not installed. Run scripts\setup_cliproxyapi.ps1 first."
}
if (-not (Test-Path -LiteralPath $config)) {
    throw "CLIProxyAPI configuration is missing: $config"
}

# The port comes from the configuration the proxy is about to read, so the two
# cannot drift -- START-BUILDMARSHAL.ps1 rewrites it when Windows has reserved
# the usual one.
$port = 8317
$match = [regex]::Match((Get-Content -LiteralPath $config -Raw), '(?m)^\s*port:\s*(\d+)')
if ($match.Success) { $port = [int]$match.Groups[1].Value }

if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "CLIProxyAPI is already running at http://127.0.0.1:$port"
    exit 0
}

# Windows hands blocks of low ports to Hyper-V at boot and then refuses to bind
# them, with nothing listening. Saying so here beats letting the proxy exit with
# "an attempt was made to access a socket in a way forbidden by its access
# permissions" and having that read as a broken install or an expired login.
try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    $listener.Start(); $listener.Stop()
} catch {
    Write-Host "Port $port is reserved by Windows; nothing is listening on it." -ForegroundColor Yellow
    foreach ($line in (netsh int ipv4 show excludedportrange protocol=tcp)) {
        if ($line -match '^\s*(\d+)\s+(\d+)') {
            if ($port -ge [int]$Matches[1] -and $port -le [int]$Matches[2]) {
                Write-Host "  It falls inside the excluded range $($Matches[1])-$($Matches[2])." -ForegroundColor Yellow
            }
        }
    }
    Write-Host "  Run RESERVE-PORTS.ps1 as Administrator to claim it back," -ForegroundColor Yellow
    Write-Host "  or use START-BUILDMARSHAL.ps1, which moves the proxy to a free port." -ForegroundColor Yellow
    throw "Cannot bind port $port."
}

Write-Host "Starting CLIProxyAPI at http://127.0.0.1:$port"
Write-Host "Keep this window open while BuildMarshalAI is running."
& $executable -config $config
