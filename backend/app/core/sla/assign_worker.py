from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.worker import Worker, WorkerAssignment
from app.models.sla import SlaConfig, SlaTracker
from app.models.complaint import Complaint
from app.models.officer import Officer
from datetime import timedelta

class NoWorkerAvailable(Exception):
    pass

async def assign_worker_to_complaint(db: AsyncSession, complaint: Complaint, officer: Officer) -> WorkerAssignment:
    # Workers always belong to a panchayat, so look them up by
    # the complaint's panchayat_id (not officer.jurisdiction_id)
    # to support mandal/district officers verifying complaints too.
    stmt = (
        select(Worker, func.count(WorkerAssignment.id).label("active_assignments"))
        .outerjoin(WorkerAssignment, (WorkerAssignment.worker_id == Worker.id) & (WorkerAssignment.is_active == True))
        .where(
            Worker.jurisdiction_id == complaint.panchayat_id,
            Worker.department_id == complaint.department_id,
            Worker.is_active == True,
        )
        .group_by(Worker.id)
    )
    result = await db.execute(stmt)
    workers = result.all()
    
    if not workers:
        raise NoWorkerAvailable("No active workers available for this department in the panchayat")
        
    def status_rank(status):
        if status == 'green': return 1
        if status == 'yellow': return 2
        return 3
        
    workers.sort(key=lambda w: (status_rank(w[0].profile_status), w[1]))
    
    best_worker = workers[0][0]
    
    assignment = WorkerAssignment(
        complaint_id=complaint.id,
        worker_id=best_worker.id,
        status='assigned'
    )
    db.add(assignment)
    await db.flush()
    
    sla_result = await db.execute(select(SlaConfig).where(SlaConfig.tracker_type == 'worker_assignment'))
    sla_config = sla_result.scalar_one_or_none()
    duration_hours = sla_config.duration_hours if sla_config else 24
    
    tracker = SlaTracker(
        tracker_type='worker_assignment',
        worker_assignment_id=assignment.id,
        due_at=func.now() + timedelta(hours=duration_hours)
    )
    db.add(tracker)
    
    complaint.status = 'assigned'
    
    return assignment
