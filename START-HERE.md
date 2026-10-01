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
6. PostgreSQL 14 or newer running on this PC (developed on 18), and its superuser (`postgres`) password. Every record — accounts, projects, tasks, documents, linked Google/Microsoft accounts — is stored there; see `BuildMarshalAI_capstone/docs/DATABASE.md`.

## First start

Open PowerShell in this folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\START-BUILDMARSHAL.ps1
```

The script performs the one-time setup, creates `.venv-gpu` from the pinned package list when needed, creates the BuildMarshalAI database on first use (it asks once for the PostgreSQL superuser password, which is not stored — or run `SETUP-DATABASE.ps1` yourself beforehand), starts CLIProxyAPI on port 8317, starts the frontend on port 5500 (moving either one if Windows has reserved its port -- see **If a service will not start on its port** below), and opens the backend notebook in VS Code. The first environment setup downloads Python packages and can take several minutes; the model weights are already bundled and are not downloaded again.

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

## The database

`SETUP-DATABASE.ps1` creates a `buildmarshal` role and the `buildmarshal`, `buildmarshal_test` and `buildmarshal_demo` databases, and records their URLs in `secrets\runtime-secrets.json`. The backend will not start without its database; `BuildMarshalAI_capstone\scripts\check_database.py` says whether it answers.

A data folder from before the database (JSON files) is imported automatically on the first start: every record goes into PostgreSQL in one transaction and the JSON files are moved to `.buildmarshal_runtime\buildmarshal\json-storage-backup\`, not deleted.

**Moving this installation to another PC** now means the data folder *and* the database: back up with `pg_dump` and restore with `pg_restore` (commands in `docs/DATABASE.md`). The data folder carries a `.database-binding.json` that must match the database it came with.

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

## If a service will not start on its port

Symptom: the launcher reports that a service did not start, or a log
shows

```
listen tcp 127.0.0.1:8317: bind: An attempt was made to access a socket
in a way forbidden by its access permissions.
```

This is **not** an authentication problem and not a broken install.
Windows allocates ports to Hyper-V's NAT driver out of the TCP *dynamic
port range*, and then refuses to let anything else bind them, even though
nothing is listening. The blocks move from boot to boot, so a port that
worked yesterday can fail today.

Windows' own default dynamic range is 49152-65535, which leaves ordinary
service ports alone. Docker Desktop and some VPN clients move it down to
start at 1024 -- and then everything from 1024 up, including 5500, 8000
and 8317, is fair game. Check both:

```powershell
netsh int ipv4 show dynamicport tcp
netsh int ipv4 show excludedportrange protocol=tcp
```

If the dynamic range starts at 1024 rather than 49152, that is the cause.

`START-BUILDMARSHAL.ps1` handles this by itself: it bind-tests every
port, moves any service whose port has been taken, and tells you where
it put it. The frontend follows the backend automatically. Nothing needs
doing, and nothing needs Administrator.

To get the usual ports back permanently, run once as Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File .\RESERVE-PORTS.ps1
```

It puts the dynamic range back to the Windows default -- which is the fix,
because it takes 1024-49151 out of contention entirely -- and also adds the
three ports as persistent exclusions. It asks before changing the range and
prints the command to undo it. Docker and WSL work normally with the default
range. `-Revert` removes the exclusions; `-KeepDynamicRange` skips the range
change.

**A reboot is required afterwards.** Blocks already handed out during the
current boot stay held until then, so the ports look blocked even after the
script succeeds. This is why running it and immediately retrying appears to
change nothing. Meanwhile the launcher keeps working: it moves each service
to a free port on its own.

When a service really has failed for some other reason, its own output is
in the `logs\` folder next to this file.

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
