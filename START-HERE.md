# BuildMarshalAI teammate handover

This folder is a self-contained handover of the working local BuildMarshalAI pipeline as of 28 August 2026.

## Included

- Complete BuildMarshalAI source, frontend, backend notebooks, tests, docs, and backups
- Pinned Python/CUDA package manifest and an automatic environment-creation script
- Offline ColPali v1.2 adapter and PaliGemma base weights
- Uploaded PDFs, rendered pages, retrieval vectors, ChromaDB indexes, project metadata, and generated documents
- CLIProxyAPI Windows executable and configuration
- Existing Antigravity OAuth login record
- Google OAuth client credentials
- Encrypted Google Workspace refresh-token store and its matching encryption key
- Scripts that restore environment variables and start the proxy/frontend

## Teammate prerequisites

1. Windows 10/11 x64.
2. NVIDIA GPU with a current driver and enough VRAM for ColPali (the original machine used an RTX 3070 Ti).
3. Python 3.13 installed and available through the Windows `py` launcher.
4. VS Code with the Python and Jupyter extensions.
5. Internet access for Gemini through CLIProxyAPI and for Google Workspace APIs. The ColPali model itself is bundled for offline loading.

## First start

Open PowerShell in this folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\START-BUILDMARSHAL.ps1
```

The script performs the one-time setup, creates `.venv-gpu` from the pinned package list when needed, starts CLIProxyAPI on port 8317, starts the frontend on port 5500, and opens the backend notebook in VS Code. The first environment setup downloads Python packages and can take several minutes; the model weights are already bundled and are not downloaded again.

To create only the Python environment yourself, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\CREATE-ENVIRONMENT.ps1
```

The package pins are documented in `requirements-handover.txt`.

In VS Code:

1. Select `BuildMarshalAI Handover GPU (Python 3.13)` as the notebook kernel.
2. Click **Restart**, then **Run All**.
3. Wait until the final cell reports that the backend is live on `http://127.0.0.1:8000`.
4. Open `http://localhost:5500`.

Health checks:

- Backend: `http://127.0.0.1:8000/api/health`
- API docs: `http://127.0.0.1:8000/docs`
- CLIProxy: `http://127.0.0.1:8000/api/cliproxy/status`
- Frontend: `http://localhost:5500`

## Signing in

The application is multi-tenant. The frontend opens on a sign-in screen and
loads nothing until you authenticate.

- **Existing data**: everything bundled with this handover (uploaded PDFs,
  rendered pages, vector indexes, generated documents, and the connected Google
  account) is migrated on first start into a single account named
  **Legacy Workspace**, owned by `admin@buildmarshal.com`. Sign in with the
  password `admin123` and change it from **My Account** straight away.
- **New accounts**: choose **Create account** on the sign-in screen. A new
  account starts completely empty and shares nothing with any other account —
  separate files, vector index, projects, settings, conversations, and Google
  integrations.
- **Members**: an account administrator adds people under
  **Company Settings -> User**. Members sign in with their own credentials and
  share that one account's workspace.

`BuildMarshalAI_capstone/docs/ACCOUNTS_AND_ISOLATION.md` documents the account
model, the isolation guarantees, and the migration in full.

## If the Antigravity login expires

Run this from the handover folder and complete the browser login:

```powershell
.\cliproxyapi\cli-proxy-api.exe -config .\cliproxyapi\config.yaml --antigravity-login
```

Then rerun `START-BUILDMARSHAL.ps1`.

## Google Workspace behavior

The connected Google account and refresh token are bundled. They only remain usable while the Google account owner allows access and the OAuth refresh token remains valid. To connect a different account while the OAuth application is in Testing mode, add that exact email under Google Cloud Console → Google Auth Platform → Audience → Test users.

## Security warning

The bundled `admin@buildmarshal.com` / `admin123` credentials own the migrated
workspace and all of its documents. Change that password on first sign-in.

This folder grants access equivalent to the original user's active Google Workspace and Antigravity sessions. Anyone holding it may be able to read Drive/Gmail/Calendar data and send email or create calendar events through the application. Transfer it only through an encrypted drive or encrypted archive, never commit it to GitHub, and never upload it to a public cloud folder.

After the teammate confirms the handover, rotate the CLIProxy API key and Google OAuth client secret if ownership is changing. Remove the original account or revoke its OAuth grants if the teammate should not retain access.
