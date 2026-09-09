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
    BUILDMARSHAL_DATA_DIR = (Join-Path $repoRoot ".buildmarshal_runtime\buildmarshal")
    HF_HOME = (Join-Path $repoRoot ".buildmarshal_runtime\hf_cache")
}

foreach ($item in $environment.GetEnumerator()) {
    if ($item.Value) {
        [Environment]::SetEnvironmentVariable($item.Key, $item.Value, "Process")
        [Environment]::SetEnvironmentVariable($item.Key, $item.Value, "User")
    }
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

# Connected Google accounts live in the encrypted store of the account that owns
# them. Before the first backend start that is still the pre-migration file at
# the data root; afterwards it sits under accounts\<account_id>\. Accept either,
# and treat "none connected yet" as a warning rather than a hard stop so a fresh
# install can start and connect one from the UI.
$legacyTokenStore = Join-Path $dataRoot "google_workspace_accounts.enc"
$accountsRoot = Join-Path $dataRoot "accounts"
$accountTokenStores = @()
if (Test-Path -LiteralPath $accountsRoot) {
    $accountTokenStores = @(Get-ChildItem -LiteralPath $accountsRoot -Filter "google_workspace_accounts.enc" -File -Recurse -ErrorAction SilentlyContinue)
}
if (-not (Test-Path -LiteralPath $legacyTokenStore) -and $accountTokenStores.Count -eq 0) {
    Write-Host "No connected Google account found yet. Sign in, then connect one from Google Workspace in the app." -ForegroundColor Yellow
}

Write-Host "Preparation complete." -ForegroundColor Green
Write-Host "Secrets installed without displaying their values."
Write-Host "Jupyter kernel: BuildMarshalAI Handover GPU (Python 3.13)"
Write-Host "Next: run .\START-BUILDMARSHAL.ps1"
