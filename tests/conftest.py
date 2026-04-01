from __future__ import annotations

import sys
import os

# Make sure the project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.data import store, InMemoryStore
from app.workflows import workflow_manager


@pytest.fixture(autouse=True)
def reset_store():
    """
    Reset in-memory store and workflow manager to their seeded/empty state
    before every test so tests don't bleed state into each other.
    """
    fresh = InMemoryStore()
    store.children = fresh.children
    store.caregivers = fresh.caregivers
    store.clinicians = fresh.clinicians
    store.child_communication_profiles = fresh.child_communication_profiles
    store.parent_communication_profiles = fresh.parent_communication_profiles
    store.environment_profiles = fresh.environment_profiles
    store.curriculum = fresh.curriculum
    store.reference_vectors = fresh.reference_vectors
    store.attempt_vectors = fresh.attempt_vectors
    store.sessions = fresh.sessions
    store.alerts = fresh.alerts
    store.progress = fresh.progress
    # Reset the module-level workflow manager's review queue.
    workflow_manager.clinician_reviews = {}
    yield
