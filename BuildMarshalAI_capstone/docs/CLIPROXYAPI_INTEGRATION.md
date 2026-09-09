# BuildMarshalAI with CLIProxyAPI

The CLIProxyAPI backend variant keeps ColPali and ChromaDB for retrieval and
replaces only Qwen2.5-VL generation. Chat, document generation, Gmail drafting,
and Calendar interpretation continue to use the shared `vl_generate` function.

## Files

- Original notebook: `backend/Dual_t4_Working_with_Document_Generation.ipynb`
- Exact safety copy: `backend/backup/Dual_t4_Working_with_Document_Generation_pre_CLIPROXYAPI.ipynb`
- Local backend notebook: `backend/Local_Working_with_Document_Generation_CLIProxyAPI.ipynb`
- Reusable/testable client: `backend/cliproxy_client.py`
- Windows installer: `scripts/setup_cliproxyapi.ps1`

## Windows setup

Run PowerShell from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_cliproxyapi.ps1
```

Edit `%USERPROFILE%\.cli-proxy-api\config.yaml` and replace the example local
API key. Then run the authentication command printed by the installer:

```powershell
cli-proxy-api.exe --config "$env:USERPROFILE\.cli-proxy-api\config.yaml" --antigravity-login
```

Start the service using the second command printed by the installer. Verify it:

```powershell
$headers = @{ Authorization = "Bearer YOUR_LOCAL_KEY" }
Invoke-RestMethod http://127.0.0.1:8317/v1/models -Headers $headers
```

After initial setup, it can be started with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_cliproxyapi.ps1
```

## BuildMarshal configuration

Set these variables before opening/running the new notebook:

```powershell
$env:CLIPROXY_BASE_URL = "http://127.0.0.1:8317/v1"
$env:CLIPROXY_API_KEY = "YOUR_LOCAL_KEY"
$env:CLIPROXY_MODEL = "gemini-3.7-flash-high"
```

The backend checks `/v1/models`. If that exact identifier is unavailable, it
selects an exposed Gemini Flash identifier and reports the actual selection in
`/api/status` and each chat response.

The new notebook renders PDFs with PyMuPDF, so a separate Windows Poppler
installation is not required.

On a local computer, downloaded ColPali/PaliGemma weights are retained under
`.buildmarshal_runtime/buildmarshal/hf_models`. Subsequent starts validate and
reuse those files instead of downloading them again. Kaggle runs retain the
old disk-saving cleanup behavior unless `BUILDMARSHAL_KEEP_MODEL_FILES=1` is set.

## Deployment boundary

`127.0.0.1` works only when BuildMarshal and CLIProxyAPI run on the same Windows
computer. A Kaggle process cannot reach a proxy on your PC through localhost.
If the notebook is run on Kaggle, `CLIPROXY_BASE_URL` must be a separately
secured reachable endpoint. Never expose CLIProxyAPI's management interface or
OAuth files publicly.
