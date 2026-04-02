from __future__ import annotations

from app.config import settings
from app.models import AgentEdge, AgentGraph, AgentNode, ArchitectureBlueprint, CommunicationProfile, ExpertDecision, FilteredMessage, ProviderComponent, ProviderStatus


# ── Levenshtein distance (no dependencies) ────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            temp = dp[j]
            dp[j] = prev if ca == cb else 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[len(b)]


def _char_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 1.0 - _levenshtein(a, b) / max(len(a), len(b))


def _phonetic_key(word: str) -> str:
    """Minimal soundex-style key for phonetic grouping (no deps).

    Sufficient for child single-word speech targets (CVC and CVCV words).
    Not a standards-compliant implementation — built for speed in the hot path.
    """
    w = word.lower().strip()
    if not w:
        return ""
    # Remove non-alpha
    w = "".join(c for c in w if c.isalpha())
    if not w:
        return ""
    codes = {
        "bfpv": "1", "cgjkqsxyz": "2", "dt": "3", "l": "4", "mn": "5", "r": "6"
    }
    key = w[0]
    last = ""
    for ch in w[1:]:
        code = next((v for k, v in codes.items() if ch in k), "0")
        if code != "0" and code != last:
            key += code
        last = code
    return key[:4].ljust(4, "0")


def _openai_score(expected: str, heard: str) -> float | None:
    """Call OpenAI to assess whether the child correctly produced the target.

    Returns a pronunciation score (0–1) or None on failure.
    Only called when OPENAI_API_KEY + USE_LIVE_PROVIDER_CALLS are set.
    Uses a minimal prompt to keep latency low (gpt-4o-mini is ~200ms p50).
    """
    if not settings.use_live_provider_calls or not settings.configured(settings.openai_api_key):
        return None
    try:
        import httpx
        payload = {
            "model": "gpt-4o-mini",
            "max_output_tokens": 10,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a speech-language pathologist assistant. "
                        "A child attempted to say a target word. "
                        "Return ONLY a decimal score from 0.00 to 1.00 indicating how well "
                        "the transcribed speech matches the target. "
                        "1.00 = exact or phonetically correct. "
                        "0.00 = completely wrong. No other text."
                    ),
                },
                {
                    "role": "user",
                    "content": f'Target: "{expected}". Child said: "{heard}".',
                },
            ],
        }
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            # Responses API: output[0].content[0].text
            text = data["output"][0]["content"][0]["text"].strip()
            return max(0.0, min(1.0, float(text)))
    except Exception:
        return None


class SpeechExpert:
    provider_name = "Deepgram Nova / Flux"

    def evaluate(self, expected_text: str, transcript: str) -> tuple[float, ExpertDecision]:
        expected = expected_text.strip().lower()
        heard = transcript.strip().lower()

        # Try OpenAI scoring first (better phoneme awareness)
        ai_score = _openai_score(expected, heard)
        if ai_score is not None:
            summary = (
                f"OpenAI scored the attempt at {ai_score:.2f} for target '{expected_text}'."
            )
            return ai_score, ExpertDecision(
                expert="speech_scoring_expert",
                provider="OpenAI gpt-4o-mini",
                confidence=round(ai_score, 2),
                summary=summary,
            )

        # Local fallback: character similarity + phonetic key match
        char_sim = _char_similarity(expected, heard)
        phonetic_match = _phonetic_key(expected) == _phonetic_key(heard)

        if heard == expected:
            score = 0.96
            summary = f"Exact lexical match for target '{expected_text}'."
        elif char_sim >= 0.85 or phonetic_match:
            score = round(0.7 + (char_sim * 0.25), 2)
            summary = f"Strong phonetic match for '{expected_text}' (char sim {char_sim:.2f}, phonetic {'✓' if phonetic_match else '✗'})."
        elif char_sim >= 0.55 or (heard and expected and heard[0] == expected[0]):
            score = round(0.45 + (char_sim * 0.3), 2)
            summary = f"Partial match for '{expected_text}' (char sim {char_sim:.2f})."
        elif heard:
            score = round(max(0.1, char_sim * 0.5), 2)
            summary = f"Weak alignment with target '{expected_text}' (char sim {char_sim:.2f})."
        else:
            score = 0.0
            summary = f"No speech detected for target '{expected_text}'."

        return score, ExpertDecision(
            expert="speech_scoring_expert",
            provider=self.provider_name,
            confidence=round(score, 2),
            summary=summary,
        )


