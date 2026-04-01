# TalkBuddy AI Agentic MVP

This starter is now architected as an agentic system, not a plain CRUD backend.

## What is built

- an expert-routed therapy orchestrator in `app/agentic.py`
- provider boundaries, agent graph, and runtime provider status in `app/providers.py`
- repository access for curriculum, vectors, and environment standards in `app/repositories.py`
- workflow queue handling for caregiver and clinician handoffs in `app/workflows.py`
- role-aware API endpoints in `app/main.py`
- seeded child, caregiver, clinician, progress, communication-profile, environment, and curriculum data in `app/data.py`
- environment scaffolding in `.env.example`
- a Supabase-ready schema in `docs/supabase_schema.sql`
- architecture documentation in `docs/architecture.md`
- working notes in `notes/`

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
- curriculum targets for the month-one program
- multimodal reference vectors
- child attempt vectors
- simple nearest-reference matching
- simple environment-standard checking

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

## Useful endpoints

- `GET /architecture/providers`
- `GET /architecture/graph`
- `GET /providers/status`
- `POST /filter/preview`
- `GET /profiles/child/child-1`
- `GET /profiles/parent/caregiver-1`
- `GET /profiles/environment/child-1`
- `POST /environment/check`
- `GET /curriculum`
- `GET /vectors/references?target_id=target-b`
- `GET /vectors/attempts?child_id=child-1`
- `GET /vectors/match?target_id=target-b&modality=audio&embedding=0.9,0.1,0.3,0.4`
- `GET /children`
- `POST /session/start`
- `GET /sessions/{session_id}`
- `POST /sessions/{session_id}/complete`
- `POST /speech/input`
- `GET /caregiver/alerts?caregiver_id=caregiver-1`
- `POST /caregiver/alerts/{alert_id}/acknowledge`
- `GET /clinician/queue?clinician_id=slp-1`
- `GET /workflows/queues`
- `GET /reports/child/child-1`
- `GET /enterprise/usage`

## Immediate next implementation slice

1. Connect Supabase as the actual repository layer.
2. Persist communication profiles, environment profiles, curriculum targets, and vectors.
3. Connect OpenAI as the real conductor, reporting expert, environment reasoner, and output filter.
4. Connect Deepgram streaming transcription.
5. Connect Hume engagement scoring.
6. Connect Temporal workflow dispatch.
7. Add Clerk auth guards around caregiver, clinician, and admin endpoints.
8. Replace heuristic vector matching with real embeddings and retrieval.
