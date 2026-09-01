/** Shared API types, mirroring the backend's Pydantic schemas. */

export type ApplicationStatus =
  | 'APPLIED'
  | 'UNDER_REVIEW'
  | 'SCREENING'
  | 'SHORTLISTED'
  | 'ASSESSMENT'
  | 'INTERVIEW'
  | 'INTERVIEW_PASSED'
  | 'INTERVIEW_FAILED'
  | 'OFFER'
  | 'OFFER_ACCEPTED'
  | 'OFFER_REJECTED'
  | 'HIRED'
  | 'REJECTED'
  | 'ON_HOLD'
  | 'WITHDRAWN'

export type JobStatus = 'DRAFT' | 'PUBLISHED' | 'PAUSED' | 'CLOSED' | 'ARCHIVED'
export type WorkMode = 'REMOTE' | 'HYBRID' | 'ONSITE'
export type EmploymentType =
  | 'FULL_TIME'
  | 'PART_TIME'
  | 'CONTRACT'
  | 'INTERNSHIP'
  | 'TEMPORARY'
  | 'FRESHER'
export type AtsRecommendation =
  | 'STRONG_MATCH'
  | 'GOOD_MATCH'
  | 'PARTIAL_MATCH'
  | 'WEAK_MATCH'
export type InterviewStatus =
  | 'SCHEDULED'
  | 'CONFIRMED'
  | 'RESCHEDULED'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'NO_SHOW'

export interface Role {
  id: string
  name: string
  description?: string | null
}

export interface CompanySummary {
  id: string
  name: string
  slug: string
  logo_url?: string | null
  industry?: string | null
}

export interface User {
  id: string
  email: string
  first_name: string
  last_name: string
  full_name: string
  phone?: string | null
  avatar_url?: string | null
  job_title?: string | null
  status: string
  company_id?: string | null
  company?: CompanySummary | null
  roles: Role[]
  created_at: string
}