class EngagementExpert:
    provider_name = "Hume Expression Measurement"

    def assess(self, attention_score: float) -> tuple[float, ExpertDecision]:
        engagement = round(attention_score, 2)
        if engagement >= 0.75:
            summary = "Child appears engaged enough to continue autonomous practice."
        elif engagement >= 0.5:
            summary = "Engagement is softening; use reward or cueing before escalating."
        else:
            summary = "Engagement is low; consider caregiver intervention or a break."
        return engagement, ExpertDecision(
            expert="engagement_expert",
            provider=self.provider_name,
            confidence=engagement,
            summary=summary,
        )


class ReasoningExpert:
    provider_name = "OpenAI Responses API"

    def decide(
        self,
        pronunciation_score: float,
        engagement_score: float,
        retries_used: int,
        max_retries: int,
    ) -> ExpertDecision:
        # Try OpenAI Responses API for richer conductor reasoning
        ai_decision = self._openai_decide(
            pronunciation_score, engagement_score, retries_used, max_retries
        )
        if ai_decision is not None:
            return ai_decision

        # Local fallback: weighted formula
        confidence = max(
            0.0,
            min(
                1.0,
                (pronunciation_score * 0.7) + (engagement_score * 0.3) - min(retries_used * 0.08, 0.2),
            ),
        )
        if pronunciation_score >= 0.9 and engagement_score >= 0.55:
            summary = "Advance to the next exercise. Confidence is high enough for autonomous progression."
        elif confidence >= 0.58 and retries_used < max_retries:
            summary = "Retry with scaffolding. The child may still succeed with another cue."
        else:
            summary = "Escalate. The system should not reinforce this turn without human support."
        return ExpertDecision(
            expert="session_conductor",
            provider=self.provider_name,
            confidence=round(confidence, 2),
            summary=summary,
        )

    def _openai_decide(
        self,
        pronunciation_score: float,
        engagement_score: float,
        retries_used: int,
        max_retries: int,
    ) -> ExpertDecision | None:
        if not settings.use_live_provider_calls or not settings.configured(settings.openai_api_key):
            return None
        try:
            import httpx

            payload = {
                "model": "gpt-4o-mini",
                "max_output_tokens": 80,
                "input": [
                    {
                        "role": "system",
                        "content": (
                            "You are the session conductor for a pediatric speech therapy AI. "
                            "Given the metrics below, decide whether to: advance (child succeeded), "
                            "retry (child needs another try), or escalate (human caregiver needed). "
                            "Respond in JSON only: "
                            '{{"action": "advance"|"retry"|"escalate", "confidence": 0.00-1.00, "reason": "short reason"}}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"pronunciation_score={pronunciation_score:.2f} "
                            f"engagement_score={engagement_score:.2f} "
                            f"retries_used={retries_used} max_retries={max_retries}"
                        ),
                    },
                ],
            }
            with httpx.Client(timeout=8.0) as client:
                resp = client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                import json
                text = data["output"][0]["content"][0]["text"].strip()
                parsed = json.loads(text)
                confidence = float(parsed.get("confidence", 0.7))
                reason = parsed.get("reason", "OpenAI conductor decision.")
                return ExpertDecision(
                    expert="session_conductor",
                    provider="OpenAI gpt-4o-mini",
                    confidence=round(confidence, 2),
                    summary=reason,
                )
        except Exception:
            return None


class PlannerExpert:
    provider_name = "OpenAI Responses API"

    def explain_goal_choice(self, target_text: str, mastery_score: float) -> ExpertDecision:
        gap = round(1 - mastery_score, 2)
        return ExpertDecision(
            expert="care_plan_expert",
            provider=self.provider_name,
            confidence=max(0.5, gap),
            summary=f"Selected '{target_text}' because it has the largest remaining mastery gap.",
        )


class WorkflowExpert:
    provider_name = "Temporal"

    def record(self, message: str) -> ExpertDecision:
        return ExpertDecision(expert="workflow_expert", provider=self.provider_name, confidence=0.9, summary=message)


