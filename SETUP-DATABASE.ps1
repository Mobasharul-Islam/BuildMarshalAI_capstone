# Creates BuildMarshalAI's PostgreSQL role and databases on this machine and
# records their URLs in secrets\runtime-secrets.json. Safe to run again.
#
#   powershell -ExecutionPolicy Bypass -File .\SETUP-DATABASE.ps1
#
# Needs PostgreSQL (14 or newer) running locally and the password of its
# superuser ("postgres"); that password is asked for and never stored.
param(
    [string]$HostName = "localhost",
    [int]$Port = 5432,
    [string]$AdminUser = "postgres"
)

$ErrorActionPreference = "Stop"
$packageRoot = $PSScriptRoot
$repoRoot = Join-Path $packageRoot "BuildMarshalAI_capstone"
$venvPython = Join-Path $repoRoot ".venv-gpu\Scripts\python.exe"
$secretsPath = Join-Path $packageRoot "secrets\runtime-secrets.json"

if (-not (Test-Path -LiteralPath $venvPython)) {
    & (Join-Path $packageRoot "CREATE-ENVIRONMENT.ps1")
}

Write-Host "Setting up the BuildMarshalAI database on ${HostName}:$Port ..." -ForegroundColor Cyan
& $venvPython (Join-Path $repoRoot "scripts\setup_database.py") `
    --host $HostName --port $Port --admin-user $AdminUser --secrets $secretsPath
if ($LASTEXITCODE -ne 0) { throw "Database setup failed." }

& $venvPython (Join-Path $repoRoot "scripts\check_database.py") --secrets $secretsPath
if ($LASTEXITCODE -ne 0) { throw "The database was set up but does not answer." }
Write-Host "Database ready. Run .\START-BUILDMARSHAL.ps1 (or .\PREPARE-TEAMMATE-PC.ps1 to export the URL)." -ForegroundColor Green