export interface AuthenticatedUser extends User {
  permissions: string[]
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface Skill {
  id: string
  name: string
  normalised_name: string
  importance?: 'REQUIRED' | 'PREFERRED'
  weight?: number
  category?: string | null
  source: string
}

export interface ScreeningQuestion {
  id: string
  question: string
  question_type:
    | 'TEXT'
    | 'YES_NO'
    | 'SINGLE_CHOICE'
    | 'MULTIPLE_CHOICE'
    | 'NUMERIC'
    | 'EXPERIENCE'
    | 'SALARY'
    | 'NOTICE_PERIOD'
  options: string[]
  is_required: boolean
  display_order: number
  is_knockout: boolean
}

export interface JobSummary {
  id: string
  title: string
  slug: string
  reference_code: string
  status: JobStatus
  location_text?: string | null
  work_mode: WorkMode
  employment_type: EmploymentType
  min_experience_years: number
  max_experience_years?: number | null
  salary_min?: number | null
  salary_max?: number | null
  salary_currency: string
  show_salary: boolean
  openings: number
  application_count: number
  view_count: number
  is_internal_only: boolean
  application_deadline?: string | null
  published_at?: string | null
  created_at: string
}

export interface JobDetail extends JobSummary {
  description: string
  responsibilities: string[]
  benefits: string[]
  education_requirements: string[]
  certifications: string[]
  keywords: string[]
  department_id?: string | null
  hiring_manager_id?: string | null
  created_by_id?: string | null
  skills: Skill[]
  screening_questions: ScreeningQuestion[]
  hiring_team: { id: string; user_id: string; team_role: string }[]
  ai_analysis_confirmed_at?: string | null
  updated_at: string
}

export interface PublicJob {
  id: string
  title: string
  slug: string
  reference_code: string
  location_text?: string | null
  work_mode: WorkMode
  employment_type: EmploymentType
  min_experience_years: number
  max_experience_years?: number | null
  salary_min?: number | null
  salary_max?: number | null
  salary_currency: string
  openings: number
  application_deadline?: string | null
  published_at?: string | null
  company?: CompanySummary | null
  required_skills: string[]
}

export interface PublicJobDetail extends PublicJob {
  description: string
  responsibilities: string[]
  benefits: string[]
  education_requirements: string[]
  certifications: string[]
  preferred_skills: string[]
  screening_questions: ScreeningQuestion[]
  already_applied: boolean
  existing_application_id?: string | null
}

export interface ExtractedSkill {
  name: string
  importance: string
  category: string
  min_years?: number | null
}

export interface JobAnalysis {
  required_skills: ExtractedSkill[]
  preferred_skills: ExtractedSkill[]
  min_experience_years: number
  max_experience_years?: number | null
  education_requirements: string[]
  certifications: string[]
  responsibilities: string[]
  keywords: string[]
  technical_skills: string[]
  soft_skills: string[]
  seniority?: string | null
  confidence: number
  engine: string
  requires_review: boolean
}

export interface CandidateSummary {
  id: string
  first_name: string
  last_name: string
  full_name: string
  email: string
  phone?: string | null
  location?: string | null
  photo_url?: string | null
  headline?: string | null
  current_designation?: string | null
  current_company?: string | null
  total_experience_years: number
  notice_period_days?: number | null
  expected_salary?: number | null
  salary_currency: string
  email_verified: boolean
  phone_verified: boolean
  tags: string[]
  source?: string | null
  is_internal_employee: boolean
  created_at: string
  skills: Skill[]
}

export interface ReviewFlag {
  code: string
  message: string
  raised_at?: string | null
  resolved: boolean
  resolved_at?: string | null
}

export interface CandidateDetail extends CandidateSummary {
  summary?: string | null
  ai_summary?: string | null
  ai_summary_generated_at?: string | null
  linkedin_url?: string | null
  github_url?: string | null
  portfolio_url?: string | null
  verification_signals: string[]
  review_flags: ReviewFlag[]
  education: {
    id: string
    degree: string
    degree_level?: string | null
    institution?: string | null
    end_year?: number | null
    grade?: string | null
  }[]
  experience: {
    id: string
    company_name: string
    position: string
    start_date?: string | null
    end_date?: string | null
    is_current: boolean
    responsibilities: string[]
    technologies: string[]
  }[]
  updated_at: string
}

export interface ApplicationSummary {
  id: string
  reference_code: string
  status: ApplicationStatus
  source: string
  source_detail?: string | null
  ats_score?: number | null
  ats_rank?: number | null
  screening_score?: number | null
  stage_position: number
  tags: string[]
  assigned_recruiter_id?: string | null
  created_at: string
  status_changed_at?: string | null
  job?: { id: string; title: string; reference_code: string; location_text?: string | null } | null
  candidate?: {
    id: string
    full_name: string
    email: string
    phone?: string | null
    location?: string | null
    photo_url?: string | null
    current_designation?: string | null
    current_company?: string | null
    total_experience_years: number
    notice_period_days?: number | null
    email_verified: boolean
  } | null
}

export interface ApplicationDetail extends ApplicationSummary {
  cover_letter?: string | null
  expected_salary?: number | null
  notice_period_days?: number | null
  rejection_reason?: string | null
  resume_id?: string | null
  shortlisted_at?: string | null
  interviewed_at?: string | null
  offered_at?: string | null
  hired_at?: string | null
  last_automated_action_at?: string | null
  screening_answers: {
    id: string
    question_snapshot: string
    answer_text?: string | null
    answer_number?: number | null
    answer_boolean?: boolean | null
    answer_options: string[]
    points_awarded?: number | null
    points_possible?: number | null
    knockout_triggered: boolean
  }[]
  allowed_transitions: string[]
  updated_at: string
}

export interface AtsComponent {
  score: number
  weight: number
  contribution: number
  explanation: string
  details: Record<string, unknown>
}

export interface AtsScore {
  id: string
  application_id: string
  job_id: string
  candidate_id: string
  overall_score: number
  skills_score: number
  experience_score: number
  education_score: number
  responsibilities_score: number
  semantic_score: number
  recommendation: AtsRecommendation
  weights_used: Record<string, number>
  explanation: {
    summary: string
    components: Record<string, AtsComponent>
    matched_skills: string[]
    missing_skills: string[]
    notes: string[]
  }
  matched_skills: string[]
  missing_skills: string[]
  engine_version: string
  semantic_engine: string
  created_at: string
  disclaimer: string
}

export interface KanbanCard {
  id: string
  reference_code: string
  candidate_id: string
  candidate_name: string
  candidate_photo_url?: string | null
  current_designation?: string | null
  ats_score?: number | null
  ats_rank?: number | null
  total_experience_years: number
  notice_period_days?: number | null
  tags: string[]
  stage_position: number
  has_pending_feedback: boolean
  applied_at: string
}

export interface KanbanColumn {
  status: ApplicationStatus
  label: string
  count: number
  cards: KanbanCard[]
}

export interface KanbanBoard {
  job_id?: string | null
  columns: KanbanColumn[]
  total: number
}

export interface TimelineEvent {
  id: string
  event_type: string
  title: string
  description?: string | null
  previous_status?: ApplicationStatus | null
  new_status?: ApplicationStatus | null
  actor_type: string
  is_visible_to_candidate: boolean
  meta: Record<string, unknown>
  created_at: string
}

export interface DashboardKpis {
  active_jobs: number
  total_applications: number
  new_applications_this_week: number
  shortlisted: number
  pending_review: number
  strong_matches_awaiting_review: number
  interviews_today: number
  upcoming_interviews: number
  pending_feedback: number
  offers_awaiting_response: number
  hired: number
}

export interface DashboardData {
  greeting: string
  kpis: DashboardKpis
  attention_required: {
    key: string
    count: number
    label: string
    url: string
    priority: string
  }[]
  funnel: { stage: string; label: string; count: number; conversion_from_previous_pct?: number | null }[]
  todays_interviews: {
    id: string
    time: string
    scheduled_start: string
    title: string
    interview_type: string
    candidate_name?: string | null
    candidate_id: string
    meeting_link?: string | null
  }[]
}

export interface Interview {
  id: string
  title: string
  round_number: number
  round_name?: string | null
  interview_type: string
  status: InterviewStatus
  scheduled_start: string
  scheduled_end: string
  duration_minutes: number
  timezone: string
  meeting_link?: string | null
  location?: string | null
  application_id: string
  job_id: string
  candidate_id: string
  candidate_name?: string | null
  job_title?: string | null
  participants: { id: string; user_id?: string | null; role: string }[]
  feedback_count: number
  created_at: string
  calendar_sync?: {
    status: string
    provider?: string | null
    detail?: string | null
  } | null
}

export interface Notification {
  id: string
  notification_type: string
  title: string
  body?: string | null
  action_url?: string | null
  is_read: boolean
  priority: string
  created_at: string
}

export interface AiStatus {
  provider: string
  is_language_model: boolean
  model?: string | null
  capabilities: Record<string, boolean>
  message: string
}

export interface AssistantAnswer {
  answer: string
  engine: string
  is_language_model: boolean
  tool_calls: { name: string; arguments: Record<string, unknown> }[]
  data?: Record<string, unknown> | null
  suggestions: string[]
  disclaimer: string
}

export interface MyApplication {
  id: string
  reference_code: string
  status_label: string
  job_title: string
  company_name?: string | null
  location?: string | null
  applied_at: string
  last_updated: string
  can_withdraw: boolean
}

export interface MyApplicationDetail extends MyApplication {
  cover_letter?: string | null
  /** Only events marked visible to the candidate; internal notes never appear here. */
  timeline: { title: string; description?: string | null; at: string }[]
  upcoming_interviews: Record<string, unknown>[]
  pending_assessments: Record<string, unknown>[]
  offer?: Record<string, unknown> | null
}

// ------------------------------------------------------------------ interviews
export type InterviewType =
  | 'PHONE'
  | 'VIDEO'
  | 'IN_PERSON'
  | 'TECHNICAL'
  | 'HR'
  | 'MANAGERIAL'
  | 'CODING'
  | 'ASSESSMENT'

export type InterviewRecommendation = 'STRONG_HIRE' | 'HIRE' | 'MAYBE' | 'NO_HIRE'

export interface UserRef {
  id: string
  full_name: string
  email?: string | null
  avatar_url?: string | null
}

export interface InterviewParticipant {
  id: string
  user_id?: string | null
  role: string
  is_required: boolean
  response_status: string
  user?: UserRef | null
}

export interface CalendarSync {
  /** SYNCED | PENDING_NO_PROVIDER | FAILED. */
  status: string
  provider?: string | null
  external_event_id?: string | null
  detail?: string | null
}

export interface InterviewSummary {
  id: string
  title: string
  round_number: number
  round_name?: string | null
  interview_type: InterviewType
  status: InterviewStatus
  scheduled_start: string
  scheduled_end: string
  duration_minutes: number
  timezone: string
  meeting_link?: string | null
  location?: string | null
  application_id: string
  job_id: string
  candidate_id: string
  candidate_name?: string | null
  job_title?: string | null
  organiser_id?: string | null
  participants: InterviewParticipant[]
  feedback_count: number
  created_at: string
}

export interface InterviewDetail extends InterviewSummary {
  candidate_instructions?: string | null
  /** Never shown to the candidate. */
  internal_notes?: string | null
  rescheduled_from?: string | null
  reschedule_count: number
  cancelled_at?: string | null
  cancellation_reason?: string | null
  completed_at?: string | null
  candidate_confirmed_at?: string | null
  calendar_sync?: CalendarSync | null
  updated_at: string
}

export interface InterviewFeedback {
  id: string
  interview_id: string
  application_id: string
  interviewer_id: string
  interviewer?: UserRef | null
  overall_rating: number
  recommendation: InterviewRecommendation
  technical_skills?: number | null
  communication?: number | null
  problem_solving?: number | null
  domain_knowledge?: number | null
  culture_fit?: number | null
  average_competency?: number | null
  strengths?: string | null
  weaknesses?: string | null
  comments?: string | null
  /**
   * Omitted by the server unless the reader holds `feedback:read:private`, so a missing
   * value here means "not visible to you", never "none written".
   */
  private_remarks?: string | null
  ai_summary?: string | null
  ai_summary_engine?: string | null
  is_draft: boolean
  submitted_at?: string | null
  created_at: string
}

// ---------------------------------------------------------------------- offers
export type OfferStatus =
  | 'DRAFT'
  | 'SENT'
  | 'VIEWED'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'WITHDRAWN'
  | 'EXPIRED'

export interface Offer {
  id: string
  reference_code: string
  application_id: string
  candidate_id: string
  job_id: string
  position_title: string
  department?: string | null
  location?: string | null
  employment_type?: string | null
  base_salary: number
  variable_pay?: number | null
  joining_bonus?: number | null
  total_compensation: number
  currency: string
  salary_period: string
  benefits: string[]
  joining_date?: string | null
  probation_months?: number | null
  reporting_to?: string | null
  notes?: string | null
  status: OfferStatus
  expires_at?: string | null
  sent_at?: string | null
  viewed_at?: string | null
  responded_at?: string | null
  decline_reason?: string | null
  approved_at?: string | null
  created_at: string
}

/** The candidate-facing view of an offer, reached with a one-time link. */
export interface PublicOffer {
  reference_code: string
  company_name?: string | null
  company_logo_url?: string | null
  position_title: string
  department?: string | null
  location?: string | null
  employment_type?: string | null
  base_salary: number
  variable_pay?: number | null
  joining_bonus?: number | null
  total_compensation: number
  currency: string
  salary_period: string
  benefits: string[]
  joining_date?: string | null
  probation_months?: number | null
  reporting_to?: string | null
  notes?: string | null
  status: OfferStatus
  expires_at?: string | null
  can_respond: boolean
}

// ----------------------------------------------------------------- assessments
export type AssessmentQuestionType =
  | 'MCQ_SINGLE'
  | 'MCQ_MULTIPLE'
  | 'CODING'
  | 'SQL'
  | 'SHORT_ANSWER'
  | 'APTITUDE'

export type AssessmentAttemptStatus =
  | 'NOT_STARTED'
  | 'IN_PROGRESS'
  | 'SUBMITTED'
  | 'EVALUATED'
  | 'EXPIRED'

export interface AssessmentQuestion {
  id: string
  question_type: AssessmentQuestionType
  prompt: string
  points: number
  difficulty: string
  display_order: number
  options: { id: string; text: string }[]
  allowed_languages: string[]
}

export interface Assessment {
  id: string
  title: string
  description?: string | null
  category: string
  duration_minutes: number
  passing_score: number
  max_attempts: number
  randomise_questions: boolean
  is_active: boolean
  total_points: number
  questions: AssessmentQuestion[]
  created_at: string
}

export interface AssessmentAttempt {
  id: string
  assessment_id: string
  application_id: string
  candidate_id: string
  attempt_number: number
  status: AssessmentAttemptStatus
  invited_at?: string | null
  started_at?: string | null
  submitted_at?: string | null
  expires_at?: string | null
  time_spent_seconds?: number | null
  score?: number | null
  max_score?: number | null
  /** Percentage of the *auto-gradable* portion; read alongside pending_manual_review. */
  percentage?: number | null
  /** Null while any answer still awaits a human — never a guessed pass/fail. */
  passed?: boolean | null
  pending_manual_review: string[]
  created_at: string
}

/** What a candidate sees when taking an assessment. Answer keys are stripped server-side. */
export interface CandidateAssessment {
  attempt_id: string
  status: AssessmentAttemptStatus
  started_at?: string | null
  expires_at?: string | null
  assessment: {
    id: string
    title: string
    description?: string | null
    duration_minutes: number
    total_points: number
    questions: {
      id: string
      question_type: AssessmentQuestionType
      prompt: string
      points: number
      options: { id: string; text: string }[]
      starter_code?: string | null
      allowed_languages: string[]
      /** Visible examples only; hidden cases never leave the server. */
      example_test_cases: { input?: string | null; expected_output?: string | null }[]
    }[]
  }
}

export interface AssessmentAnswerInput {
  question_id: string
  selected_options?: string[]
  answer_text?: string | null
  code_submission?: string | null
  language?: string | null
  time_spent_seconds?: number | null
}

// ------------------------------------------------------------------- workflows
export type WorkflowTrigger =
  | 'APPLICATION_CREATED'
  | 'ATS_SCORE_GENERATED'
  | 'APPLICATION_STATUS_CHANGED'
  | 'INTERVIEW_SCHEDULED'
  | 'INTERVIEW_COMPLETED'
  | 'FEEDBACK_SUBMITTED'
  | 'OFFER_ACCEPTED'
  | 'ASSESSMENT_SUBMITTED'

export type WorkflowActionType =
  | 'CHANGE_STATUS'
  | 'SEND_EMAIL'
  | 'NOTIFY'
  | 'ADD_TO_TALENT_POOL'
  | 'ADD_TAG'
  | 'CREATE_TASK'
  | 'ASSIGN_RECRUITER'
  | 'FLAG_FOR_REVIEW'
  | 'DELAY'

export type WorkflowExecutionStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'SKIPPED'

export interface WorkflowStep {
  id: string
  step_order: number
  action_type: WorkflowActionType
  config: Record<string, unknown>
  conditions: Record<string, unknown>
  delay_minutes: number
  continue_on_error: boolean
  is_enabled: boolean
}

export interface Workflow {
  id: string
  name: string
  description?: string | null
  trigger: WorkflowTrigger
  conditions: Record<string, unknown>
  job_ids: string[]
  is_enabled: boolean
  /** Required before a workflow may move an application to a human-only status. */
  requires_human_approval: boolean
  priority: number
  execution_count: number
  last_executed_at?: string | null
  steps: WorkflowStep[]
  created_at: string
  updated_at: string
}

export interface WorkflowExecution {
  id: string
  workflow_id: string
  workflow_name?: string | null
  entity_type: string
  entity_id: string
  status: WorkflowExecutionStatus
  /** Why a run did nothing, in the condition grammar's own words. */
  skip_reason?: string | null
  trigger_context: Record<string, unknown>
  step_results: Record<string, unknown>[]
  awaiting_approval: boolean
  approved_by_id?: string | null
  approved_at?: string | null
  started_at?: string | null
  completed_at?: string | null
  error?: string | null
  created_at: string
}

export interface WorkflowFieldSpec {
  key: string
  label: string
  type: string
  description?: string | null
  options: string[]
  operators: string[]
}

export interface WorkflowSchema {
  triggers: { value: WorkflowTrigger; label: string }[]
  actions: { value: WorkflowActionType; label: string }[]
  fields: WorkflowFieldSpec[]
  group_operators: string[]
  governance: { human_only_statuses: string[]; note: string }
}

// ----------------------------------------------------------------------- email
export type EmailDeliveryStatus =
  | 'QUEUED'
  | 'SENT'
  | 'FAILED'
  /** No email provider is configured. The message was recorded, not transmitted. */
  | 'NOT_SENT_NO_PROVIDER'
  | 'RECEIVED'

export type EmailFolder =
  | 'INCOMING'
  | 'SENT'
  | 'CANDIDATE_REPLIES'
  | 'INTERVIEW'
  | 'IMPORTANT'
  | 'ARCHIVED'

export interface EmailMessage {
  id: string
  thread_id?: string | null
  application_id?: string | null
  candidate_id?: string | null
  direction: 'OUTBOUND' | 'INBOUND'
  from_address: string
  from_name?: string | null
  to_addresses: string[]
  cc_addresses: string[]
  subject: string
  body_html?: string | null
  body_text?: string | null
  delivery_status: EmailDeliveryStatus
  transport?: string | null
  sent_at?: string | null
  failure_reason?: string | null
  is_automated: boolean
  created_at: string
}

export interface EmailThread {
  id: string
  subject: string
  candidate_id?: string | null
  application_id?: string | null
  job_id?: string | null
  folder: EmailFolder
  is_read: boolean
  is_important: boolean
  is_archived: boolean
  message_count: number
  last_message_at?: string | null
  created_at: string
}

export interface EmailAccount {
  id: string
  provider: string
  email_address: string
  display_name?: string | null
  is_active: boolean
  last_synced_at?: string | null
  sync_error?: string | null
}

export interface EmailProviderStatus {
  provider: string
  transmits: boolean
  message: string
}

// -------------------------------------------------------------------- calendar
export interface CalendarAccount {
  id: string
  provider: string
  account_email: string
  is_active: boolean
  last_synced_at?: string | null
  sync_error?: string | null
}

export interface CalendarEvent {
  id: string
  title: string
  description?: string | null
  location?: string | null
  meeting_link?: string | null
  start_at: string
  end_at: string
  timezone: string
  all_day: boolean
  status: string
  sync_status: string
  provider?: string | null
  interview_id?: string | null
  attendees: Record<string, unknown>[]
}

export interface CalendarView {
  view: string
  start: string
  end: string
  events: CalendarEvent[]
  total: number
  provider_status: string
}

// ----------------------------------------------------------------- talent pool
export interface TalentPool {
  id: string
  name: string
  description?: string | null
  criteria: Record<string, unknown>
  is_dynamic: boolean
  colour?: string | null
  member_count: number
  created_at: string
}

// -------------------------------------------------------------------- ranking
export interface RankedCandidate {
  rank: number
  application_id: string
  candidate_id: string
  candidate_name: string
  current_designation?: string | null
  total_experience_years: number
  ats_score: number
  recommendation?: AtsRecommendation | null
  status: ApplicationStatus
  matched_skills: string[]
  missing_skills: string[]
}

export interface JobStats {
  job_id: string
  total_applications: number
  by_status: Record<string, number>
  funnel: Record<string, number>
  average_ats_score?: number | null
  top_sources: Record<string, number>
  interviews_scheduled: number
  offers_extended: number
}

// ------------------------------------------------------------------- analytics
export interface FunnelStage {
  stage: string
  label: string
  count: number
  conversion_from_previous_pct?: number | null
}

export interface FunnelReport {
  stages: FunnelStage[]
  total_applications: number
  total_hired: number
  overall_conversion_pct: number
  by_status: Record<string, number>
}

export interface SourceReport {
  source: string
  label: string
  applications: number
  shortlisted: number
  interviewed: number
  offers: number
  hired: number
  average_ats_score?: number | null
  hire_rate_pct: number
}

export interface TimeToHireReport {
  hires_measured: number
  average_days_to_hire?: number | null
  median_days_to_hire?: number | null
  fastest_days?: number
  slowest_days?: number
  stage_durations_days: Record<string, number>
  /** Present only when there is nothing to measure, explaining the empty report. */
  note?: string
}

export interface JobPerformanceRow {
  job_id: string
  title: string
  reference_code: string
  status: JobStatus
  applications: number
  shortlisted: number
  interviewed: number
  hired: number
  average_ats_score?: number | null
  interview_conversion_pct: number
}

export interface JobPerformanceReport {
  highest_volume: JobPerformanceRow[]
  lowest_volume: JobPerformanceRow[]
  best_interview_conversion: JobPerformanceRow[]
}

export interface AtsBand {
  band: string
  min: number
  max: number
  count: number
}

export interface DropOffRow {
  status: ApplicationStatus
  label: string
  count: number
}

export interface RecruiterRow {
  recruiter_id: string
  name: string
  applications_assigned: number
  shortlisted: number
  hired: number
}

export interface VolumePoint {
  date: string
  applications: number
}

// ----------------------------------------------------------------------- admin
export type CompanyStatus = 'ACTIVE' | 'TRIAL' | 'SUSPENDED' | 'ARCHIVED'
export type UserStatus = 'PENDING_VERIFICATION' | 'ACTIVE' | 'INACTIVE' | 'SUSPENDED'

export interface AdminCompany {
  id: string
  name: string
  slug: string
  industry?: string | null
  size?: string | null
  status: CompanyStatus
  subscription_plan: string
  created_at: string
  user_count: number
  job_count: number
  application_count: number
}

export interface PlatformStats {
  companies: Record<string, number>
  users: Record<string, number>
  jobs: Record<string, number>
  applications: Record<string, number>
  candidates: number
  /** Which integrations are genuinely configured, straight from the provider layer. */
  providers: Record<string, Record<string, unknown>>
}

export interface AuditLog {
  id: string
  company_id?: string | null
  actor_id?: string | null
  actor_email?: string | null
  actor_roles: string[]
  action: string
  entity_type: string
  entity_id?: string | null
  summary: string
  changes: Record<string, unknown>
  meta: Record<string, unknown>
  ip_address?: string | null
  request_id?: string | null
  created_at: string
}

export interface UserProfile {
  id: string
  email: string
  first_name: string
  last_name: string
  full_name: string
  phone?: string | null
  avatar_url?: string | null
  job_title?: string | null
  timezone: string
  locale: string
  status: UserStatus
  email_verified_at?: string | null
  last_login_at?: string | null
  company_id?: string | null
  company?: CompanySummary | null
  roles: Role[]
  created_at: string
}

export interface AssignableRole {
  name: string
  description: string
  grantable: boolean
}

/**
 * The cross-tenant user listing shown to super admins. Deliberately narrower than
 * `UserProfile`: it carries identity and access state only, never anything belonging to
 * the company the user works for.
 */
export interface AdminUser {
  id: string
  email: string
  full_name: string
  status: UserStatus
  /** Role names, not objects — this endpoint returns the flat list. */
  roles: string[]
  company?: string | null
  company_id?: string | null
  last_login_at?: string | null
  created_at: string
}

// ------------------------------------------------------------ public tracking
export interface TrackedApplication {
  reference_code: string
  /** A candidate-safe label; internal statuses like INTERVIEW_FAILED are never exposed. */
  status: string
  job_title?: string | null
  company_name?: string | null
  applied_at: string
  last_updated?: string | null
  timeline: { title: string; at: string; description?: string | null }[]
}

// ------------------------------------------------------------------ onboarding
export type OnboardingStatus =
  | 'PREBOARDING'
  | 'DOCUMENT_COLLECTION'
  | 'VERIFICATION'
  | 'READY_TO_JOIN'
  | 'JOINED'
  | 'CANCELLED'

export interface OnboardingTask {
  id: string
  title: string
  description?: string | null
  category: string
  is_completed: boolean
  due_date?: string | null
  assigned_to_id?: string | null
  completed_at?: string | null
}

export interface Onboarding {
  id: string
  offer_id: string
  candidate_id: string
  application_id: string
  status: OnboardingStatus
  expected_joining_date?: string | null
  actual_joining_date?: string | null
  owner_id?: string | null
  buddy_user_id?: string | null
  employee_user_id?: string | null
  notes?: string | null
  completion_percentage: number
  tasks: OnboardingTask[]
  created_at: string
  updated_at: string
}
