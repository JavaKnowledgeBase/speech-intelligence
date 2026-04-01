#!/usr/bin/env python
"""
Seed reference data to Supabase for speech-intelligence.

Writes the seeded children, caregivers, clinicians, communication profiles,
environment profiles, curriculum targets, and reference vectors from the
in-memory store to Supabase tables.

Usage:
    # Dry run (no writes):
    python scripts/seed_supabase.py --dry-run

    # Live upsert:
    python scripts/seed_supabase.py

Environment:
    SUPABASE_URL                 Required for live mode
    SUPABASE_SERVICE_ROLE_KEY    Required for live mode
"""
from __future__ import annotations

import argparse
import json
import sys
import os

# Allow running from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data import InMemoryStore
from app.db.client import db


def _upsert(client, table: str, payload: dict, on_conflict: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] {table}: {list(payload.keys())}")
        return
    client.table(table).upsert(payload, on_conflict=on_conflict).execute()


def seed(dry_run: bool = False) -> None:
    store = InMemoryStore()
    client = None if dry_run else db.get()

    if not dry_run and client is None:
        print("ERROR: Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
        sys.exit(1)

    print(f"Seeding speech-intelligence reference data {'(dry-run)' if dry_run else '(live)'}...")

    # ── Clinicians ──────────────────────────────────────────────────────────
    print("\nClinicians:")
    for clinician in store.clinicians.values():
        payload = {
            "external_clinician_id": clinician.clinician_id,
            "name": clinician.name,
        }
        if not dry_run:
            try:
                client.table("clinicians").upsert(payload, on_conflict="external_clinician_id").execute()
                print(f"  upserted clinician {clinician.clinician_id}")
            except Exception as exc:
                print(f"  WARN: clinician {clinician.clinician_id} skipped ({exc})")
        else:
            print(f"  [dry-run] clinicians: {list(payload.keys())}")

    # ── Organizations (default placeholder) ────────────────────────────────
    print("\nOrganizations:")
    org_payload = {
        "external_org_id": "org-default",
        "name": "Default Organization",
    }
    _upsert(client, "organizations", org_payload, "external_org_id", dry_run)

    # ── Children ────────────────────────────────────────────────────────────
    print("\nChildren:")
    org_id: str | None = None
    if not dry_run:
        rows = client.table("organizations").select("id").eq("external_org_id", "org-default").limit(1).execute().data or []
        org_id = rows[0]["id"] if rows else None

    for child in store.children.values():
        payload: dict = {
            "external_child_id": child.child_id,
            "caregiver_external_id": child.caregiver_id,
            "clinician_external_id": child.clinician_id,
            "name": child.name,
            "age": child.age,
            "engagement_baseline": child.engagement_baseline,
        }
        if org_id:
            payload["organization_id"] = org_id
        _upsert(client, "children", payload, "external_child_id", dry_run)

    # ── Goals ────────────────────────────────────────────────────────────────
    print("\nGoals:")
    for child in store.children.values():
        child_uuid: str | None = None
        if not dry_run:
            rows = client.table("children").select("id").eq("external_child_id", child.child_id).limit(1).execute().data or []
            child_uuid = rows[0]["id"] if rows else None

        for goal in child.goals:
            payload = {
                "external_goal_id": goal.goal_id,
                "target_text": goal.target_text,
                "cue": goal.cue,
                "difficulty": goal.difficulty,
                "active": goal.active,
            }
            if child_uuid:
                payload["child_id"] = child_uuid
            _upsert(client, "goals", payload, "external_goal_id", dry_run)

    # ── Communication profiles ───────────────────────────────────────────────
    print("\nCommunication profiles:")
    all_profiles = list(store.child_communication_profiles.values()) + list(store.parent_communication_profiles.values())
    for profile in all_profiles:
        payload = {
            "external_profile_id": profile.profile_id,
            "audience": profile.audience,
            "owner_external_id": profile.owner_id,
            "preferred_tone": profile.preferred_tone,
            "preferred_pacing": profile.preferred_pacing,
            "sensory_notes": json.dumps(profile.sensory_notes),
            "banned_styles": json.dumps(profile.banned_styles),
            "preferred_phrases": json.dumps(profile.preferred_phrases),
            "calmness_level": profile.policy.calmness_level,
            "verbosity_limit": profile.policy.verbosity_limit,
            "encouragement_level": profile.policy.encouragement_level,
            "avoid_overstimulation": profile.policy.avoid_overstimulation,
            "avoid_exclamations": profile.policy.avoid_exclamations,
            "avoid_chatter": profile.policy.avoid_chatter,
        }
        _upsert(client, "communication_profiles", payload, "external_profile_id", dry_run)

    # ── Environment profiles ─────────────────────────────────────────────────
    print("\nEnvironment profiles:")
    for ep in store.environment_profiles.values():
        child_uuid = None
        if not dry_run:
            rows = client.table("children").select("id").eq("external_child_id", ep.child_id).limit(1).execute().data or []
            child_uuid = rows[0]["id"] if rows else None

        payload = {
            "external_environment_profile_id": ep.environment_profile_id,
            "room_label": ep.room_label,
            "baseline_room_embedding": ep.baseline_room_embedding or None,
            "baseline_visual_clutter_score": ep.baseline_visual_clutter_score,
            "baseline_noise_score": ep.baseline_noise_score,
            "baseline_lighting_score": ep.baseline_lighting_score,
            "baseline_distraction_notes": json.dumps(ep.baseline_distraction_notes),
            "recommended_adjustments": json.dumps(ep.recommended_adjustments),
            "preferred_objects": json.dumps(ep.preferred_objects),
            "avoid_objects": json.dumps(ep.avoid_objects),
        }
        if child_uuid:
            payload["child_id"] = child_uuid
        _upsert(client, "environment_profiles", payload, "external_environment_profile_id", dry_run)

    # ── Curriculum targets ───────────────────────────────────────────────────
    print("\nCurriculum targets:")
    for target in store.curriculum.values():
        payload = {
            "external_target_id": target.target_id,
            "target_type": target.target_type,
            "display_text": target.display_text,
            "phoneme_group": target.phoneme_group,
            "month_index": target.month_index,
            "difficulty_level": target.difficulty_level,
        }
        _upsert(client, "curriculum_targets", payload, "external_target_id", dry_run)

    # ── Reference vectors ────────────────────────────────────────────────────
    print("\nReference vectors:")
    for target_id, refs in store.reference_vectors.items():
        target_uuid: str | None = None
        if not dry_run:
            rows = client.table("curriculum_targets").select("id").eq("external_target_id", target_id).limit(1).execute().data or []
            target_uuid = rows[0]["id"] if rows else None

        for ref in refs:
            payload = {
                "external_reference_id": ref.reference_id,
                "modality": ref.modality,
                "source_label": ref.source_label,
                "quality_score": ref.quality_score,
                "age_band": ref.age_band,
                "notes": ref.notes,
                "embedding": ref.embedding or None,
            }
            if target_uuid:
                payload["target_id"] = target_uuid
            _upsert(client, "reference_vectors", payload, "external_reference_id", dry_run)

    print(f"\nDone. {len(store.children)} children, {len(store.curriculum)} targets, "
          f"{sum(len(v) for v in store.reference_vectors.values())} reference vectors seeded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed speech-intelligence reference data to Supabase.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no writes.")
    args = parser.parse_args()
    seed(dry_run=args.dry_run)
