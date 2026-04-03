# TalkBuddy Complete User Manual

Version: 1.0
Applies to: speech-intellegence plus speech-filters Docker deployment
Primary UI port: 18200
Filter service port: 18100

## 1. Purpose

TalkBuddy is a pediatric speech-practice application made of two cooperating services:

- `speech-intellegence`: the main therapy application, browser UI, orchestration layer, and session APIs.
- `speech-filters`: the dedicated output filtering service that rewrites child-facing and caregiver-facing language into calmer, lower-stimulation responses.

The app is designed to support guided speech practice, caregiver visibility, and safer child-facing output. It is not a diagnostic system and it does not replace a licensed speech-language pathologist.

## 2. Current Local Architecture

The complete local system runs as two Docker containers:

- Main app container: `talkbuddy-app`
- Filter service container: `speech-filters-speech-core-1` or the current Compose-assigned container name

Live local URLs:

- Main application shell: `http://127.0.0.1:18200/`
- Therapy screen: `http://127.0.0.1:18200/therapy`
- Main app health: `http://127.0.0.1:18200/health`
- Filter service health: `http://127.0.0.1:18100/health`
- Filter service docs in development only: `http://127.0.0.1:18100/docs`

Request flow:

1. A browser or API client sends a request to `speech-intellegence`.
2. The orchestrator decides what response or next action is needed.
3. Child-facing or parent-facing output is sent to `speech-filters` over HTTP.
4. The filter service returns a safer rewritten message plus trace data.
5. The main app returns the filtered result to the browser or API client.

## 3. Who This Manual Is For

This manual is for:

- caregivers running a local demo or pilot
- clinicians reviewing session behavior
- operators starting the local Docker deployment
- developers and testers validating the APIs with Postman

## 4. Prerequisites

Before starting the system, make sure these are available:

- Docker Desktop is installed and running
- Ports `18100` and `18200` are free on the host machine
- Each repo has a local `.env` file copied from `.env.example`

Recommended folder layout:

- `C:\Users\rkafl\Documents\Projects\speech-intellegence`
- `C:\Users\rkafl\Documents\Projects\speech-filters`

## 5. Required Environment Variables

### 5.1 speech-intellegence

Minimum local settings for containerized integration:

- `APP_ENV=development`
- `SUPABASE_REPOSITORY_MODE=memory` for local seeded demo mode
- `FILTER_SERVICE_URL=http://host.docker.internal:18100`
- `FILTER_SERVICE_TIMEOUT=3`
- `FILTER_SERVICE_API_KEY=local-prod-key`

Optional live-provider settings:

- `OPENAI_API_KEY`
- `DEEPGRAM_API_KEY`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `LIVEKIT_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

### 5.2 speech-filters

Minimum local production-style settings:

- `APP_ENV=production`
- `SERVICE_API_KEY=local-prod-key`
- `SUPABASE_URL` and `SUPABASE_KEY` if you want Supabase-backed persistence

Useful behavior flags:

- `REQUIRE_AUTH_IN_PRODUCTION=true`
- `ALLOW_OPENAPI_IN_PRODUCTION=false`
- `ENABLE_AUDIT_LOGGING=true`
- `LOG_IDENTIFIER_SALT` set to a non-empty value for hashed identifiers in logs

## 6. Starting the System with Docker

Start the filter service first.

From the `speech-filters` repo:

```powershell
cd C:\Users\rkafl\Documents\Projects\speech-filters
docker compose up -d --build
```

Verify it is running:

```powershell
docker compose ps
```

Expected check:

- `GET http://127.0.0.1:18100/health`
- In production-style mode you should see `"auth_required": true`

Then start the main app.

From the `speech-intellegence` repo:

```powershell
cd C:\Users\rkafl\Documents\Projects\speech-intellegence
docker compose up -d --build
```

Verify it is running:

```powershell
docker compose ps
```

Expected check:

- `GET http://127.0.0.1:18200/health`
- In local demo mode you should see `"status": "ok"`

