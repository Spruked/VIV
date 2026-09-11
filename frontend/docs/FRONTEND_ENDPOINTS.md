# Cali CRM Frontend Endpoint Contract

Base URL: `VITE_CALI_API_URL`, default `http://127.0.0.1:21000`.

Auth: every `/cali/*` request sends `Authorization: Bearer <CALI_ADMIN_TOKEN>` from localStorage key `cali_admin_token`.

## Core

| Method | Path | Used By |
| --- | --- | --- |
| `GET` | `/health` | Dashboard health card |
| `GET` | `/cali/status` | Reserved status surface |
| `GET` | `/cali/crm/unified/status` | Dashboard integration state |

## Contacts

| Method | Path | Used By |
| --- | --- | --- |
| `GET` | `/cali/contacts?query=&contact_type=` | Contacts table, Activities picker |
| `POST` | `/cali/contacts` | Contacts create form |
| `GET` | `/cali/contacts/financial` | Financial contacts extension point |

Expected create payload:

```json
{
  "name": "Example Contact",
  "contact_type": "business",
  "email": "contact@example.com",
  "phone": "optional",
  "address": "optional",
  "notes": "optional",
  "priority": 1,
  "crm_stage": "prospect",
  "lead_source": "manual",
  "owner": "bryan@spruked.com",
  "next_follow_up_at": null
}
```

## Pipeline

| Method | Path | Used By |
| --- | --- | --- |
| `GET` | `/cali/crm/pipeline` | Dashboard, Pipeline Kanban |
| `PATCH` | `/cali/crm/leads/stage` | Kanban drag/drop stage updates |

Backend-supported stages currently used by the frontend:

`prospect`, `qualified`, `contacted`, `meeting_scheduled`, `proposal`, `won`, `lost`.

## Activities

| Method | Path | Used By |
| --- | --- | --- |
| `GET` | `/cali/crm/activities/{contact_id}?limit=80` | Activity feed |
| `POST` | `/cali/crm/activities` | Log activity form |
| `POST` | `/cali/crm/appointments` | Calendar/appointment extension point |

## Email

| Method | Path | Used By |
| --- | --- | --- |
| `GET` | `/cali/crm/external-email/health` | Integration extension |
| `GET` | `/cali/crm/external-email/stats` | Email analytics extension |
| `GET` | `/cali/crm/external-email/messages?folder=&limit=&offset=&search=&unread_only=` | Email inbox |
| `GET` | `/cali/crm/external-email/messages/{email_id}` | Message detail extension |
| `PATCH` | `/cali/crm/external-email/messages/{email_id}` | Star/read/archive updates |
| `DELETE` | `/cali/crm/external-email/messages/{email_id}` | Delete action extension |
| `POST` | `/cali/crm/external-email/send` | Compose form |
| `POST` | `/cali/crm/external-email/sync` | Sync inbox to CRM |

## Calendar

| Method | Path | Used By |
| --- | --- | --- |
| `GET` | `/cali/calendar/upcoming?days=14` | Calendar page |
| `GET` | `/cali/calendar/today` | Today briefing extension |
| `POST` | `/cali/calendar/events` | Create event extension |

## ORB

| Method | Path | Used By |
| --- | --- | --- |
| `POST` | `/cali/orb/respond` | ORB Assistant chat |
| `POST` | `/cali/query` | Query extension |
| `GET` | `/cali/site/context?current_path=` | Route context extension |

## Desktop ORB Bridge

The frontend exposes live context to Desktop ORB without requiring an API round trip:

```js
window.__CALI_CRM_CONTEXT
window.addEventListener('cali-crm-context-update', event => console.log(event.detail))
window.addEventListener('cali-crm-open-orb', event => console.log(event.detail))
```

Open ORB command:

```js
window.postMessage({ type: 'OPEN_ORB', payload: window.__CALI_CRM_CONTEXT }, '*')
```
