# AgentBoundary on a Windows laptop — WSL2 setup guide

Target: Windows 10/11, 8 GB+ RAM, WSL2 + Ubuntu. The backend is
**not verified natively on Windows** (process exclusivity relies
on POSIX `flock`), so run everything below **inside WSL2/Ubuntu**,
not from PowerShell and not from a `/mnt/c` path (keep the tree
on the Linux filesystem for correct file-locking behavior).

## 1. Prerequisites (one time)

1. In PowerShell (administrator):
   `wsl --install -d Ubuntu` (then restart if asked, and finish
   the Ubuntu first-run user setup).
2. Inside Ubuntu, install runtimes:
   `sudo apt update && sudo apt install -y python3.12
   python3.12-venv nodejs npm`
   (Node 20+ works; the build environment used Node v24.)
3. You need about 2 GB free for the source plus installed
   dependencies (~250 MB for the Python venv + node_modules).

## 2. Extract and install

1. Copy this ZIP into Ubuntu (for example, to `~/agentboundary/`)
   and extract it there — do not extract onto `/mnt/c`.
2. Backend:
   `cd backend`
   `python3 -m venv .venv`
   `.venv/bin/pip install -r requirements.txt -e .[test]`
3. Frontend:
   `cd ../frontend`
   `npm ci`

## 3. Run the demo

From the repository root:
`scripts/start.sh`

This starts the backend on `http://127.0.0.1:8000` and the
frontend on `http://127.0.0.1:5173`, loopback only. Open
`http://127.0.0.1:5173` in your Windows browser (WSL2 forwards
loopback). Stop with the script's stop path (see
`scripts/start.sh`); start/stop does not touch the database
except through the app itself.

First start creates a fresh database from the synthetic
fixtures (48 records: tenants, personas, cases, alerts, runbooks,
approvals, assets). The original demo database is **not**
included in this backup (it held only fixtures plus expired
session tokens), so a fresh seed is the expected state — not a
problem.

## 4. Verify it works

- Health: `curl http://127.0.0.1:8000/api/v1/health`
  (expect 200).
- Scripted scenario A1 (offline, no key needed), protected CLI
  from `backend/`:
  `.venv/bin/python -m agentboundary.cli run --scenario A1`
  (expect PASS, 0 forbidden completions).
- Backend tests: `.venv/bin/python -m pytest -q` from `backend/`.
- Frontend tests: `npm run test` from `frontend/`; Playwright:
  `npx playwright test` from `frontend/`.

## 5. Notes and limits

- **No paid API is required.** Scripted mode is fully offline.
  The real-LLM path is optional and mocked in tests; to try it,
  see `docs/real-llm-evaluation.md` and `backend/.env.example`
  (variable names only — never commit a real key). A completed
  live Ollama PASS trial was never verified on the build
  machine, so live-model effectiveness is not claimed.
- The deliberately weak comparison mode is CLI-only and
  requires `AGENTBOUNDARY_UNSAFE_LAB=1` (`run-weak`); it never
  runs as a server.
- Ports are loopback-only by design. Do not expose the backend
  beyond your machine: there is no TLS, no SSO, and sessions
  are server-held tokens.
- This source ZIP is not a portable virtual environment: if you
  move machines, re-run the install steps above.
- Full reference: `README.md` (Quick start) and the consolidated
  security report under `reports/`.