## 7. Stopping the System

To stop each stack:

```powershell
docker compose down
```

Run that command separately from each repo folder.

## 8. Browser Usage

### 8.1 Main Application

Open the main UI in a browser:

- Home shell: `http://127.0.0.1:18200/`
- Therapy screen: `http://127.0.0.1:18200/therapy`

The main app serves the browser UI. The filter service does not serve the child UI.

### 8.2 Filter Service

The filter service is an API service. It does not provide the main browser experience. If you open the root path at `http://127.0.0.1:18100/`, a `404 Not Found` response is normal unless a root route is added later.

Use these instead:

- `GET /health` for a browser-safe status check
- `POST /filter` for filtering
- `POST /filter/preview` for previewing filtered output
- `POST /filter/batch` for multi-item filtering

## 9. Running a Therapy Session

Typical local flow:

1. Open `http://127.0.0.1:18200/therapy`.
2. Start or create a session using the UI or API.
3. Submit a child speech attempt.
4. The main app evaluates the attempt.
5. The main app sends the response text to `speech-filters`.
6. The filter service returns a rewritten response.
7. The child receives the filtered coaching language.

A verified example response returned:

- Original text: `Great job.`
- Filtered text: `Quiet try. Nice work.`

A verified full-turn response from the main app returned:

- `Quiet try. Nice work. We can move to the next sound now.`

## 10. Postman Testing Guide

### 10.1 Filter Service Authentication

When the filter service runs in production mode, send this header:

- `x-service-api-key: local-prod-key`

Without that header, protected endpoints should return `401 Unauthorized`.

### 10.2 Basic Filter Request

Method:

- `POST`

URL:

- `http://127.0.0.1:18100/filter`

Headers:

- `Content-Type: application/json`
- `x-service-api-key: local-prod-key`

Body format:

- Postman Body tab
- choose `raw`
- choose `JSON`

Example body:

```json
{
  "audience": "child",
  "text": "Great job.",
  "context": "success",
  "owner_id": "child-1"
}
```

Expected outcome:

- HTTP `200 OK`
- response contains `filtered_text`
- response includes style tags and filter trace

### 10.3 Preview Request Through Main App

URL:

- `POST http://127.0.0.1:18200/filter/preview`

Example body:

```json
{
  "audience": "child",
  "text": "Great job.",
  "owner_id": "child-1"
}
```

Expected outcome:

- provider trace shows `speech-filters-service`
- filtered output should come back from the dedicated filter service

### 10.4 Session Start

URL:

- `POST http://127.0.0.1:18200/session/start`

Example body:

```json
{
  "child_id": "child-1"
}
```

Expected outcome:

- a new session id
- a starting prompt or first activity message

### 10.5 Speech Input

URL:

- `POST http://127.0.0.1:18200/speech/input`

Example body:

```json
{
  "session_id": "your-session-id",
  "transcript": "pa",
  "attention_score": 0.92
}
```

Expected outcome:

- an action such as `advance` or `retry`
- child feedback text
- trace data showing the output filter expert path

## 11. Postman Collection

A ready-made collection exists in the filter service repo:

- `speech-filters/docs/speech-filters-postman-collection.json`

It includes:

- `GET /health`
- `POST /filter`
- `POST /filter/preview`
- `POST /filter/batch`
- `GET /profiles`
- `GET /filters/policies`
- `POST /retrieval/blended-match`

Default variables currently used:

- `base_url=http://127.0.0.1:18100`
- `service_api_key=local-prod-key`

## 12. Health Checks and What They Mean

### 12.1 Filter Service Health

Example fields:

- `status`: service readiness
- `env`: `development` or `production`
- `provider`: active output filter provider class
- `live_providers`: whether live provider calls are enabled
- `openai_configured`: whether OpenAI is configured
- `supabase_enabled`: whether Supabase is active
- `auth_required`: whether the API key is enforced
- `openapi_enabled`: whether `/docs` is exposed

### 12.2 Main App Health

Example fields:

