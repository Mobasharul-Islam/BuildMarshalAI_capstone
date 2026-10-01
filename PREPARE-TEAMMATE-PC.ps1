$ErrorActionPreference = "Stop"

$packageRoot = $PSScriptRoot
$repoRoot = Join-Path $packageRoot "BuildMarshalAI_capstone"
$secretsPath = Join-Path $packageRoot "secrets\runtime-secrets.json"
$oauthPath = Join-Path $packageRoot "google-oauth\client_secret.json"
$proxyRoot = Join-Path $packageRoot "cliproxyapi"
$proxyAuthSource = Join-Path $proxyRoot "auth"
$proxyUserRoot = Join-Path $env:USERPROFILE ".cli-proxy-api"
$venvPython = Join-Path $repoRoot ".venv-gpu\Scripts\python.exe"
$notebook = Join-Path $repoRoot "backend\Local_Working_with_Document_Generation_CLIProxyAPI.ipynb"

Write-Host "Preparing BuildMarshalAI handover..." -ForegroundColor Cyan

foreach ($requiredPath in @($repoRoot, $secretsPath, $oauthPath, $proxyRoot, $notebook)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required handover item is missing: $requiredPath"
    }
}

$runtimeSecrets = Get-Content -Raw -LiteralPath $secretsPath | ConvertFrom-Json
$oauthDocument = Get-Content -Raw -LiteralPath $oauthPath | ConvertFrom-Json
$oauth = if ($oauthDocument.web) { $oauthDocument.web } elseif ($oauthDocument.installed) { $oauthDocument.installed } else { $null }
if (-not $oauth -or -not $oauth.client_id -or -not $oauth.client_secret) {
    throw "The bundled Google OAuth client file is invalid."
}

$environment = [ordered]@{
    GOOGLE_CLIENT_ID = [string]$oauth.client_id
    GOOGLE_CLIENT_SECRET = [string]$oauth.client_secret
    GOOGLE_TOKEN_ENCRYPTION_KEY = [string]$runtimeSecrets.GOOGLE_TOKEN_ENCRYPTION_KEY
    GOOGLE_ALLOWED_ORIGINS = [string]$runtimeSecrets.GOOGLE_ALLOWED_ORIGINS
    MICROSOFT_CLIENT_ID = [string]$runtimeSecrets.MICROSOFT_CLIENT_ID
    MICROSOFT_CLIENT_SECRET = [string]$runtimeSecrets.MICROSOFT_CLIENT_SECRET
    MICROSOFT_TENANT_ID = [string]$runtimeSecrets.MICROSOFT_TENANT_ID
    MICROSOFT_ALLOWED_ORIGINS = [string]$runtimeSecrets.MICROSOFT_ALLOWED_ORIGINS
    CLIPROXY_BASE_URL = [string]$runtimeSecrets.CLIPROXY_BASE_URL
    CLIPROXY_API_KEY = [string]$runtimeSecrets.CLIPROXY_API_KEY
    CLIPROXY_MODEL = [string]$runtimeSecrets.CLIPROXY_MODEL
    CLIPROXY_TIMEOUT_SECONDS = [string]$runtimeSecrets.CLIPROXY_TIMEOUT_SECONDS
    BUILDMARSHAL_DOCGEN_MAX_TOKENS = [string]$runtimeSecrets.BUILDMARSHAL_DOCGEN_MAX_TOKENS
    # Every record lives in PostgreSQL; SETUP-DATABASE.ps1 records these.
    BUILDMARSHAL_DATABASE_URL = [string]$runtimeSecrets.BUILDMARSHAL_DATABASE_URL
    BUILDMARSHAL_TEST_DATABASE_URL = [string]$runtimeSecrets.BUILDMARSHAL_TEST_DATABASE_URL
    BUILDMARSHAL_DEMO_DATABASE_URL = [string]$runtimeSecrets.BUILDMARSHAL_DEMO_DATABASE_URL
    BUILDMARSHAL_DATA_DIR = (Join-Path $repoRoot ".buildmarshal_runtime\buildmarshal")
    HF_HOME = (Join-Path $repoRoot ".buildmarshal_runtime\hf_cache")
}

