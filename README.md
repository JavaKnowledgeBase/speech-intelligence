# TalkBuddy AI Agentic MVP

This starter is now architected as an agentic system, not a plain CRUD backend.

## Core purpose

The product's purpose is to encourage the child to speak.

It should not drift into being mainly a word-familiarization or text-familiarization app.

Success should be measured more by:

- speaking attempts
- vocal imitation
- speaking confidence
- repeated speech production

than by passive recognition of words or text.

## What is built

- an expert-routed therapy orchestrator in `app/agentic.py`
- a dedicated integration gateway for output filtering, vectors, environment checks, and attempt ingestion in `app/integrations.py`
- provider boundaries, agent graph, and runtime provider status in `app/providers.py`
- a Supabase-aware repository layer with in-memory fallback in `app/repositories.py`
- workflow queue handling for caregiver and clinician handoffs in `app/workflows.py`
- role-aware API endpoints in `app/main.py`
- seeded child, caregiver, clinician, progress, communication-profile, environment, and curriculum data in `app/data.py`
- environment scaffolding in `.env.example`
- a Supabase-ready schema in `docs/supabase_schema.sql`
- architecture documentation in `docs/architecture.md`
- working notes in `notes/`

## Device target

The app must work well on:

- tablet
- TV
- desktop

That means future frontend work should prioritize:

- touch-first controls where appropriate
- large tap targets
- large visual prompts
- high readability from a distance on TV
- minimal reading burden in child mode
- landscape and large-screen layouts
- responsive layouts that also fully support desktop caregiver, clinician, and admin use

## Agentic design

The core therapy loop now runs through specialist experts:

- `child_session_runtime`: intended for LiveKit Agents
- `session_conductor`: intended for OpenAI Responses API
- `speech_scoring_expert`: intended for Deepgram Nova / Flux
- `engagement_expert`: intended for Hume Expression Measurement
- `care_plan_expert`: intended for OpenAI Responses API
- `environment_expert`: compares room state against the child baseline
- `vector_match_expert`: compares attempts to multimodal reference clusters
- `workflow_expert`: intended for Temporal
- `reporting_expert`: intended for OpenAI Responses API
- `output_filter_expert`: calming, constructive, low-arousal filter for all child and parent output

## Output and environment behavior

All child-facing and parent-facing output passes through a dedicated output filter layer before delivery.

The system also now has first-pass support for:

- child communication profiles
- parent communication profiles
- environment standards per child
- session-start environment checks
- calm parent adjustment guidance when the room is off-standard
- curriculum targets for the month-one program
- multimodal reference vectors
- child attempt vectors
- simple nearest-reference matching
- request-based attempt ingestion through a stable integration contract
- Supabase-backed reads and writes for repository-managed entities when configured

## Recommended external stack

- Realtime media and session runtime: LiveKit Agents + WebRTC
- Agent brain and tool calling: OpenAI Responses API
- Realtime speech-to-speech fallback: OpenAI Realtime API
- Speech-to-text and turn detection: Deepgram Nova / Flux
- Engagement and affect analysis: Hume Expression Measurement
- Environment reasoning: OpenAI vision-capable reasoning or custom scene analysis
- Durable workflows: Temporal
- Clinical data, storage, environment standards, curriculum targets, and vectors: Supabase + pgvector
- Auth, organizations, and permissions: Clerk Organizations

## Run

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open the voice-first shell at `http://localhost:18200/` when running via Docker Compose, or `http://localhost:8000/` when running the app process directly.

## Repository mode

The repository layer supports three runtime modes through `SUPABASE_REPOSITORY_MODE`:

- `auto`: use Supabase when credentials are configured, otherwise fall back to the local in-memory seed store
- `memory`: force local in-memory behavior even when Supabase credentials are present
- `supabase`: prefer Supabase and still fall back to in-memory data if a request fails

Required Supabase variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Useful endpoints