- `status`: service readiness
- `version`: current app version
- `env`: runtime environment
- `live_providers`: whether live providers are active
- `openai_configured`: whether OpenAI is configured
- `deepgram_configured`: whether Deepgram is configured
- `livekit_configured`: whether LiveKit is configured
- `supabase_enabled`: whether Supabase is active
- `auth_required`: whether app-level auth is enabled

## 13. Troubleshooting

### 13.1 `{"detail":"Not Found"}` on the Filter Service

Usually this means one of these:

- you opened `http://127.0.0.1:18100/` instead of `/health`
- you used the wrong path for the endpoint
- another container was bound to the same port earlier

Fixes:

- try `GET http://127.0.0.1:18100/health`
- for filter calls, use `POST http://127.0.0.1:18100/filter`
- confirm the active container with `docker compose ps`

### 13.2 `401 Unauthorized`

Likely cause:

- missing or incorrect `x-service-api-key` header

Fix:

- send `x-service-api-key: local-prod-key` when the filter service is in production mode

### 13.3 `127.0.0.1 refused to connect`

Likely cause:

- the container is not running
- the stack was previously stopped after a smoke test

Fix:

- run `docker compose up -d --build`
- recheck with `docker compose ps`

### 13.4 The Main App Does Not Use the Filter Service

Likely cause:

- `FILTER_SERVICE_URL` is missing or incorrect
- `FILTER_SERVICE_API_KEY` does not match the filter service value

Fix:

- in `speech-intellegence/.env`, set `FILTER_SERVICE_URL=http://host.docker.internal:18100`
- set `FILTER_SERVICE_API_KEY=local-prod-key`
- rebuild the main app container

### 13.5 Supabase Errors in Local Demo Mode

Likely cause:

- placeholder values were left in `.env`
- the app tried to use a malformed URL or fake key

Fix:

- for a local seeded demo, set `SUPABASE_REPOSITORY_MODE=memory`
- blank out unused placeholder secrets

## 14. Safety and Standards Notes

Current safeguards added to the filter service include:

- production auth enforcement
- startup fail-fast checks for unsafe production configuration
- structured audit logging
- hashed identifiers in logs when configured
- no raw child text in audit events
- safer response headers
- safer persistence fallback when Supabase fails

Important boundary:

This local build is better aligned for pediatric health workflows, but software controls alone do not make the full product legally or clinically compliant. Organizational controls, consent flows, legal review, retention policy, access controls, and regulatory review still matter.

## 15. Recommended Operator Checklist

Before a demo:

- confirm Docker Desktop is running
- confirm both containers show healthy or running status
- confirm `GET /health` works on `18100` and `18200`
- confirm the filter service requires the expected API key in production mode
- confirm a sample `POST /filter` returns `200`
- confirm the main app can start a session and process one speech input

Before a production-style pilot:

- replace `local-prod-key` with a real secret
- configure Supabase with real credentials if persistence is required
- set a non-empty `LOG_IDENTIFIER_SALT`
- review audit logging and retention expectations
- confirm the calling app's auth and role controls

## 16. File Locations

Useful files in `speech-intellegence`:

- `README.md`
- `docker-compose.yml`
- `app/main.py`
- `app/integrations/gateway.py`
- `docs/generate_manual_pdf.py`
- `docs/TalkBuddy_Complete_User_Manual.md`
- `docs/TalkBuddy_User_Manual.pdf`

Useful files in `speech-filters`:

- `README.md`
- `docker-compose.yml`
- `app/main.py`
- `app/client.py`
- `docs/medical-readiness.md`
- `docs/speech-filters-postman-collection.json`

## 17. Support Notes

If a local request fails, the fastest first checks are:

1. `docker compose ps` in both repos
2. `GET /health` on `18100` and `18200`
3. check whether the request path, method, and headers match this manual
4. confirm the main app `.env` still points to `host.docker.internal:18100`

## 18. Revision History

- Version 1.0: first complete two-service user manual aligned with the verified Docker deployment and Postman flow.
