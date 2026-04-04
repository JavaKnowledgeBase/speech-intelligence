# TalkBuddy AI Architecture

## Product shape

TalkBuddy is an expert-routed agentic speech therapy platform with human oversight, not a single LLM app.

## Core purpose

The core purpose is to encourage the child to speak.

The product optimises for:
- spoken attempts
- imitation
- vocal confidence
- repeated speech production

It must not drift into:
- a vocabulary familiarisation app
- a text familiarity tool
- a passive reading or viewing experience

The child session is handled by a conductor agent that consults narrow experts:
- speech scoring expert
- engagement expert
- care-plan expert
- escalation expert
- reporting expert
- workflow expert
- environment expert
- output filter expert

---

## Primary device targets

| Device | Role | Input |
|--------|------|-------|
| **iPad (child)** | Therapy session — child-facing | Microphone, touch |
| **iPad / tablet (caregiver)** | Live monitoring + alerts | Touch |
| **TV (room display)** | Caregiver dashboard, session overview | Remote / cast |
| **Desktop** | Clinician review, admin, reporting | Mouse + keyboard |

### iPad requirements (child device — highest priority)
- HTTPS mandatory — `getUserMedia` refuses on iOS without it
- Installed as PWA (home screen, fullscreen, no browser chrome)
- Landscape orientation locked
- Screen must stay awake for full session — WakeLock API is not supported on iOS Safari; use silent audio loop workaround
- AudioContext must resume after app-switch — iOS suspends it on `visibilitychange`
- No reliance on `window.SpeechRecognition` — use Deepgram streaming exclusively
- Touch targets minimum 72px for child use
- No scrolling in session view

### TV requirements (caregiver display)
- Layout readable at 3+ metres — minimum 2rem base font, 4rem headings
- High contrast, no hover-dependent interactions
- Navigation via remote (focus states required on all interactive elements)
- Can be driven by AirPlay/cast from iPad or standalone browser session
- No microphone required

---

## Voice-first product rule

More than 98% of child-session interaction must be speech input and speech output.
Text exists for clinician, caregiver, admin, audit, and fallback use only.

Frontend must optimise for:
- dependable microphone capture
- low-latency playback (target < 500ms turn-end to first audio byte)
- barge-in support
- graceful recovery from mic drop, network spike, or provider failure

---

## Recommended voice pipeline (production target)

```
iPad mic
  │
  ▼
LiveKit WebRTC  ──────────────────────────────────────────►  Speaker playback
  │                                                               ▲
  ▼                                                               │
Deepgram Flux (streaming STT + turn detection)               Dedicated TTS
  │                                                               ▲
  ▼                                                               │
OpenAI Responses API  (conductor + experts + output filter) ─────┘
  │
  ▼
Supabase  (session storage, profiles, audit trail)
  │
  ▼
Temporal  (escalation workflows, reminders, clinician queue)
```

### Why this pipeline
- Preserves exact control over child-facing wording (text in the loop, not speech-to-speech)
- Full audit trail at the transcript layer (HIPAA requirement)
- Deepgram supports custom vocabulary for therapy target words
- Fallback at every layer — if Deepgram degrades, browser STT catches; if OpenAI spikes, cached prompt plays
- LiveKit is provider-agnostic and supports both WebRTC and WebSocket transport

---

## Current implementation state vs target

| Layer | Target | Current state | Gap |
|-------|--------|---------------|-----|
| Transport | LiveKit WebRTC | None (WebSocket direct) | LiveKit not wired |
| STT | Deepgram Flux streaming | Browser SpeechRecognition + Gemini Live WS | Must replace |
| Audio processing | AudioWorklet (dedicated thread) | ScriptProcessor (deprecated, main thread) | Must replace |
| Evaluation | OpenAI Responses API (async) | Sequential sync httpx calls (~3s) | Parallelise |
| TTS | Dedicated streaming TTS | Browser SpeechSynthesis + OpenAI HEAD ping | OpenAI TTS wired, HEAD method wrong (405) |
| Data persistence | Supabase (load on startup) | In-memory only, lost on restart | Load from Supabase on startup |
| Auth | Clerk (organisations + roles) | Passthrough (no secret key set) | Enable before production |
| HTTPS | Caddy + Let's Encrypt | HTTP only | Add Caddy to docker-compose |
| PWA | Installable, landscape, fullscreen | Plain HTML in browser | Add manifest + service worker |
| Screen wake | Silent audio loop (iOS) | WakeLock only (not supported on iOS) | Add audio fallback |
| Child creation | POST /children from wizard | Wizard matches seeded children only | Add child creation endpoint |

