from enum import Enum

class JurisdictionLevel(str, Enum):
    panchayat = 'panchayat'
    mandal = 'mandal'
    district = 'district'

class ComplaintInputMode(str, Enum):
    voice = 'voice'
    text = 'text'

class ComplaintSeverity(str, Enum):
    low = 'low'
    medium = 'medium'
    high = 'high'
    critical = 'critical'

class ComplaintStatus(str, Enum):
    submitted = 'submitted'
    waiting = 'waiting'
    escalated = 'escalated'
    dismissed = 'dismissed'
    assigned = 'assigned'
    in_progress = 'in_progress'
    pending_citizen_confirmation = 'pending_citizen_confirmation'
    reopened = 'reopened'
    closed = 'closed'

class VerificationActionType(str, Enum):
    verify = 'verify'
    dismiss = 'dismiss'
    wait = 'wait'
    escalate = 'escalate'

class AssignmentStatus(str, Enum):
    assigned = 'assigned'
    accepted = 'accepted'
    worker_excused = 'worker_excused'
    rejected = 'rejected'
    in_progress = 'in_progress'
    completed = 'completed'

class WorkerStatus(str, Enum):
    green = 'green'
    yellow = 'yellow'
    red = 'red'

class EscalationTriggerType(str, Enum):
    manual = 'manual'
    sla_breach = 'sla_breach'

class SlaTrackerType(str, Enum):
    worker_assignment = 'worker_assignment'
    panchayat_verification = 'panchayat_verification'
    mandal_verification = 'mandal_verification'
    district_verification = 'district_verification'

class AnomalyFlagType(str, Enum):
    impossible_travel = 'impossible_travel'
    fast_completion = 'fast_completion'
    duplicate_photo = 'duplicate_photo'
    model_flagged = 'model_flagged'

class AnomalySeverity(str, Enum):
    low = 'low'
    medium = 'medium'
    high = 'high'

class AnomalyReviewOutcome(str, Enum):
    pending = 'pending'
    confirmed_fraud = 'confirmed_fraud'
    false_positive = 'false_positive'

class MasterIssueStatus(str, Enum):
    active = 'active'
    fast_tracked = 'fast_tracked'
    resolved = 'resolved'
    closed = 'closed'

class NotificationType(str, Enum):
    assignment = 'assignment'
    sla_reminder = 'sla_reminder'
    citizen_verification_reminder = 'citizen_verification_reminder'
    escalation = 'escalation'
    general = 'general'

class AiProcessingStatus(str, Enum):
    pending = 'pending'
    processing = 'processing'
    completed = 'completed'
    failed = 'failed'
