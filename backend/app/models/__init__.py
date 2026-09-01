"""Model registry.

Importing this package registers every mapper with the declarative ``Base``. Alembic's
``env.py`` and ``create_all`` both rely on that, so any new model file must be imported
here or its table will silently never be created.
"""

from app.db.base import Base
from app.models.application import (
    Application,
    ApplicationTimelineEvent,
    ScreeningAnswer,
)
from app.models.assessment import (
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    JobAssessment,
)
from app.models.ats import AtsMatch, AtsScore, AtsWeightProfile
from app.models.audit import AiDecisionLog, AuditLog
from app.models.calendar import CalendarAccount, CalendarEvent
from app.models.candidate import (
    Candidate,
    CandidateDocument,
    CandidateEducation,
    CandidateExperience,
    CandidateNote,
    CandidateSkill,
)
from app.models.communication import (
    EmailAccount,
    EmailMessage,
    EmailTemplate,
    EmailThread,
    Notification,
    NotificationDelivery,
)
from app.models.company import Company, CompanyLocation, Department
from app.models.interview import Interview, InterviewFeedback, InterviewParticipant
from app.models.job import Job, JobHiringTeamMember, JobScreeningQuestion, JobSkill
from app.models.offer import Offer, Onboarding, OnboardingTask
from app.models.resume import Resume, ResumeAnalysis
from app.models.talent import Referral, TalentPool, TalentPoolMember
from app.models.user import (
    DataRequest,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserRole,
    VerificationToken,
)
from app.models.workflow import Workflow, WorkflowExecution, WorkflowStep

__all__ = [
    "Base",
    # identity
    "User",
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "RefreshToken",
    "VerificationToken",
    "DataRequest",
    # tenancy
    "Company",
    "Department",
    "CompanyLocation",
    # jobs
    "Job",
    "JobSkill",
    "JobScreeningQuestion",
    "JobHiringTeamMember",
    # candidates
    "Candidate",
    "CandidateSkill",
    "CandidateEducation",
    "CandidateExperience",
    "CandidateDocument",
    "CandidateNote",
    # applications
    "Application",
    "ApplicationTimelineEvent",
    "ScreeningAnswer",
    # resumes & ats
    "Resume",
    "ResumeAnalysis",
    "AtsScore",
    "AtsMatch",
    "AtsWeightProfile",
    # assessments
    "Assessment",
    "AssessmentQuestion",
    "AssessmentAttempt",
    "AssessmentAnswer",
    "JobAssessment",
    # interviews
    "Interview",
    "InterviewParticipant",
    "InterviewFeedback",
    # communication
    "EmailTemplate",
    "EmailThread",
    "EmailMessage",
    "EmailAccount",
    "Notification",
    "NotificationDelivery",
    # calendar
    "CalendarAccount",
    "CalendarEvent",
    # workflow
    "Workflow",
    "WorkflowStep",
    "WorkflowExecution",
    # talent
    "TalentPool",
    "TalentPoolMember",
    "Referral",
    # offers
    "Offer",
    "Onboarding",
    "OnboardingTask",
    # audit
    "AuditLog",
    "AiDecisionLog",
]
