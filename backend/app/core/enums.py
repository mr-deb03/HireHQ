"""Central enumerations shared across HireHQ models, schemas and services.

Every enum here is persisted as a *string* in PostgreSQL (via ``SAEnum(..., native_enum=False)``)
so that adding a member never requires a database type migration, and so the same
definitions work unchanged on SQLite during local development and tests.
"""

from __future__ import annotations

from enum import StrEnum


class RoleName(StrEnum):
    """Built-in platform roles (RBAC). See ``app.core.permissions`` for the grant matrix."""

    SUPER_ADMIN = "SUPER_ADMIN"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    RECRUITER = "RECRUITER"
    HIRING_MANAGER = "HIRING_MANAGER"
    INTERVIEWER = "INTERVIEWER"
    CANDIDATE = "CANDIDATE"
    EMPLOYEE = "EMPLOYEE"


#: Roles that operate *inside* a company tenant. A user holding any of these must
#: have ``company_id`` set; tenant isolation is enforced against it.
STAFF_ROLES: frozenset[RoleName] = frozenset(
    {
        RoleName.COMPANY_ADMIN,
        RoleName.RECRUITER,
        RoleName.HIRING_MANAGER,
        RoleName.INTERVIEWER,
        RoleName.EMPLOYEE,
    }
)


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class CompanyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    TRIAL = "TRIAL"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class CompanySize(StrEnum):
    SIZE_1_10 = "1-10"
    SIZE_11_50 = "11-50"
    SIZE_51_200 = "51-200"
    SIZE_201_500 = "201-500"
    SIZE_501_1000 = "501-1000"
    SIZE_1000_PLUS = "1000+"


class JobStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class WorkMode(StrEnum):
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"


class EmploymentType(StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    INTERNSHIP = "INTERNSHIP"
    TEMPORARY = "TEMPORARY"
    FRESHER = "FRESHER"


class SkillImportance(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"


class ApplicationStatus(StrEnum):
    APPLIED = "APPLIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SCREENING = "SCREENING"
    SHORTLISTED = "SHORTLISTED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    INTERVIEW_PASSED = "INTERVIEW_PASSED"
    INTERVIEW_FAILED = "INTERVIEW_FAILED"
    OFFER = "OFFER"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_REJECTED = "OFFER_REJECTED"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    ON_HOLD = "ON_HOLD"
    WITHDRAWN = "WITHDRAWN"


#: Statuses from which no further pipeline movement is allowed.
TERMINAL_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.HIRED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.OFFER_REJECTED,
    }
)