class OutputFilterExpert:
    provider_name = "OpenAI Responses API or custom empathy layer"

    def filter_text(
        self,
        audience: str,
        text: str,
        profile: CommunicationProfile | None = None,
    ) -> tuple[FilteredMessage, ExpertDecision]:
        # Try OpenAI for context-aware, profile-informed message generation
        ai_result = self._openai_filter(audience, text, profile)
        if ai_result is not None:
            return ai_result

        # Local rule-based fallback
        return self._local_filter(audience, text, profile)

    def _openai_filter(
        self,
        audience: str,
        text: str,
        profile: CommunicationProfile | None,
    ) -> tuple[FilteredMessage, ExpertDecision] | None:
        if not settings.use_live_provider_calls or not settings.configured(settings.openai_api_key):
            return None
        try:
            import httpx

            limit = 90 if audience == "child" else 140
            calmness = "maximum calmness, no exclamations"
            if profile is not None:
                limit = profile.policy.verbosity_limit
                if profile.policy.calmness_level >= 4:
                    calmness = "very calm, peaceful, no exclamations"

            system_prompt = (
                f"You are an output filter for a pediatric speech therapy app. "
                f"Rewrite the message for the {audience} audience. "
                f"Rules: {calmness}, under {limit} characters, no diagnosis language, "
                f"no exclamation marks, simple words a child can understand if audience is child. "
                f"Return ONLY the rewritten message text, nothing else."
            )

            payload = {
                "model": "gpt-4o-mini",
                "max_output_tokens": 60,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
            }
            with httpx.Client(timeout=6.0) as client:
                resp = client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                filtered_text = data["output"][0]["content"][0]["text"].strip()

            style_tags = ["ai-filtered", "calm", "profile-aware" if profile else "default"]
            return FilteredMessage(
                audience=audience,
                text=filtered_text,
                style_tags=style_tags,
            ), ExpertDecision(
                expert="output_filter_expert",
                provider="OpenAI gpt-4o-mini",
                confidence=0.95,
                summary=f"OpenAI rewrote {audience} output using calmness rules ({calmness}).",
            )
        except Exception:
            return None

    def _local_filter(
        self,
        audience: str,
        text: str,
        profile: CommunicationProfile | None,
    ) -> tuple[FilteredMessage, ExpertDecision]:
        cleaned = " ".join(text.strip().split())
        replacements = {
            "Please": "Please calmly",
            "Let's": "Let us",
            "!": ".",
            "very": "",
            "really": "",
            "right now": "now",
        }
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        style_tags = ["calm", "constructive"]
        limit = 90 if audience == "child" else 140
        if profile is not None:
            limit = profile.policy.verbosity_limit
            style_tags.append(profile.preferred_tone)
            if profile.policy.avoid_chatter:
                style_tags.append("non-chatty")
            if profile.policy.calmness_level >= 4:
                style_tags.append("peaceful")
            for banned in profile.banned_styles:
                cleaned = cleaned.replace(banned, "")
            if profile.preferred_phrases and audience == "child" and cleaned.lower().startswith("let us try"):
                cleaned = f"{profile.preferred_phrases[0].capitalize()}. {cleaned}"
        cleaned = " ".join(cleaned.split())
        if len(cleaned) > limit:
            cleaned = cleaned[: max(limit - 3, 10)].rstrip() + "..."
        if not cleaned.endswith("."):
            cleaned += "."
        if audience == "child":
            style_tags.extend(["gentle", "brief"])
        else:
            style_tags.extend(["clear", "supportive"])
        return FilteredMessage(
            audience=audience,
            text=cleaned.strip(),
            style_tags=list(dict.fromkeys(style_tags)),
        ), ExpertDecision(
            expert="output_filter_expert",
            provider=self.provider_name,
            confidence=0.92 if profile else 0.88,
            summary=f"Filtered {audience} output using {'profile-aware' if profile else 'default'} calmness policy.",
        )


