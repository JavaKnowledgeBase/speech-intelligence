# Handoff

## Repo State

- Branch: `main`
- Latest pushed commit: `357a618`
- Commit message: `Build voice runtime transport and TTS pipeline scaffolding`
- Verification: `160 passed`

## Current Build Status

The repo now includes:

- voice-first frontend dev shell
- runtime transport/session contract
- LiveKit-style transport connect handshake
- transcript and runtime event ingestion endpoints
- Deepgram adapter seam
- playback queue and playback state contract
- TTS synthesis-job adapter
- mock TTS artifact processing
- direct TTS queue snapshot endpoint
- warning-free test suite

## Important Files

- `app/main.py`
- `app/runtime.py`
- `app/agentic.py`
- `app/models.py`
- `app/integrations/deepgram_adapter.py`
- `app/integrations/tts_adapter.py`
- `app/static/app.js`
- `app/static/index.html`
- `README.md`

## Runtime Endpoints

- `POST /runtime/voice/session`
- `POST /runtime/voice/connect`
- `POST /runtime/voice/transcript`
- `POST /runtime/voice/deepgram`
- `POST /runtime/voice/events`
- `POST /runtime/voice/playback`
- `POST /runtime/voice/playback/state`
- `GET /runtime/voice/playback?session_id=...`
- `POST /runtime/voice/tts`
- `POST /runtime/voice/tts/process`
- `GET /runtime/voice/tts?session_id=...`

## Next To-Do

1. Wire a real LiveKit client/session worker to `/runtime/voice/connect`.
2. Add a real Deepgram streaming bridge that feeds `/runtime/voice/deepgram`.
3. Replace mock TTS artifact generation with a real synthesis provider behind `app/integrations/tts_adapter.py`.
4. Persist runtime transcripts, checkpoints, playback queue, and TTS jobs through the repository layer.
5. Add auth/RBAC and audit logging before production rollout.
6. Add structured observability for voice latency, provider failures, and interruptions.

## Notes

- Final product assumption remains app-native, not browser-native. The current web shell is a development harness.
- Preferred voice architecture remains LiveKit + Deepgram Flux + OpenAI Responses + dedicated TTS, with OpenAI Realtime only as a selective fallback.
