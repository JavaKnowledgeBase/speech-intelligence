from __future__ import annotations

from uuid import uuid4

from app.clock import utc_now
from app.data import store
from app.db import persistence
from app.models import Alert, AlertAcknowledgeResponse, ClinicianReviewItem, WorkflowQueueSnapshot


class WorkflowManager:
    def __init__(self) -> None:
        self.clinician_reviews: dict[str, ClinicianReviewItem] = {}

    def enqueue_clinician_review(self, child_id: str, session_id: str, summary: str, priority: str) -> ClinicianReviewItem:
        child = store.children[child_id]
        review = ClinicianReviewItem(
            review_id=f"review-{uuid4().hex[:8]}",
            clinician_id=child.clinician_id,
            child_id=child_id,
            session_id=session_id,
            priority=priority,
            summary=summary,
            created_at=utc_now(),
        )
        self.clinician_reviews[review.review_id] = review
        persistence.upsert_review(review)
        return review

    def snapshot(self) -> WorkflowQueueSnapshot:
        pending_alerts = [alert for alert in store.alerts.values() if not alert.acknowledged]
        clinician_reviews = sorted(
            self.clinician_reviews.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )
        return WorkflowQueueSnapshot(
            pending_alerts=pending_alerts,
            clinician_reviews=clinician_reviews,
        )

    def clinician_queue(self, clinician_id: str) -> list[ClinicianReviewItem]:
        return [item for item in self.clinician_reviews.values() if item.clinician_id == clinician_id]

    def caregiver_alerts(self, caregiver_id: str) -> list[Alert]:
        return [alert for alert in store.alerts.values() if alert.caregiver_id == caregiver_id]

    def acknowledge_alert(self, alert_id: str) -> AlertAcknowledgeResponse:
        alert = store.alerts[alert_id]
        alert.acknowledged = True
        persistence.acknowledge_alert(alert_id)
        review = self.enqueue_clinician_review(
            child_id=alert.child_id,
            session_id=alert.session_id,
            summary=f"Caregiver acknowledged alert '{alert.message}'. Review whether the target should be simplified or reassigned.",
            priority="medium",
        )
        return AlertAcknowledgeResponse(
            alert_id=alert_id,
            acknowledged=True,
            follow_up_review_id=review.review_id,
        )


workflow_manager = WorkflowManager()