class ProviderCatalog:
    @staticmethod
    def blueprint() -> ArchitectureBlueprint:
        return ArchitectureBlueprint(
            product_name="TalkBuddy AI",
            approach="Agentic, expert-routed speech therapy platform with third-party specialist services and human oversight.",
            components=[
                ProviderComponent(component="Realtime session transport", recommended_service="LiveKit Agents + WebRTC", role="Runs the low-latency child voice session, turn-taking, and media streaming layer.", source_url="https://docs.livekit.io/agents/", notes="LiveKit's docs describe a provider-agnostic agents framework with built-in observability and realtime media support."),
                ProviderComponent(component="Agent reasoning and tool use", recommended_service="OpenAI Responses API", role="Acts as the session conductor, care-plan expert, report-writing brain, environment reasoner, and output-filter layer.", source_url="https://openai.com/index/new-tools-and-features-in-the-responses-api/", notes="OpenAI states the Responses API is the core primitive for agentic applications and supports tools plus remote MCP servers."),
                ProviderComponent(component="Realtime multimodal fallback", recommended_service="OpenAI Realtime API", role="Supports speech-to-speech interactions when we want the child coach to be live and conversational.", source_url="https://platform.openai.com/docs/api-reference/realtime?api-mode=responses", notes="Official docs say Realtime supports low-latency speech-to-speech over WebRTC, WebSocket, and SIP."),
                ProviderComponent(component="Speech-to-text and turn detection", recommended_service="Deepgram Nova / Flux", role="Provides fast transcription, conversational turn detection, and vocabulary adaptation for therapy prompts.", source_url="https://deepgram.com/product/speech-to-text", notes="Deepgram positions Flux for conversational agents with integrated turn detection, and Nova-3 adds multilingual transcription plus vocabulary adaptation."),
                ProviderComponent(component="Engagement and affect analysis", recommended_service="Hume Expression Measurement", role="Measures vocal expression and prosody to estimate frustration, fatigue, or disengagement.", source_url="https://dev.hume.ai/docs/expression-measurement/overview", notes="Hume offers multimodal expression measurement across voice, audio, video, and text, which fits engagement-aware escalation."),
                ProviderComponent(component="Environment and scene analysis", recommended_service="OpenAI Responses API vision tools or custom scene pipeline", role="Checks 360 room captures against the child's preferred learning environment standard.", source_url="https://openai.com/index/new-tools-and-features-in-the-responses-api/", notes="Use a vision-capable reasoning pass first, then add a dedicated scene-analysis service if needed."),
                ProviderComponent(component="Durable workflow orchestration", recommended_service="Temporal", role="Runs long-lived workflows for reminders, escalations, report generation, and clinician review queues.", source_url="https://docs.temporal.io/", notes="Temporal is the strongest fit for durable retries, timers, and human-in-the-loop enterprise workflows."),
                ProviderComponent(component="Clinical data and storage", recommended_service="Supabase", role="Holds profiles, environment standards, curriculum targets, vector references, session events, and object storage.", source_url="https://supabase.com/docs/guides/getting-started/features", notes="Supabase gives us Postgres, storage, realtime, and edge functions in one platform, which is strong for a fast MVP with enterprise runway."),
                ProviderComponent(component="Auth and multi-tenant roles", recommended_service="Clerk Organizations", role="Handles caregiver, clinician, and enterprise admin authentication with organization-scoped permissions.", source_url="https://clerk.com/docs/guides/organizations/control-access/roles-and-permissions", notes="Clerk provides organization roles and custom permissions, which matches clinics and school tenants well."),
            ],
            implementation_notes=[
                "All child-facing and parent-facing output should pass through a dedicated output-filter expert before delivery.",
                "Profile-aware filter policies should be persisted and tuned per child and caregiver.",
                "Environment standards and multimodal reference vectors should become first-class persisted entities.",
            ],
        )

    @staticmethod
    def graph() -> AgentGraph:
        return AgentGraph(
            nodes=[
                AgentNode(agent_id="child_session_runtime", title="Child Session Runtime", responsibility="Handles live voice session transport and media state.", provider="LiveKit Agents"),
                AgentNode(agent_id="session_conductor", title="Session Conductor", responsibility="Decides advance, retry, reward, or escalate.", provider="OpenAI Responses API"),
                AgentNode(agent_id="speech_scoring_expert", title="Speech Scoring Expert", responsibility="Evaluates target production quality and turn structure.", provider="Deepgram Nova / Flux"),
                AgentNode(agent_id="engagement_expert", title="Engagement Expert", responsibility="Assesses frustration, attention, and need for redirection.", provider="Hume Expression Measurement"),
                AgentNode(agent_id="care_plan_expert", title="Care Plan Expert", responsibility="Chooses next goals and clinician-facing interventions.", provider="OpenAI Responses API"),
                AgentNode(agent_id="environment_expert", title="Environment Expert", responsibility="Compares the current room against the child's saved comfort and focus baseline.", provider="OpenAI Responses API or custom scene analysis"),
                AgentNode(agent_id="vector_match_expert", title="Vector Match Expert", responsibility="Finds the nearest multimodal reference cluster for the child's attempt.", provider="Supabase pgvector or Pinecone"),
                AgentNode(agent_id="workflow_expert", title="Workflow Expert", responsibility="Schedules reminders, escalations, and clinician review work.", provider="Temporal"),
                AgentNode(agent_id="reporting_expert", title="Reporting Expert", responsibility="Builds summaries for caregivers, SLPs, and enterprise admins.", provider="OpenAI Responses API"),
                AgentNode(agent_id="output_filter_expert", title="Output Filter Expert", responsibility="Filters every child and parent message using calmness policies and communication profiles.", provider="OpenAI Responses API or custom empathy layer"),
            ],
            edges=[
                AgentEdge(from_agent="child_session_runtime", to_agent="speech_scoring_expert", condition="New speech turn arrives."),
                AgentEdge(from_agent="child_session_runtime", to_agent="engagement_expert", condition="New audio/prosody segment arrives."),
                AgentEdge(from_agent="child_session_runtime", to_agent="environment_expert", condition="A session is about to start and the room must be checked."),
                AgentEdge(from_agent="speech_scoring_expert", to_agent="vector_match_expert", condition="Speech evidence is ready for nearest-reference comparison."),
                AgentEdge(from_agent="vector_match_expert", to_agent="session_conductor", condition="Closest reference cluster and similarity scores are ready."),
                AgentEdge(from_agent="engagement_expert", to_agent="session_conductor", condition="Attention and affect evidence is ready."),
                AgentEdge(from_agent="environment_expert", to_agent="session_conductor", condition="Room comfort and distraction check is ready."),
                AgentEdge(from_agent="session_conductor", to_agent="care_plan_expert", condition="Advance or remediation path must be selected."),
                AgentEdge(from_agent="session_conductor", to_agent="output_filter_expert", condition="Any child-facing or parent-facing output is about to be delivered."),
                AgentEdge(from_agent="workflow_expert", to_agent="output_filter_expert", condition="A caregiver-facing alert or guidance message is about to be delivered."),
                AgentEdge(from_agent="workflow_expert", to_agent="reporting_expert", condition="Session, alert, or review data must be summarized."),
            ],
        )

    @staticmethod
    def statuses() -> list[ProviderStatus]:
        live_mode = "live" if settings.use_live_provider_calls else "mock"
        return [
            ProviderStatus(provider="OpenAI Responses API", purpose="Agent reasoning, reporting, environment reasoning, and output filtering", configured=settings.configured(settings.openai_api_key), environment_key="OPENAI_API_KEY", mode=live_mode, notes="Used as the primary session conductor, care-plan expert, environment reasoner, and output filter."),
            ProviderStatus(provider="Deepgram", purpose="Streaming speech recognition and turn detection", configured=settings.configured(settings.deepgram_api_key), environment_key="DEEPGRAM_API_KEY", mode=live_mode, notes="Recommended first speech provider for low-latency child sessions."),
            ProviderStatus(provider="Hume", purpose="Engagement and affect analysis", configured=settings.configured(settings.hume_api_key), environment_key="HUME_API_KEY", mode=live_mode, notes="Supports escalation and re-engagement logic."),
            ProviderStatus(provider="LiveKit", purpose="Realtime media transport", configured=settings.livekit_configured, environment_key="LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET", mode=live_mode, notes="Recommended for child-facing live sessions. A signed access token also requires LIVEKIT_API_SECRET."),
            ProviderStatus(provider="Temporal", purpose="Durable workflow orchestration", configured=settings.configured(settings.temporal_host), environment_key="TEMPORAL_HOST", mode=live_mode, notes="Recommended for alerts, reminders, and review queues."),
            ProviderStatus(provider="Supabase", purpose="Clinical data, object storage, environment standards, curriculum targets, and vector state", configured=settings.supabase_configured, environment_key="SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY/SUPABASE_REPOSITORY_MODE", mode=live_mode, notes=f"Repository mode is '{settings.supabase_repository_mode}'. Auto mode prefers Supabase when configured and falls back to in-memory data on request failures."),
            ProviderStatus(provider="Clerk", purpose="Authentication and organizations", configured=settings.configured(settings.clerk_secret_key), environment_key="CLERK_SECRET_KEY", mode=live_mode, notes="Recommended for clinics, caregivers, and enterprise RBAC."),
        ]