---

## Recommended stack

### 1. Realtime transport
- **LiveKit Agents + WebRTC**
- Provider-agnostic, built-in observability, supports both WebRTC and WebSocket
- Source: https://docs.livekit.io/agents/

### 2. Speech recognition
- **Deepgram Nova-3 / Flux**
- Flux: conversational turn detection, low latency
- Nova-3: highest accuracy for children's speech, custom vocabulary adaptation
- HIPAA BAA available
- Source: https://deepgram.com/product/speech-to-text

### 3. Agent brain + conductor
- **OpenAI Responses API**
- Tool use, MCP support, built for agentic workflows
- Source: https://openai.com/index/new-tools-and-features-in-the-responses-api/

### 4. Speech-to-speech fallback
- **OpenAI Realtime API**
- Used selectively for natural back-and-forth only, not as the primary path
- Source: https://platform.openai.com/docs/api-reference/realtime?api-mode=responses

### 5. Engagement detection
- **Hume Expression Measurement**
- Voice + affect analysis for frustration, fatigue, and redirection signals
- Source: https://dev.hume.ai/docs/expression-measurement/overview

### 6. Workflow engine
- **Temporal**
- Durable timers, retries, escalation queues, human-in-the-loop
- Source: https://docs.temporal.io/

### 7. Data platform
- **Supabase**
- Postgres + storage + realtime + edge functions
- Source: https://supabase.com/docs/guides/getting-started/features

### 8. Identity and tenancy
- **Clerk Organisations**
- Caregiver / clinician / admin roles with organisation-scoped permissions
- Source: https://clerk.com/docs/guides/organizations/control-access/roles-and-permissions

### 9. Reverse proxy / HTTPS
- **Caddy**
- Automatic Let's Encrypt in production; self-signed for dev
- Required for getUserMedia on iPad

---

## Child session flow

1. iPad receives child audio via LiveKit WebRTC
2. Deepgram Flux transcribes and detects turn end
3. Hume scores vocal engagement from the audio stream
4. OpenAI conductor checks room context, progress snapshot, and next action
5. Output filter applies child-safe or caregiver-safe wording policy
6. Dedicated TTS renders the approved response for playback
7. Supabase stores session events, transcripts, and environment data
8. Temporal triggers caregiver alerts or clinician review workflows
9. Caregiver iPad / TV dashboard reads live session state and progress

---

## Human-in-the-loop boundaries

- AI may coach and score structured drills
- AI must escalate when confidence drops or max retries reached
- AI must request room adjustments when environment is off-standard
- AI must not diagnose
- AI must not override clinician-set goals or constraints

---

## Voice reliability requirements

- Continuous mic capture with clear recording state indicator
- Barge-in while system is speaking
- Streaming partial transcripts for caregiver debug view
- Graceful fallback: if STT/TTS/reasoning latency spikes, play cached "please wait" prompt
- Persistent transcript + event log for audit and clinician review
- Separate voice styles for child-facing, caregiver-facing, clinician-facing output
- Latency tracking: turn_end → first_transcript → first_token → first_audio_byte → playback_start

---

## Medical and compliance requirements

| Requirement | Status |
|-------------|--------|
| HTTPS everywhere | Pending (Caddy) |
| HIPAA BAA — Deepgram | Available, must be signed |
| HIPAA BAA — OpenAI | Available, must be signed |
| HIPAA BAA — Supabase | Available on Pro+, must be signed |
| COPPA consent (children < 13) | Not yet implemented |
| Audit log (who accessed PHI) | Partial (observability middleware) |
| Data encryption at rest | Supabase default (AES-256) |
| Session recording for clinician review | Not yet implemented |
| Clinician override of AI decisions | Escalation queue exists, override not yet wired |
| Auth + role-based access | Clerk configured, passthrough mode currently |