#: Allowed pipeline transitions. Enforced by ``app.modules.applications.state_machine``.
#: Deliberately permissive *forward* movement (recruiters skip stages all the time) but
#: strict about terminal states and about not moving backwards past a decision.
APPLICATION_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.APPLIED: frozenset(
        {
            ApplicationStatus.UNDER_REVIEW,
            ApplicationStatus.SCREENING,
            ApplicationStatus.SHORTLISTED,
            ApplicationStatus.ASSESSMENT,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.UNDER_REVIEW: frozenset(
        {
            ApplicationStatus.SCREENING,
            ApplicationStatus.SHORTLISTED,
            ApplicationStatus.ASSESSMENT,
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.SCREENING: frozenset(
        {
            ApplicationStatus.SHORTLISTED,
            ApplicationStatus.ASSESSMENT,
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.SHORTLISTED: frozenset(
        {
            ApplicationStatus.ASSESSMENT,
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.ASSESSMENT: frozenset(
        {
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.SHORTLISTED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.INTERVIEW: frozenset(
        {
            ApplicationStatus.INTERVIEW_PASSED,
            ApplicationStatus.INTERVIEW_FAILED,
            ApplicationStatus.INTERVIEW,  # next round
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.INTERVIEW_PASSED: frozenset(
        {
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.INTERVIEW_FAILED: frozenset(
        {
            ApplicationStatus.REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.INTERVIEW,  # recruiter grants another round
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.OFFER: frozenset(
        {
            ApplicationStatus.OFFER_ACCEPTED,
            ApplicationStatus.OFFER_REJECTED,
            ApplicationStatus.ON_HOLD,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.REJECTED,
        }
    ),
    ApplicationStatus.OFFER_ACCEPTED: frozenset(
        {ApplicationStatus.HIRED, ApplicationStatus.WITHDRAWN}
    ),
    ApplicationStatus.OFFER_REJECTED: frozenset(),
    ApplicationStatus.ON_HOLD: frozenset(
        {
            ApplicationStatus.UNDER_REVIEW,
            ApplicationStatus.SCREENING,
            ApplicationStatus.SHORTLISTED,
            ApplicationStatus.ASSESSMENT,
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.HIRED: frozenset(),
    ApplicationStatus.REJECTED: frozenset(),
    ApplicationStatus.WITHDRAWN: frozenset(),
}


class ApplicationSource(StrEnum):
    DIRECT = "DIRECT"
    COMPANY_WEBSITE = "COMPANY_WEBSITE"
    LINKEDIN = "LINKEDIN"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"
    TWITTER = "TWITTER"
    JOB_BOARD = "JOB_BOARD"
    REFERRAL = "REFERRAL"
    INTERNAL = "INTERNAL"
    TALENT_POOL = "TALENT_POOL"
    OTHER = "OTHER"


class ResumeStatus(StrEnum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    SCANNING = "SCANNING"
    EXTRACTING = "EXTRACTING"
    PARSING = "PARSING"
    PARSED = "PARSED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class AtsRecommendation(StrEnum):
    STRONG_MATCH = "STRONG_MATCH"
    GOOD_MATCH = "GOOD_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    WEAK_MATCH = "WEAK_MATCH"


class VerificationSignal(StrEnum):
    """Objective, checkable facts about a candidate record.

    These are *signals for human review*, never automated judgements about a person.
    """

    EMAIL_VERIFIED = "EMAIL_VERIFIED"
    PHONE_VERIFIED = "PHONE_VERIFIED"
    RESUME_UPLOADED = "RESUME_UPLOADED"
    PROFILE_COMPLETE = "PROFILE_COMPLETE"
    LINKS_PROVIDED = "LINKS_PROVIDED"


class ReviewFlag(StrEnum):
    """Things a human should look at. Never used to auto-reject."""

    DUPLICATE_PROFILE_DETECTED = "DUPLICATE_PROFILE_DETECTED"
    DUPLICATE_RESUME_DETECTED = "DUPLICATE_RESUME_DETECTED"
    INCONSISTENT_EMPLOYMENT_DATES = "INCONSISTENT_EMPLOYMENT_DATES"
    EMPLOYMENT_GAP = "EMPLOYMENT_GAP"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    UNVERIFIED_PROFILE_LINKS = "UNVERIFIED_PROFILE_LINKS"
    REPEAT_APPLICATION_SAME_JOB = "REPEAT_APPLICATION_SAME_JOB"
    RESUME_PARSE_LOW_CONFIDENCE = "RESUME_PARSE_LOW_CONFIDENCE"


class ScreeningQuestionType(StrEnum):
    TEXT = "TEXT"
    YES_NO = "YES_NO"
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    NUMERIC = "NUMERIC"
    EXPERIENCE = "EXPERIENCE"
    SALARY = "SALARY"
    NOTICE_PERIOD = "NOTICE_PERIOD"


class InterviewType(StrEnum):
    PHONE = "PHONE"
    VIDEO = "VIDEO"
    IN_PERSON = "IN_PERSON"
    TECHNICAL = "TECHNICAL"
    HR = "HR"
    MANAGERIAL = "MANAGERIAL"
    CODING = "CODING"
    ASSESSMENT = "ASSESSMENT"


class InterviewStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class InterviewRecommendation(StrEnum):
    STRONG_HIRE = "STRONG_HIRE"
    HIRE = "HIRE"
    MAYBE = "MAYBE"
    NO_HIRE = "NO_HIRE"


class AssessmentQuestionType(StrEnum):
    MCQ_SINGLE = "MCQ_SINGLE"
    MCQ_MULTIPLE = "MCQ_MULTIPLE"
    CODING = "CODING"
    SQL = "SQL"
    SHORT_ANSWER = "SHORT_ANSWER"
    APTITUDE = "APTITUDE"


class AssessmentAttemptStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    EVALUATED = "EVALUATED"
    EXPIRED = "EXPIRED"


class EmailTemplateKey(StrEnum):
    APPLICATION_RECEIVED = "APPLICATION_RECEIVED"
    SHORTLISTED = "SHORTLISTED"
    SCREENING_INVITATION = "SCREENING_INVITATION"
    INTERVIEW_INVITATION = "INTERVIEW_INVITATION"
    INTERVIEW_RESCHEDULED = "INTERVIEW_RESCHEDULED"
    INTERVIEW_REMINDER = "INTERVIEW_REMINDER"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    ON_HOLD = "ON_HOLD"
    OFFER = "OFFER"
    OFFER_REMINDER = "OFFER_REMINDER"
    JOINING_REMINDER = "JOINING_REMINDER"
    ASSESSMENT_INVITATION = "ASSESSMENT_INVITATION"


class EmailDirection(StrEnum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


class EmailDeliveryStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    #: Recorded, rendered and stored, but **not** transmitted because no real provider
    #: is configured. Never reported to a user as "sent".
    NOT_SENT_NO_PROVIDER = "NOT_SENT_NO_PROVIDER"
    RECEIVED = "RECEIVED"


class EmailFolder(StrEnum):
    INCOMING = "INCOMING"
    SENT = "SENT"
    CANDIDATE_REPLIES = "CANDIDATE_REPLIES"
    INTERVIEW = "INTERVIEW"
    IMPORTANT = "IMPORTANT"
    ARCHIVED = "ARCHIVED"


class IntegrationProvider(StrEnum):
    GOOGLE = "GOOGLE"
    MICROSOFT = "MICROSOFT"
    MOCK = "MOCK"


class NotificationType(StrEnum):
    NEW_APPLICATION = "NEW_APPLICATION"
    ATS_COMPLETED = "ATS_COMPLETED"
    CANDIDATE_SHORTLISTED = "CANDIDATE_SHORTLISTED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_REMINDER = "INTERVIEW_REMINDER"
    FEEDBACK_PENDING = "FEEDBACK_PENDING"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_REJECTED = "OFFER_REJECTED"
    JOB_CLOSING = "JOB_CLOSING"
    NEW_CANDIDATE_REPLY = "NEW_CANDIDATE_REPLY"
    ASSESSMENT_SUBMITTED = "ASSESSMENT_SUBMITTED"
    WORKFLOW_ACTION = "WORKFLOW_ACTION"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"


class WorkflowTrigger(StrEnum):
    APPLICATION_CREATED = "APPLICATION_CREATED"
    ATS_SCORE_GENERATED = "ATS_SCORE_GENERATED"
    APPLICATION_STATUS_CHANGED = "APPLICATION_STATUS_CHANGED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_COMPLETED = "INTERVIEW_COMPLETED"
    FEEDBACK_SUBMITTED = "FEEDBACK_SUBMITTED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    ASSESSMENT_SUBMITTED = "ASSESSMENT_SUBMITTED"


class WorkflowActionType(StrEnum):
    CHANGE_STATUS = "CHANGE_STATUS"
    SEND_EMAIL = "SEND_EMAIL"
    NOTIFY = "NOTIFY"
    ADD_TO_TALENT_POOL = "ADD_TO_TALENT_POOL"
    ADD_TAG = "ADD_TAG"
    CREATE_TASK = "CREATE_TASK"
    ASSIGN_RECRUITER = "ASSIGN_RECRUITER"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"
    DELAY = "DELAY"


class WorkflowExecutionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class OfferStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    VIEWED = "VIEWED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class OnboardingStatus(StrEnum):
    PREBOARDING = "PREBOARDING"
    DOCUMENT_COLLECTION = "DOCUMENT_COLLECTION"
    VERIFICATION = "VERIFICATION"
    READY_TO_JOIN = "READY_TO_JOIN"
    JOINED = "JOINED"
    CANCELLED = "CANCELLED"


class ReferralStatus(StrEnum):
    REFERRED = "REFERRED"
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    HIRED = "HIRED"
    REJECTED = "REJECTED"


class DocumentType(StrEnum):
    RESUME = "RESUME"
    CERTIFICATE = "CERTIFICATE"
    ID_PROOF = "ID_PROOF"
    OFFER_LETTER = "OFFER_LETTER"
    EDUCATION_PROOF = "EDUCATION_PROOF"
    EXPERIENCE_LETTER = "EXPERIENCE_LETTER"
    PROFILE_PHOTO = "PROFILE_PHOTO"
    OTHER = "OTHER"


class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    STATUS_CHANGE = "STATUS_CHANGE"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    EXPORT = "EXPORT"
    AI_DECISION_ASSIST = "AI_DECISION_ASSIST"
    FILE_ACCESS = "FILE_ACCESS"
