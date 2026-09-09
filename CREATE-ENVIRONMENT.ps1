$ErrorActionPreference = "Stop"

$packageRoot = $PSScriptRoot
$repoRoot = Join-Path $packageRoot "BuildMarshalAI_capstone"
$venvRoot = Join-Path $repoRoot ".venv-gpu"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$requirements = Join-Path $packageRoot "requirements-handover.txt"

if (-not (Test-Path -LiteralPath $requirements)) {
    throw "Missing package manifest: $requirements"
}

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $pyLauncher) {
    throw "Python launcher not found. Install 64-bit Python 3.13 from python.org and enable the py launcher."
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating Python 3.13 environment at $venvRoot" -ForegroundColor Cyan
    & $pyLauncher.Source -3.13 -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python 3.13 environment." }
}

& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Could not update pip." }

Write-Host "Installing CUDA-enabled PyTorch..." -ForegroundColor Cyan
& $venvPython -m pip install --index-url https://download.pytorch.org/whl/cu130 torch==2.12.1+cu130 torchvision==0.27.1+cu130
if ($LASTEXITCODE -ne 0) { throw "CUDA PyTorch installation failed." }

Write-Host "Installing BuildMarshalAI packages..." -ForegroundColor Cyan
& $venvPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "BuildMarshalAI package installation failed." }

& $venvPython -m ipykernel install --user --name buildmarshal-handover --display-name "BuildMarshalAI Handover GPU (Python 3.13)"
if ($LASTEXITCODE -ne 0) { throw "Could not register the Jupyter kernel." }

& $venvPython -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"
if ($LASTEXITCODE -ne 0) { throw "Environment import validation failed." }

Write-Host "Environment created successfully." -ForegroundColor Green
Write-Host "If CUDA available is False, update the NVIDIA driver before running the backend." -ForegroundColor Yellow