# CLIPROXY_BASE_URL is deliberately not persisted when it points at this
# machine. The proxy's port is not fixed -- Windows reserves blocks of low
# ports for Hyper-V at every boot, so the launcher moves the proxy when it has
# to -- and a value stored in the user environment outranks the config the
# proxy was actually started from, in every shell and every notebook kernel
# opened afterwards. The backend reads the port from cliproxyapi\config.yaml
# instead. A remote value, such as a Kaggle or ngrok tunnel, is still kept.
$loopbackUrl = '^https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)'
foreach ($item in $environment.GetEnumerator()) {
    if (-not $item.Value) { continue }
    if ($item.Key -eq "CLIPROXY_BASE_URL" -and $item.Value -match $loopbackUrl) {
        # Clear one an earlier run stored, which would otherwise go on pinning
        # a port the proxy has since moved off.
        $stored = [Environment]::GetEnvironmentVariable($item.Key, "User")
        if ($stored -match $loopbackUrl) {
            Write-Host "Clearing stale $($item.Key)=$stored from the user environment." -ForegroundColor DarkGray
            [Environment]::SetEnvironmentVariable($item.Key, $null, "User")
        }
        [Environment]::SetEnvironmentVariable($item.Key, $null, "Process")
        continue
    }
    [Environment]::SetEnvironmentVariable($item.Key, $item.Value, "Process")
    [Environment]::SetEnvironmentVariable($item.Key, $item.Value, "User")
}

New-Item -ItemType Directory -Force -Path $proxyUserRoot | Out-Null
Get-ChildItem -LiteralPath $proxyAuthSource -Filter "antigravity-*.json" -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $proxyUserRoot $_.Name) -Force
}
Copy-Item -LiteralPath (Join-Path $proxyRoot "config.yaml") -Destination (Join-Path $proxyUserRoot "config.yaml") -Force

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "The GPU environment has not been created yet." -ForegroundColor Yellow
    & (Join-Path $packageRoot "CREATE-ENVIRONMENT.ps1")
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Environment creation did not produce $venvPython"
}

& $venvPython -m ipykernel install --user --name buildmarshal-handover --display-name "BuildMarshalAI Handover GPU (Python 3.13)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not register the BuildMarshalAI Jupyter kernel."
}

$dataRoot = Join-Path $repoRoot ".buildmarshal_runtime\buildmarshal"
$modelIndex = Join-Path $dataRoot "hf_models\colpaligemma-3b-pt-448-base\model.safetensors.index.json"
$adapter = Join-Path $dataRoot "hf_models\colpali-v1.2\adapter_model.safetensors"
foreach ($requiredData in @($modelIndex, $adapter)) {
    if (-not (Test-Path -LiteralPath $requiredData)) {
        throw "Required offline runtime data is missing: $requiredData"
    }
}

# Every record -- accounts, projects, tasks, documents, linked Google and
# Microsoft accounts (encrypted) -- lives in PostgreSQL. Create the database on
# first use, then make sure it answers before anything tries to start.
if (-not $runtimeSecrets.BUILDMARSHAL_DATABASE_URL) {
    Write-Host "No BuildMarshalAI database yet; creating one (you will be asked for the PostgreSQL superuser password)." -ForegroundColor Yellow
    & (Join-Path $packageRoot "SETUP-DATABASE.ps1")
    $runtimeSecrets = Get-Content -Raw -LiteralPath $secretsPath | ConvertFrom-Json
    foreach ($name in @("BUILDMARSHAL_DATABASE_URL", "BUILDMARSHAL_TEST_DATABASE_URL", "BUILDMARSHAL_DEMO_DATABASE_URL")) {
        $value = [string]$runtimeSecrets.$name
        if ($value) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
            [Environment]::SetEnvironmentVariable($name, $value, "User")
        }
    }
}
& $venvPython (Join-Path $repoRoot "scripts\check_database.py") --secrets $secretsPath
if ($LASTEXITCODE -ne 0) {
    throw "The BuildMarshalAI database does not answer. Start the PostgreSQL service (services.msc), or run .\SETUP-DATABASE.ps1."
}

Write-Host "Preparation complete." -ForegroundColor Green
Write-Host "Secrets installed without displaying their values."
Write-Host "Jupyter kernel: BuildMarshalAI Handover GPU (Python 3.13)"
Write-Host "Next: run .\START-BUILDMARSHAL.ps1"
