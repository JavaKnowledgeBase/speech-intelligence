# TalkBuddy AI Architecture

## Product shape

TalkBuddy should be built as an expert-routed agentic platform with human oversight, not as a single LLM app.

The child session should be handled by a conductor agent that consults narrow experts:

- speech scoring expert
- engagement expert
- care-plan expert
- escalation expert
- reporting expert
- workflow expert
- environment expert
- output filter expert

## Device targets

The app should support:

- tablets
- TVs
- desktops

That means the frontend should be optimized for:

- touch-first controls where appropriate
- large tap targets
- large visual prompts
- high legibility from several feet away on TV
- simple navigation without keyboard dependence for child therapy mode
- landscape layouts as a first-class target
- minimal reading burden for the child
- responsive layouts that also work well on desktop for caregiver, clinician, and admin workflows

The system should not assume a desktop mouse-and-keyboard setup for therapy sessions only, but desktop must still be fully supported as a product surface.

## Recommended stack

### 1. Realtime runtime
- LiveKit Agents + WebRTC
- Why: LiveKit officially positions its Agents framework as a realtime framework for voice and multimodal agents, with provider-agnostic integrations and observability.
- Source: https://docs.livekit.io/agents/

### 2. Agent brain
- OpenAI Responses API
- Why: OpenAI describes the Responses API as the core primitive for agentic applications and highlights built-in tools plus remote MCP support.
- Source: https://openai.com/index/new-tools-and-features-in-the-responses-api/

### 3. Speech-to-speech fallback
- OpenAI Realtime API
- Why: Official API docs say it supports low-latency speech-to-speech over WebRTC, WebSocket, and SIP.
- Source: https://platform.openai.com/docs/api-reference/realtime?api-mode=responses

### 4. Speech recognition
- Deepgram Nova / Flux
- Why: Deepgram's official materials position Flux for conversational voice agents with integrated turn detection, while Nova-3 emphasizes multilingual accuracy and vocabulary adaptation.
- Source: https://deepgram.com/product/speech-to-text
- Source: https://deepgram.com/learn/introducing-nova-3-speech-to-text-api

### 5. Engagement detection
- Hume Expression Measurement
- Why: Hume's docs state it measures nuanced human expression across voice, face, and language, which is valuable for frustration, fatigue, and redirection signals.
- Source: https://dev.hume.ai/docs/expression-measurement/overview

### 6. Workflow engine
- Temporal
- Why: Best fit for durable timers, retries, reminders, escalation queues, and human-in-the-loop workflows.
- Source: https://docs.temporal.io/

### 7. Data platform
- Supabase
- Why: Postgres, storage, realtime, and edge functions make it a strong MVP-to-enterprise backbone.
- Source: https://supabase.com/docs/guides/getting-started/features
- Source: https://supabase.com/docs/guides/functions

### 8. Identity and tenancy
- Clerk Organizations
- Why: Official docs support organization roles and custom permissions, which fit clinics, schools, and enterprise admin models.
- Source: https://clerk.com/docs/guides/organizations/control-access/roles-and-permissions

## Inference and caution

This is my recommended stack, not an absolute universal ranking.

Inference:
- LiveKit is the best realtime shell for fast execution and provider flexibility.
- OpenAI is the best conductor layer for tool-using agent workflows.
- Deepgram is the easiest first STT choice for live therapy sessions.
- Hume is the most relevant specialist API for affect-aware escalation.

Before production lock-in, benchmark Deepgram against AssemblyAI on real pediatric speech samples because child speech is a special-case accuracy problem.

## Architecture slice

### Child session flow
1. LiveKit receives child audio.
2. Deepgram transcribes and detects turns.
3. Hume scores vocal engagement.
4. OpenAI conductor checks room context, progress, and next action.
5. Supabase stores session and environment data.
6. Temporal triggers caregiver or clinician workflows.
7. Clinician and caregiver desktop/tablet views read reports and overrides.

### Human-in-the-loop boundaries
- AI may coach and score structured drills.
- AI should escalate when confidence drops.
- AI should ask for room adjustments when the environment is off-standard.
- AI should not diagnose or override clinician-set constraints.
