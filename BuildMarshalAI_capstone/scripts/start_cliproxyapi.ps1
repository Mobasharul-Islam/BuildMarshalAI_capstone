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

if (Get-NetTCPConnection -LocalPort 8317 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "CLIProxyAPI is already running at http://127.0.0.1:8317"
    exit 0
}

Write-Host "Starting CLIProxyAPI at http://127.0.0.1:8317"
Write-Host "Keep this window open while BuildMarshalAI is running."
& $executable -config $config
