# Cali CRM Frontend

React + Vite + TypeScript operator console for the local Cali CRM backend.

Main slogan: `Pipeline Intelligence. Orbit Faster.`

Secondary tagline: `Your AI-powered revenue command center`

## Run

```powershell
cd R:\SPRUKED_CRM_MASTER_2026-05-05\frontend
npm install
npm run dev:local
```

URL:

```text
http://127.0.0.1:21010
```

Backend default:

```text
http://127.0.0.1:21000
```

Set the admin token in the UI with the `Token` button. The token is stored in localStorage key `cali_admin_token`.

## Build And Test

```powershell
npm run build
npm run test:smoke
```

For authenticated smoke tests:

```powershell
$env:CALI_ADMIN_TOKEN = ((Get-Content ..\.env | Where-Object { $_ -match '^CALI_ADMIN_TOKEN=' }) -replace '^CALI_ADMIN_TOKEN=','')
npm run test:smoke
```

## Surfaces

- Dashboard: CRM health, unified status, pipeline summary, ORB context debug panel
- Contacts: search, type filters, create contact, selected-contact ORB context
- Pipeline: drag/drop Kanban wired to `PATCH /cali/crm/leads/stage`
- Email: Prime Mail messages, sync-to-CRM, star toggle, compose hook
- Activities: per-contact event feed and activity creation
- Calendar: upcoming local events
- ORB Assistant: direct `/cali/orb/respond` chat

Endpoint contract: [docs/FRONTEND_ENDPOINTS.md](docs/FRONTEND_ENDPOINTS.md)