- `GET /architecture/providers`
- `GET /architecture/graph`
- `GET /providers/status`
- `POST /runtime/voice/session`
- `POST /runtime/voice/connect`
- `POST /runtime/voice/checkpoints`
- `GET /runtime/voice/checkpoints?session_id=...`
- `POST /runtime/voice/transcript`
- `POST /runtime/voice/deepgram`
- `POST /runtime/voice/events`
- `POST /runtime/voice/playback`
- `POST /runtime/voice/playback/state`
- `GET /runtime/voice/playback?session_id=...`
- `POST /runtime/voice/tts`
- `POST /runtime/voice/tts/process`
- `GET /runtime/voice/tts?session_id=...`
- `POST /filter/preview`

Docker integration note:

When `speech-intellegence` runs in Docker alongside `speech-filters`, set `FILTER_SERVICE_URL=http://host.docker.internal:18100` and `FILTER_SERVICE_API_KEY` to the filter service key so the app routes all output filtering through the dedicated service.
- `GET /profiles/child/child-1`
- `GET /profiles/parent/caregiver-1`
- `GET /profiles/environment/child-1`
- `POST /environment/check`
- `GET /curriculum`
- `GET /vectors/references?target_id=target-b`
- `GET /vectors/attempts?child_id=child-1`
- `POST /vectors/attempts`
- `GET /vectors/match?target_id=target-b&modality=audio&embedding=0.9,0.1,0.3,0.4`
- `POST /session/start`
- `POST /speech/input`
- `GET /caregiver/alerts?caregiver_id=caregiver-1`
- `GET /clinician/queue?clinician_id=slp-1`
- `GET /enterprise/usage`

## Session start shape

The frontend shell now includes a first-pass voice runtime contract.

Use `POST /runtime/voice/session` after `POST /session/start` to request the current transport handshake details, room name, token state, and explicit STT/TTS/transcript/event lane metadata for the child session. In mock mode it returns the same shape without a signed token so the frontend or future native app shell can keep moving before LiveKit is fully connected.

Use `POST /runtime/voice/connect` when the client is ready to move from session metadata into a transport join handshake. In live mode it returns a `ready_to_join` contract with the LiveKit URL, room, token, and data-channel labels. In mock mode it still returns a stable local connection shape.

Use `POST /runtime/voice/transcript` for partial or final transcript chunks. Final chunks run the normal therapy turn evaluation, which makes this the core internal seam for STT providers.

Use `POST /runtime/voice/deepgram` when a transport worker is receiving Deepgram-style streaming frames and needs the backend to normalize them into the internal transcript contract before session evaluation.

Use `POST /runtime/voice/events` for barge-in, VAD, client join, and playback interruption signals, and keep `/runtime/voice/checkpoints` for latency timing snapshots.

Use the playback queue endpoints to move child-facing audio through a deterministic lane before real synthesis is attached: enqueue with `POST /runtime/voice/playback`, promote a queued playback item into a provider-ready synthesis job with `POST /runtime/voice/tts`, finalize that job into a ready artifact with `POST /runtime/voice/tts/process`, inspect synthesis jobs directly with `GET /runtime/voice/tts`, and move items through `pending -> synthesizing -> ready -> playing -> interrupted -> played` with `POST /runtime/voice/playback/state`, and inspect the queue with `GET /runtime/voice/playback`.


`POST /session/start` can include an optional environment snapshot. If the room looks off-standard, the response includes a calm parent-facing adjustment message before therapy begins.

## Immediate next implementation slice

1. Persist sessions, session events, alerts, and progress snapshots through the repository layer too.
2. Seed Supabase with the current starter data from this repo.
3. Add a frontend built for tablet, TV, and desktop.
4. Connect OpenAI as the real conductor, reporting expert, environment reasoner, and output filter.
5. Connect Deepgram streaming transcription.
6. Connect Hume engagement scoring.
7. Connect Temporal workflow dispatch.
8. Add Clerk auth guards around caregiver, clinician, and admin endpoints.
9. Replace heuristic vector matching with real embeddings and retrieval.
