from uuid import uuid4

from sqlalchemy import select

from app.storage.database import DatabaseManager
from app.storage.schema import AuditRecord, ClosePackRecord, ExceptionRecord, FeedbackRecord


REVIEW_STATES = {
    "APPROVE": "APPROVED",
    "REJECT": "REJECTED",
    "LEAVE_UNRESOLVED": "LEFT_UNRESOLVED",
}


class ReviewService:
    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def list_exceptions(self, tenant_id: str, run_id: str) -> list[dict]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(ExceptionRecord).where(
                        ExceptionRecord.tenant_id == tenant_id, ExceptionRecord.run_id == run_id
                    ).order_by(ExceptionRecord.created_at)
                )
            )
        return [
            {
                "exception_id": row.id,
                "run_id": row.run_id,
                "proof_id": row.proof_id,
                "exception_type": row.exception_type,
                "amount_paise": row.amount_paise,
                "state": row.state,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    def review_exception(
        self,
        tenant_id: str,
        exception_id: str,
        action: str,
        actor_id: str,
        reason: str,
    ) -> dict:
        if action not in REVIEW_STATES:
            raise ValueError("review action must be APPROVE, REJECT, or LEAVE_UNRESOLVED")
        cleaned_reason = reason.strip()
        if sum(1 for char in cleaned_reason if char.isprintable() and not char.isspace()) < 5:
            raise ValueError("review reason must contain at least five characters")
        with self.database.session() as session:
            exception = session.scalar(
                select(ExceptionRecord).where(
                    ExceptionRecord.id == exception_id, ExceptionRecord.tenant_id == tenant_id
                )
            )
            if exception is None:
                raise KeyError(exception_id)
            if session.scalar(
                select(ClosePackRecord.id).where(
                    ClosePackRecord.tenant_id == tenant_id,
                    ClosePackRecord.run_id == exception.run_id,
                )
            ) is not None:
                raise PermissionError("review mutations are frozen after Final Close Pack creation")
            previous = exception.state
            if previous != "OPEN":
                raise ValueError("review item is no longer OPEN")
            new_state = REVIEW_STATES[action]
            exception.state = new_state
            audit = AuditRecord(
                id=f"audit_{uuid4().hex[:18]}",
                tenant_id=tenant_id,
                run_id=exception.run_id,
                actor_id=actor_id,
                object_type="EXCEPTION",
                object_id=exception.id,
                previous_state=previous,
                new_state=new_state,
                reason=cleaned_reason,
            )
            session.add(audit)
        return {
            "audit_id": audit.id,
            "exception_id": exception_id,
            "previous_state": previous,
            "new_state": new_state,
            "reason": cleaned_reason,
            "actor_id": actor_id,
        }

    def challenge_proof(
        self, tenant_id: str, run_id: str, proof_id: str, actor_id: str, feedback_type: str, comment: str
    ) -> dict:
        if feedback_type not in {"INCORRECT_MATCH", "INCORRECT_EXCEPTION", "PROOF_UNCLEAR", "OTHER"}:
            raise ValueError("unsupported feedback type")
        cleaned_comment = comment.strip()
        if sum(1 for char in cleaned_comment if char.isprintable() and not char.isspace()) < 5:
            raise ValueError("challenge comment must contain at least five visible characters")
        feedback = FeedbackRecord(
            id=f"feedback_{uuid4().hex[:18]}",
            tenant_id=tenant_id,
            run_id=run_id,
            proof_id=proof_id,
            actor_id=actor_id,
            feedback_type=feedback_type,
            comment=cleaned_comment,
        )
        with self.database.session() as session:
            session.add(feedback)
        return {
            "feedback_id": feedback.id,
            "status": "RECORDED_FOR_OFFLINE_REVIEW",
            "feedback_type": feedback.feedback_type,
            "comment": feedback.comment,
        }

    def list_audit(self, tenant_id: str, run_id: str) -> list[dict]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(AuditRecord).where(
                        AuditRecord.tenant_id == tenant_id, AuditRecord.run_id == run_id
                    ).order_by(AuditRecord.created_at)
                )
            )
        return [
            {
                "audit_id": row.id,
                "actor_id": row.actor_id,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "previous_state": row.previous_state,
                "new_state": row.new_state,
                "reason": row.reason,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
