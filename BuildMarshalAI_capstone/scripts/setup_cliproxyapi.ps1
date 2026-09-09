param(
    [string]$InstallDirectory = "$env:USERPROFILE\BuildMarshalAI\CLIProxyAPI",
    [string]$ConfigPath = "$env:USERPROFILE\.cli-proxy-api\config.yaml"
)

$ErrorActionPreference = "Stop"
$repository = "router-for-me/CLIProxyAPI"
$release = Invoke-RestMethod "https://api.github.com/repos/$repository/releases/latest"
$asset = $release.assets | Where-Object {
    $_.name -match 'windows_amd64\.zip$'
} | Select-Object -First 1

if (-not $asset) {
    throw "The latest CLIProxyAPI release does not contain a Windows amd64 ZIP."
}

New-Item -ItemType Directory -Force -Path $InstallDirectory | Out-Null
$zipPath = Join-Path $InstallDirectory $asset.name
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
Expand-Archive -LiteralPath $zipPath -DestinationPath $InstallDirectory -Force
Remove-Item -LiteralPath $zipPath

$configDirectory = Split-Path -Parent $ConfigPath
New-Item -ItemType Directory -Force -Path $configDirectory | Out-Null
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    $template = Join-Path $PSScriptRoot "..\config\cliproxyapi.config.example.yaml"
    Copy-Item -LiteralPath $template -Destination $ConfigPath
    Write-Host "Created $ConfigPath. Replace the example api-keys value before starting."
}

$executable = Get-ChildItem -LiteralPath $InstallDirectory -Recurse -Filter "cli-proxy-api.exe" |
    Select-Object -First 1
if (-not $executable) {
    throw "CLIProxyAPI executable was not found after extraction."
}

Write-Host "Installed CLIProxyAPI $($release.tag_name) at $($executable.FullName)"
Write-Host "Next, authenticate Antigravity:"
Write-Host "  & '$($executable.FullName)' --config '$ConfigPath' --antigravity-login"
Write-Host "Then start the proxy:"
Write-Host "  & '$($executable.FullName)' --config '$ConfigPath'"

