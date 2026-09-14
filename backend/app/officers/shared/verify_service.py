import uuid as _uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.sla import ComplaintVerificationAction, Escalation
from app.models.complaint import Complaint
from app.models.officer import Officer
from app.core.sla.assign_worker import assign_worker_to_complaint


class InvalidAction(Exception):
    pass


class ComplaintNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("Complaint not found")


class OfficerNotAuthorized(Exception):
    pass


async def perform_verification_action(
    db: AsyncSession,
    officer: Officer,
    complaint_id: str,
    action_type: str,
    reason: str | None = None,
) -> dict:
    """Execute a verification action on a complaint.

    DB triggers handle cascading side-effects for dismiss/wait/escalate.
    For verify, Python explicitly assigns a worker and sets status='assigned'.
    """

    try:
        complaint_uuid = _uuid.UUID(complaint_id)
    except ValueError:
        raise ComplaintNotFound()

    result = await db.execute(
        select(Complaint).where(Complaint.id == complaint_uuid)
    )
    complaint = result.scalar_one_or_none()

    if not complaint:
        raise ComplaintNotFound()

    # ── Jurisdiction authorization ───────────────────────────────────────
    jurisdiction_map = {
        "panchayat": complaint.panchayat_id,
        "mandal": complaint.mandal_id,
        "district": complaint.district_id,
    }
    if jurisdiction_map.get(officer.level) != officer.jurisdiction_id:
        raise OfficerNotAuthorized("Complaint not in officer's jurisdiction")

    if complaint.current_review_level != officer.level:
        raise OfficerNotAuthorized(
            f"Complaint is at {complaint.current_review_level} level, "
            f"officer is at {officer.level} level"
        )

    # ── Input validation ─────────────────────────────────────────────────
    if action_type not in ("verify", "dismiss", "wait", "escalate"):
        raise InvalidAction(f"Unknown action type '{action_type}'")

    if action_type in ("dismiss", "wait", "escalate") and not reason:
        raise InvalidAction("Reason is required for this action")

    # ── Verify ───────────────────────────────────────────────────────────
    if action_type == "verify":
        if complaint.status not in ("submitted", "waiting", "reopened"):
            raise InvalidAction(f"Cannot verify from status '{complaint.status}'")

        assignment = await assign_worker_to_complaint(db, complaint, officer)

        action = ComplaintVerificationAction(
            complaint_id=complaint.id,
            officer_id=officer.id,
            action_type="verify",
            review_level=officer.level,
        )
        db.add(action)
        await db.flush()
        return {
            "status": "success",
            "action": "verify",
            "assignment_id": str(assignment.id),
        }

    # ── Dismiss ──────────────────────────────────────────────────────────
    elif action_type == "dismiss":
        if complaint.status not in ("submitted", "waiting"):
            raise InvalidAction(f"Cannot dismiss from status '{complaint.status}'")

        action = ComplaintVerificationAction(
            complaint_id=complaint.id,
            officer_id=officer.id,
            action_type="dismiss",
            reason=reason,
            review_level=officer.level,
        )
        db.add(action)
        await db.flush()  # triggers fire: complaint.status → 'dismissed'
        return {"status": "success", "action": "dismiss"}

    # ── Wait ─────────────────────────────────────────────────────────────
    elif action_type == "wait":
        if complaint.status not in ("submitted", "reopened"):
            raise InvalidAction(f"Cannot wait from status '{complaint.status}'")

        action = ComplaintVerificationAction(
            complaint_id=complaint.id,
            officer_id=officer.id,
            action_type="wait",
            reason=reason,
            review_level=officer.level,
        )
        db.add(action)
        await db.flush()  # triggers fire: complaint.status → 'waiting', wait_count++
        return {"status": "success", "action": "wait"}

    # ── Escalate ─────────────────────────────────────────────────────────
    else:  # escalate
        if complaint.status not in ("submitted", "waiting", "reopened"):
            raise InvalidAction(f"Cannot escalate from status '{complaint.status}'")

        action = ComplaintVerificationAction(
            complaint_id=complaint.id,
            officer_id=officer.id,
            action_type="escalate",
            reason=reason,
            review_level=officer.level,
        )
        db.add(action)

        to_level = "mandal" if officer.level == "panchayat" else "district"
        escalation = Escalation(
            complaint_id=complaint.id,
            from_level=officer.level,
            to_level=to_level,
            trigger_type="manual",
            escalated_by=officer.id,
            reason=reason,
        )
        db.add(escalation)
        await db.flush()  # triggers fire: complaint.status → 'escalated', review_level updated
        return {"status": "success", "action": "escalate"}
