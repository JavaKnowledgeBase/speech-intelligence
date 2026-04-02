from __future__ import annotations

from datetime import timedelta

from app.clock import utc_now
from app.models import (
    CaregiverProfile,
    ChildAttemptVector,
    ChildProfile,
    ClinicianProfile,
    CommunicationProfile,
    EnvironmentProfile,
    Goal,
    OutputPolicy,
    ProgressSnapshot,
    ReferenceVector,
    TargetCurriculumItem,
)


class InMemoryStore:
    def __init__(self) -> None:
        self.children: dict[str, ChildProfile] = {}
        self.caregivers: dict[str, CaregiverProfile] = {}
        self.clinicians: dict[str, ClinicianProfile] = {}
        self.child_communication_profiles: dict[str, CommunicationProfile] = {}
        self.parent_communication_profiles: dict[str, CommunicationProfile] = {}
        self.environment_profiles: dict[str, EnvironmentProfile] = {}
        self.curriculum: dict[str, TargetCurriculumItem] = {}
        self.reference_vectors: dict[str, list[ReferenceVector]] = {}
        self.attempt_vectors: dict[str, list[ChildAttemptVector]] = {}
        self.sessions: dict[str, object] = {}
        self.alerts: dict[str, object] = {}
        self.progress: dict[tuple[str, str], ProgressSnapshot] = {}
        self.voice_runtime_checkpoints: dict[str, list[object]] = {}
        self.voice_runtime_transcripts: dict[str, list[object]] = {}
        self.voice_runtime_events: dict[str, list[object]] = {}
        self.voice_runtime_connections: dict[str, object] = {}
        self.voice_playback_items: dict[str, list[object]] = {}
        self.voice_synthesis_jobs: dict[str, list[object]] = {}
        self._seed()

    def _seed_curriculum(self) -> None:
        targets = [("target-a", "letter", "a", "vowel"), ("target-b", "letter", "b", "bilabial"), ("target-m", "letter", "m", "bilabial"), ("target-p", "letter", "p", "bilabial"), ("target-t", "letter", "t", "alveolar"), ("target-d", "letter", "d", "alveolar"), ("target-k", "letter", "k", "velar"), ("target-g", "letter", "g", "velar"), ("target-s", "letter", "s", "fricative"), ("target-n", "letter", "n", "nasal"), ("target-0", "number", "0", "number"), ("target-1", "number", "1", "number"), ("target-2", "number", "2", "number"), ("target-3", "number", "3", "number"), ("target-4", "number", "4", "number"), ("target-5", "number", "5", "number"), ("target-6", "number", "6", "number"), ("target-7", "number", "7", "number"), ("target-8", "number", "8", "number"), ("target-9", "number", "9", "number")]
        for idx, (target_id, target_type, display_text, phoneme_group) in enumerate(targets, start=1):
            self.curriculum[target_id] = TargetCurriculumItem(target_id=target_id, target_type=target_type, display_text=display_text, phoneme_group=phoneme_group, month_index=1, difficulty_level=1 if idx <= 10 else 2)

    def _seed_reference_vectors(self) -> None:
        for target_id, item in list(self.curriculum.items())[:4]:
            self.reference_vectors[target_id] = [
                ReferenceVector(reference_id=f"{target_id}-audio-1", target_id=target_id, modality="audio", source_label=f"clean-audio-{item.display_text}", quality_score=0.95, age_band="3-6", notes="clear exemplar", embedding=[0.91, 0.12, 0.33, 0.44]),
                ReferenceVector(reference_id=f"{target_id}-noise-1", target_id=target_id, modality="noise", source_label=f"light-noise-{item.display_text}", quality_score=0.79, age_band="3-6", notes="light room noise", embedding=[0.62, 0.21, 0.27, 0.39]),
                ReferenceVector(reference_id=f"{target_id}-lip-1", target_id=target_id, modality="lip", source_label=f"lip-shape-{item.display_text}", quality_score=0.92, age_band="3-6", notes="front mouth visible", embedding=[0.71, 0.81, 0.18, 0.22]),
                ReferenceVector(reference_id=f"{target_id}-emotion-1", target_id=target_id, modality="emotion", source_label=f"calm-tone-{item.display_text}", quality_score=0.9, age_band="3-6", notes="calm affect", embedding=[0.41, 0.52, 0.62, 0.73]),
            ]

    def _seed(self) -> None:
        clinician = ClinicianProfile(clinician_id="slp-1", name="Dr. Maya Chen", child_ids=["child-1", "child-2"])
        caregiver_1 = CaregiverProfile(caregiver_id="caregiver-1", name="Alex Parker", child_ids=["child-1"])
        caregiver_2 = CaregiverProfile(caregiver_id="caregiver-2", name="Jordan Rivera", child_ids=["child-2"])
        child_1_goals = [Goal(goal_id="goal-1", target_text="ba", cue="Tap your lips together, then say ba."), Goal(goal_id="goal-2", target_text="ma", cue="Close your lips and hum gently for ma."), Goal(goal_id="goal-3", target_text="pa", cue="Use a small puff of air for pa.")]
        child_2_goals = [Goal(goal_id="goal-4", target_text="ba", cue="Watch the avatar and repeat ba."), Goal(goal_id="goal-5", target_text="me", cue="Smile and say me clearly.")]
        self.children["child-1"] = ChildProfile(child_id="child-1", name="Liam", age=4, caregiver_id="caregiver-1", clinician_id="slp-1", goals=child_1_goals, streak_days=3, engagement_baseline=0.82)
        self.children["child-2"] = ChildProfile(child_id="child-2", name="Ava", age=5, caregiver_id="caregiver-2", clinician_id="slp-1", goals=child_2_goals, streak_days=5, engagement_baseline=0.76)
        self.caregivers[caregiver_1.caregiver_id] = caregiver_1
        self.caregivers[caregiver_2.caregiver_id] = caregiver_2
        self.clinicians[clinician.clinician_id] = clinician
        self.child_communication_profiles["child-1"] = CommunicationProfile(profile_id="comm-child-1", audience="child", owner_id="child-1", preferred_tone="gentle and warm", preferred_pacing="slow and short", sensory_notes=["low stimulation", "one cue at a time"], banned_styles=["loud", "fast", "overexcited"], preferred_phrases=["quiet try", "small step", "good calm work"], policy=OutputPolicy(policy_id="policy-child-1", calmness_level=5, verbosity_limit=72, encouragement_level=3))
        self.child_communication_profiles["child-2"] = CommunicationProfile(profile_id="comm-child-2", audience="child", owner_id="child-2", preferred_tone="soft and encouraging", preferred_pacing="short and rhythmic", sensory_notes=["brief prompts", "steady pacing"], banned_styles=["chatty", "intense"], preferred_phrases=["try together", "quiet sound", "good steady try"], policy=OutputPolicy(policy_id="policy-child-2", calmness_level=5, verbosity_limit=78, encouragement_level=4))
        self.parent_communication_profiles["caregiver-1"] = CommunicationProfile(profile_id="comm-parent-1", audience="parent", owner_id="caregiver-1", preferred_tone="calm and practical", preferred_pacing="clear and brief", sensory_notes=["avoid overload"], banned_styles=["alarmist", "verbose"], preferred_phrases=["one calm prompt", "brief model", "quiet support"], policy=OutputPolicy(policy_id="policy-parent-1", calmness_level=5, verbosity_limit=132, encouragement_level=2))
        self.parent_communication_profiles["caregiver-2"] = CommunicationProfile(profile_id="comm-parent-2", audience="parent", owner_id="caregiver-2", preferred_tone="steady and supportive", preferred_pacing="short and actionable", sensory_notes=["minimize interruptions"], banned_styles=["chatter", "pressure"], preferred_phrases=["simple cue", "single model", "calm repetition"], policy=OutputPolicy(policy_id="policy-parent-2", calmness_level=5, verbosity_limit=136, encouragement_level=2))
        self.environment_profiles["child-1"] = EnvironmentProfile(environment_profile_id="env-child-1", child_id="child-1", room_label="Living room learning corner", baseline_room_embedding=[0.55, 0.33, 0.61, 0.29], baseline_visual_clutter_score=0.28, baseline_noise_score=0.2, baseline_lighting_score=0.72, baseline_distraction_notes=["keep side table clear", "turn off TV"], recommended_adjustments=["clear bright toys from the immediate view", "keep one chair and one visual cue only"], preferred_objects=["small chair", "therapy mirror"], avoid_objects=["tv", "tablet with cartoons", "flashing toy"])
        self.environment_profiles["child-2"] = EnvironmentProfile(environment_profile_id="env-child-2", child_id="child-2", room_label="Bedroom desk area", baseline_room_embedding=[0.48, 0.27, 0.58, 0.31], baseline_visual_clutter_score=0.24, baseline_noise_score=0.18, baseline_lighting_score=0.69, baseline_distraction_notes=["limit wall movement", "keep desk simple"], recommended_adjustments=["close nearby toy bins", "face the chair away from moving distractions"], preferred_objects=["desk lamp", "plain chair"], avoid_objects=["spinning toy", "open toy shelf"])
        self._seed_curriculum()
        self._seed_reference_vectors()
        self.attempt_vectors["child-1"] = [ChildAttemptVector(attempt_id="attempt-1", child_id="child-1", target_id="target-b", session_id="seed-session-1", audio_embedding=[0.88, 0.14, 0.31, 0.43], lip_embedding=[0.69, 0.79, 0.2, 0.25], emotion_embedding=[0.4, 0.49, 0.6, 0.69], noise_embedding=[0.58, 0.19, 0.28, 0.35], top_match_reference_id="target-b-audio-1", cosine_similarity=0.93, success_flag=True)]
        now = utc_now()
        self.progress[("child-1", "ba")] = ProgressSnapshot(child_id="child-1", target_text="ba", attempts=8, successes=6, mastery_score=0.75, last_practiced_at=now - timedelta(days=1))
        self.progress[("child-1", "ma")] = ProgressSnapshot(child_id="child-1", target_text="ma", attempts=5, successes=2, mastery_score=0.4, last_practiced_at=now - timedelta(days=2))
        self.progress[("child-2", "ba")] = ProgressSnapshot(child_id="child-2", target_text="ba", attempts=7, successes=5, mastery_score=0.71, last_practiced_at=now - timedelta(hours=12))


store = InMemoryStore()
