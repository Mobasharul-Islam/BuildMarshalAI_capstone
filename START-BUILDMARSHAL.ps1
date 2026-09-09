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
$notebook = Join-Path $repoRoot "backend\Local_Working_with_Document_Generation_CLIProxyAPI.ipynb"
$backendScript = Join-Path $repoRoot "backend\run_backend.py"

if (-not $SkipPreparation) {
    & (Join-Path $packageRoot "PREPARE-TEAMMATE-PC.ps1")
}

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-Port 8317)) {
    Start-Process -FilePath $proxyExe -ArgumentList @("-config", $proxyConfig) -WorkingDirectory (Split-Path -Parent $proxyExe) -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-Port 8317) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-Port 8317)) {
        throw "CLIProxyAPI did not start on port 8317. See START-HERE.md for re-authentication instructions."
    }
}

if (-not (Test-Port 5500)) {
    Start-Process -FilePath $venvPython -ArgumentList @("-m", "http.server", "5500", "--directory", (Join-Path $repoRoot "frontend")) -WorkingDirectory $repoRoot -WindowStyle Hidden
}

if ($StartBackend -and -not (Test-Port 8000)) {
    Start-Process -FilePath $venvPython -ArgumentList @($backendScript) -WorkingDirectory (Split-Path -Parent $backendScript) -WindowStyle Hidden
    # Loading ColPali onto the GPU takes a couple of minutes, so wait for the
    # port instead of reporting "not running" the instant after launching it.
    Write-Host "Starting backend (loading ColPali onto the GPU, this takes a minute or two)..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddMinutes(5)
    while (-not (Test-Port 8000) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    if (-not (Test-Port 8000)) {
        Write-Host "The backend did not reach port 8000 within 5 minutes. Run it in the foreground to see why:" -ForegroundColor Yellow
        Write-Host "  & '$venvPython' '$backendScript'" -ForegroundColor Yellow
    }
}

$code = Get-Command code -ErrorAction SilentlyContinue
if ($code -and -not $StartBackend -and -not (Test-Port 8000)) {
    Start-Process -FilePath $code.Source -ArgumentList @($notebook) -WorkingDirectory $repoRoot
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "BuildMarshalAI Services Status" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "CLIProxyAPI : http://127.0.0.1:8317/v1" -ForegroundColor Green
Write-Host "Frontend    : http://localhost:5500" -ForegroundColor Green
if (Test-Port 8000) {
    Write-Host "Backend API : http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "API Docs    : http://127.0.0.1:8000/docs" -ForegroundColor Green
    Write-Host "Health      : http://127.0.0.1:8000/api/health" -ForegroundColor Green
} else {
    Write-Host "Backend     : not running - open the notebook and Run All, or rerun with -StartBackend" -ForegroundColor Yellow
}
Write-Host "Sign in at http://localhost:5500 (each account has its own data)." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

