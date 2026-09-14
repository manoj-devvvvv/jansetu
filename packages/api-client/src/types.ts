export const PROJECT_NAME = "JanSetu";
export const API_VERSION = "v1";
export const SUPPORTED_LOCALES = ["en", "hi", "te"];
export const JURISDICTION_LEVELS = ["panchayat", "mandal", "district"] as const;
export const DEPARTMENT_CODES = ["water", "drainage", "roads", "electricity", "hospital"] as const;

export type JurisdictionLevel = typeof JURISDICTION_LEVELS[number];
export type DepartmentCode = typeof DEPARTMENT_CODES[number];

export type ComplaintInputMode = 'voice' | 'text';
export type ComplaintSeverity = 'low' | 'medium' | 'high' | 'critical';
export type ComplaintStatus = 
  | 'submitted'
  | 'waiting'
  | 'escalated'
  | 'dismissed'
  | 'assigned'
  | 'in_progress'
  | 'pending_citizen_confirmation'
  | 'reopened'
  | 'closed';

export type VerificationActionType = 'verify' | 'dismiss' | 'wait' | 'escalate';
export type AssignmentStatus = 'assigned' | 'accepted' | 'worker_excused' | 'rejected' | 'in_progress' | 'completed';
export type WorkerStatus = 'green' | 'yellow' | 'red';
export type EscalationTriggerType = 'manual' | 'sla_breach';
export type SlaTrackerType = 'worker_assignment' | 'panchayat_verification' | 'mandal_verification' | 'district_verification';
export type AnomalyFlagType = 'impossible_travel' | 'fast_completion' | 'duplicate_photo' | 'model_flagged';
export type AnomalySeverity = 'low' | 'medium' | 'high';
export type AnomalyReviewOutcome = 'pending' | 'confirmed_fraud' | 'false_positive';
export type MasterIssueStatus = 'active' | 'fast_tracked' | 'resolved' | 'closed';
export type NotificationType = 'assignment' | 'sla_reminder' | 'citizen_verification_reminder' | 'escalation' | 'general';
export type AiProcessingStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface Department {
  id: string;
  code: string;
  name_i18n: Record<string, string>;
  icon_key: string;
  display_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Jurisdiction {
  id: string;
  level: JurisdictionLevel;
  parent_id: string | null;
  name_i18n: Record<string, string>;
  lgd_code: string | null;
  boundary: any;
  centroid: any;
  created_at: string;
  updated_at: string;
}

export interface Officer {
  id: string;
  full_name: string;
  level: JurisdictionLevel;
  jurisdiction_id: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Citizen {
  id: string;
  mobile_hash: string;
  preferred_language: string;
  total_complaints_filed: number;
  is_blocked: boolean;
  created_at: string;
  updated_at: string;
}

export interface Complaint {
  id: string;
  citizen_id: string;
  department_id: string;
  panchayat_id: string;
  mandal_id: string;
  district_id: string;
  current_review_level: JurisdictionLevel;
  location: any;
  input_mode: ComplaintInputMode;
  voice_audio_url: string | null;
  raw_text: string | null;
  formalized_text: string | null;
  detected_language: string | null;
  transcription_confidence: number | null;
  severity: ComplaintSeverity;
  image_url: string;
  submitter_ip: string;
  status: ComplaintStatus;
  wait_count: number;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  closed_at: string | null;
}

export interface ComplaintImageValidation {
  id: string;
  complaint_id: string;
  model_name: string;
  detected_labels: any[];
  confidence: number | null;
  is_valid: boolean;
  rejection_reason: string | null;
  validated_at: string;
}

export interface ComplaintProcessingStatus {
  complaint_id: string;
  transcription_status: AiProcessingStatus;
  formalization_status: AiProcessingStatus;
  image_validation_status: AiProcessingStatus;
  embedding_status: AiProcessingStatus;
  updated_at: string;
}

export interface ComplaintStatusHistory {
  id: string;
  complaint_id: string;
  old_status: ComplaintStatus | null;
  new_status: ComplaintStatus;
  changed_at: string;
}

export interface Worker {
  id: string;
  mobile_hash: string;
  full_name: string;
  department_id: string;
  jurisdiction_id: string;
  preferred_language: string;
  profile_score: number;
  profile_status: WorkerStatus;
  bulk_upload_id: string | null;
  is_active: boolean;
  created_by_officer_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkerAssignment {
  id: string;
  complaint_id: string;
  worker_id: string;
  status: AssignmentStatus;
  assigned_at: string;
  accepted_at: string | null;
  excuse_used: boolean;
  rejected_at: string | null;
  rejected_reason: string | null;
  arrival_photo_url: string | null;
  arrival_location: any | null;
  arrived_at: string | null;
  completion_photo_url: string | null;
  completion_location: any | null;
  completed_at: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkerExcuse {
  id: string;
  worker_assignment_id: string;
  reason_text: string | null;
  reason_audio_url: string | null;
  extension_hours: number;
  requested_at: string;
}

export interface WorkerScoreHistory {
  id: string;
  worker_id: string;
  change_amount: number;
  reason: string;
  related_assignment_id: string | null;
  changed_by: string | null;
  created_at: string;
}

export interface WorkerCompletionFeatures {
  id: string;
  worker_assignment_id: string;
  distance_from_previous_job_meters: number | null;
  time_since_previous_job_seconds: number | null;
  implied_travel_speed_kmph: number | null;
  completion_duration_seconds: number | null;
  is_duplicate_photo: boolean;
  anomaly_score: number | null;
  feature_vector: any;
  computed_at: string;
  model_version: string;
}

export interface AnomalyFlag {
  id: string;
  worker_id: string;
  worker_assignment_id: string;
  flag_type: AnomalyFlagType;
  severity: AnomalySeverity;
  anomaly_score: number | null;
  review_outcome: AnomalyReviewOutcome;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface SlaConfig {
  tracker_type: SlaTrackerType;
  duration_hours: number;
  description: string | null;
  updated_at: string;
}

export interface SlaTracker {
  id: string;
  tracker_type: SlaTrackerType;
  worker_assignment_id: string | null;
  complaint_id: string | null;
  started_at: string;
  due_at: string;
  breached: boolean;
  breach_processed_at: string | null;
  resolved_at: string | null;
  created_at: string;
}

export interface VerificationAction {
  id: string;
  complaint_id: string;
  officer_id: string;
  action_type: VerificationActionType;
  reason: string | null;
  created_at: string;
  review_level: JurisdictionLevel | null;
}

export interface Escalation {
  id: string;
  complaint_id: string;
  from_level: JurisdictionLevel;
  to_level: JurisdictionLevel;
  trigger_type: EscalationTriggerType;
  escalated_by: string | null;
  reason: string;
  sla_tracker_id: string | null;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface MasterIssue {
  id: string;
  department_id: string;
  jurisdiction_id: string;
  cluster_level: JurisdictionLevel;
  representative_complaint_id: string | null;
  centroid_location: any | null;
  confidence_score: number | null;
  member_count: number;
  status: MasterIssueStatus;
  is_fast_tracked: boolean;
  fast_tracked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MasterIssueMember {
  id: string;
  master_issue_id: string;
  complaint_id: string;
  similarity_score: number | null;
  joined_at: string;
  is_active: boolean;
  superseded_at: string | null;
}

export interface RecurringIssuePattern {
  id: string;
  jurisdiction_id: string;
  department_id: string;
  pattern_month: number | null;
  occurrence_years: number[];
  recurrence_count: number;
  confidence_score: number | null;
  description: string | null;
  related_master_issue_ids: string[];
  first_detected_at: string;
  last_detected_at: string;
  is_active: boolean;
}

export interface ClosureVerification {
  id: string;
  complaint_id: string;
  worker_assignment_id: string;
  reminder_count: number;
  last_reminder_sent_at: string | null;
  citizen_confirmed: boolean;
  citizen_confirmed_at: string | null;
  reopened: boolean;
  reopened_at: string | null;
  reopen_reason: string | null;
  red_flagged: boolean;
  created_at: string;
  verification_due_at: string | null;
}

export interface PushSubscription {
  id: string;
  citizen_id: string | null;
  worker_id: string | null;
  endpoint: string;
  p256dh: string;
  auth_key: string;
  user_agent: string | null;
  created_at: string;
  is_active: boolean;
  invalidated_at: string | null;
}

export interface NotificationLog {
  id: string;
  push_subscription_id: string | null;
  notification_type: NotificationType;
  related_complaint_id: string | null;
  related_worker_assignment_id: string | null;
  payload: any;
  sent_at: string;
  delivered: boolean | null;
  failure_reason: string | null;
}
