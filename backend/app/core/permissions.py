"""Permission catalogue and the role -> permission grant matrix.

Permissions are strings of the form ``<resource>:<action>``. Roles are persisted in the
database (so a Super Admin can add custom roles at runtime) but this module is the
authoritative *default* matrix used to seed and to reconcile the built-in roles.

A single place defines who can do what, which is what makes ``require_permission``
dependencies and the AI assistant's tool gating agree with each other.
"""

from __future__ import annotations

from app.core.enums import RoleName


class Perm:
    """Permission constants. Grouped by resource for readability."""

    # platform
    PLATFORM_MANAGE = "platform:manage"
    PLATFORM_ANALYTICS_READ = "platform:analytics:read"
    AUDIT_READ = "audit:read"
    AI_CONFIG_MANAGE = "ai:config:manage"

    # companies
    COMPANY_CREATE = "company:create"
    COMPANY_READ = "company:read"
    COMPANY_UPDATE = "company:update"
    COMPANY_DELETE = "company:delete"
    DEPARTMENT_MANAGE = "department:manage"

    # users
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    ROLE_MANAGE = "role:manage"

    # jobs
    JOB_CREATE = "job:create"
    JOB_READ = "job:read"
    JOB_UPDATE = "job:update"
    JOB_DELETE = "job:delete"
    JOB_PUBLISH = "job:publish"
    JOB_READ_ASSIGNED = "job:read:assigned"

    # candidates
    CANDIDATE_READ = "candidate:read"
    CANDIDATE_UPDATE = "candidate:update"
    CANDIDATE_DELETE = "candidate:delete"
    CANDIDATE_NOTE_WRITE = "candidate:note:write"
    CANDIDATE_DOCUMENT_READ = "candidate:document:read"

    # applications
    APPLICATION_CREATE = "application:create"
    APPLICATION_READ = "application:read"
    APPLICATION_READ_OWN = "application:read:own"
    APPLICATION_UPDATE_STATUS = "application:update:status"
    APPLICATION_BULK_ACTION = "application:bulk"
    APPLICATION_WITHDRAW_OWN = "application:withdraw:own"

    # ats
    ATS_READ = "ats:read"
    ATS_RUN = "ats:run"
    ATS_CONFIG_MANAGE = "ats:config:manage"

    # screening & assessments
    SCREENING_MANAGE = "screening:manage"
    ASSESSMENT_MANAGE = "assessment:manage"
    ASSESSMENT_TAKE = "assessment:take"
    ASSESSMENT_RESULT_READ = "assessment:result:read"

    # interviews
    INTERVIEW_CREATE = "interview:create"
    INTERVIEW_READ = "interview:read"
    INTERVIEW_READ_ASSIGNED = "interview:read:assigned"
    INTERVIEW_UPDATE = "interview:update"
    INTERVIEW_CANCEL = "interview:cancel"
    FEEDBACK_SUBMIT = "feedback:submit"
    FEEDBACK_READ = "feedback:read"
    FEEDBACK_READ_PRIVATE = "feedback:read:private"

    # emails
    EMAIL_SEND = "email:send"
    EMAIL_READ = "email:read"
    EMAIL_TEMPLATE_MANAGE = "email:template:manage"
    EMAIL_ACCOUNT_CONNECT = "email:account:connect"

    # calendar
    CALENDAR_READ = "calendar:read"
    CALENDAR_MANAGE = "calendar:manage"

    # talent pool / referrals
    TALENT_POOL_MANAGE = "talent_pool:manage"
    TALENT_POOL_READ = "talent_pool:read"
    REFERRAL_CREATE = "referral:create"
    REFERRAL_READ = "referral:read"
    REFERRAL_READ_OWN = "referral:read:own"

    # offers & onboarding
    OFFER_CREATE = "offer:create"
    OFFER_READ = "offer:read"
    OFFER_READ_OWN = "offer:read:own"
    OFFER_RESPOND_OWN = "offer:respond:own"
    OFFER_APPROVE = "offer:approve"
    ONBOARDING_MANAGE = "onboarding:manage"
    ONBOARDING_READ_OWN = "onboarding:read:own"

    # analytics & workflows
    ANALYTICS_READ = "analytics:read"
    WORKFLOW_MANAGE = "workflow:manage"
    WORKFLOW_READ = "workflow:read"

    # ai
    AI_ASSISTANT_USE = "ai:assistant:use"
    AI_GENERATE = "ai:generate"

    # notifications & profile (everyone)
    NOTIFICATION_READ_OWN = "notification:read:own"
    PROFILE_MANAGE_OWN = "profile:manage:own"


#: Permissions every authenticated user holds regardless of role.
BASE_PERMISSIONS: frozenset[str] = frozenset(
    {Perm.NOTIFICATION_READ_OWN, Perm.PROFILE_MANAGE_OWN}
)

_RECRUITER_PERMISSIONS: frozenset[str] = frozenset(
    {
        Perm.COMPANY_READ,
        Perm.JOB_CREATE,
        Perm.JOB_READ,
        Perm.JOB_UPDATE,
        Perm.JOB_PUBLISH,
        Perm.CANDIDATE_READ,
        Perm.CANDIDATE_UPDATE,
        Perm.CANDIDATE_NOTE_WRITE,
        Perm.CANDIDATE_DOCUMENT_READ,
        Perm.APPLICATION_READ,
        Perm.APPLICATION_UPDATE_STATUS,
        Perm.APPLICATION_BULK_ACTION,
        Perm.ATS_READ,
        Perm.ATS_RUN,
        Perm.ATS_CONFIG_MANAGE,
        Perm.SCREENING_MANAGE,
        Perm.ASSESSMENT_MANAGE,
        Perm.ASSESSMENT_RESULT_READ,
        Perm.INTERVIEW_CREATE,
        Perm.INTERVIEW_READ,
        Perm.INTERVIEW_UPDATE,
        Perm.INTERVIEW_CANCEL,
        Perm.FEEDBACK_READ,
        Perm.EMAIL_SEND,
        Perm.EMAIL_READ,
        Perm.EMAIL_TEMPLATE_MANAGE,
        Perm.EMAIL_ACCOUNT_CONNECT,
        Perm.CALENDAR_READ,
        Perm.CALENDAR_MANAGE,
        Perm.TALENT_POOL_MANAGE,
        Perm.TALENT_POOL_READ,
        Perm.REFERRAL_READ,
        Perm.OFFER_CREATE,
        Perm.OFFER_READ,
        Perm.ONBOARDING_MANAGE,
        Perm.ANALYTICS_READ,
        Perm.WORKFLOW_MANAGE,
        Perm.WORKFLOW_READ,
        Perm.AI_ASSISTANT_USE,
        Perm.AI_GENERATE,
        Perm.USER_READ,
    }
)

_COMPANY_ADMIN_PERMISSIONS: frozenset[str] = _RECRUITER_PERMISSIONS | {
    Perm.COMPANY_UPDATE,
    Perm.DEPARTMENT_MANAGE,
    Perm.USER_CREATE,
    Perm.USER_UPDATE,
    Perm.USER_DELETE,
    Perm.ROLE_MANAGE,
    Perm.JOB_DELETE,
    Perm.CANDIDATE_DELETE,
    Perm.OFFER_APPROVE,
    Perm.FEEDBACK_READ_PRIVATE,
    Perm.AUDIT_READ,
}

_HIRING_MANAGER_PERMISSIONS: frozenset[str] = frozenset(
    {
        Perm.COMPANY_READ,
        Perm.JOB_READ_ASSIGNED,
        Perm.JOB_READ,
        Perm.CANDIDATE_READ,
        Perm.CANDIDATE_NOTE_WRITE,
        Perm.CANDIDATE_DOCUMENT_READ,
        Perm.APPLICATION_READ,
        Perm.APPLICATION_UPDATE_STATUS,
        Perm.ATS_READ,
        Perm.ASSESSMENT_RESULT_READ,
        Perm.INTERVIEW_READ,
        Perm.INTERVIEW_CREATE,
        Perm.FEEDBACK_SUBMIT,
        Perm.FEEDBACK_READ,
        Perm.FEEDBACK_READ_PRIVATE,
        Perm.CALENDAR_READ,
        Perm.ANALYTICS_READ,
        Perm.OFFER_READ,
        Perm.OFFER_APPROVE,
        Perm.TALENT_POOL_READ,
        Perm.AI_ASSISTANT_USE,
    }
)

_INTERVIEWER_PERMISSIONS: frozenset[str] = frozenset(
    {
        Perm.INTERVIEW_READ_ASSIGNED,
        Perm.CANDIDATE_READ,
        Perm.CANDIDATE_DOCUMENT_READ,
        Perm.FEEDBACK_SUBMIT,
        Perm.FEEDBACK_READ,
        Perm.CALENDAR_READ,
        Perm.JOB_READ_ASSIGNED,
    }
)

_CANDIDATE_PERMISSIONS: frozenset[str] = frozenset(
    {
        Perm.APPLICATION_CREATE,
        Perm.APPLICATION_READ_OWN,
        Perm.APPLICATION_WITHDRAW_OWN,
        Perm.ASSESSMENT_TAKE,
        Perm.OFFER_READ_OWN,
        Perm.OFFER_RESPOND_OWN,
        Perm.ONBOARDING_READ_OWN,
        Perm.INTERVIEW_READ_ASSIGNED,
    }
)

_EMPLOYEE_PERMISSIONS: frozenset[str] = _CANDIDATE_PERMISSIONS | {
    Perm.REFERRAL_CREATE,
    Perm.REFERRAL_READ_OWN,
    Perm.JOB_READ,
}

#: The full catalogue, derived so it can never drift from what is actually granted.
ALL_PERMISSIONS: frozenset[str] = frozenset(
    value
    for name, value in vars(Perm).items()
    if not name.startswith("_") and isinstance(value, str)
)

ROLE_PERMISSIONS: dict[RoleName, frozenset[str]] = {
    RoleName.SUPER_ADMIN: ALL_PERMISSIONS,
    RoleName.COMPANY_ADMIN: _COMPANY_ADMIN_PERMISSIONS | BASE_PERMISSIONS,
    RoleName.RECRUITER: _RECRUITER_PERMISSIONS | BASE_PERMISSIONS,
    RoleName.HIRING_MANAGER: _HIRING_MANAGER_PERMISSIONS | BASE_PERMISSIONS,
    RoleName.INTERVIEWER: _INTERVIEWER_PERMISSIONS | BASE_PERMISSIONS,
    RoleName.CANDIDATE: _CANDIDATE_PERMISSIONS | BASE_PERMISSIONS,
    RoleName.EMPLOYEE: _EMPLOYEE_PERMISSIONS | BASE_PERMISSIONS,
}

ROLE_DESCRIPTIONS: dict[RoleName, str] = {
    RoleName.SUPER_ADMIN: "Platform owner. Manages companies, users, subscriptions and system configuration.",
    RoleName.COMPANY_ADMIN: "Owns a company tenant: its hiring team, departments, jobs and workflows.",
    RoleName.RECRUITER: "Runs day-to-day recruitment: jobs, candidates, pipeline, interviews and offers.",
    RoleName.HIRING_MANAGER: "Reviews candidates for their own jobs, interviews and approves hires.",
    RoleName.INTERVIEWER: "Conducts assigned interviews and submits evaluations.",
    RoleName.CANDIDATE: "Applies for jobs and tracks their own applications, interviews and offers.",
    RoleName.EMPLOYEE: "Internal employee: applies to internal openings and refers candidates.",
}


def permissions_for_roles(roles: list[str] | set[str]) -> frozenset[str]:
    """Union the grants of every role a user holds."""
    granted: set[str] = set(BASE_PERMISSIONS)
    for role in roles:
        try:
            granted |= ROLE_PERMISSIONS[RoleName(role)]
        except ValueError:
            # Custom role created at runtime; its grants come from the database and are
            # merged by the auth service, not from this static matrix.
            continue
    return frozenset(granted)
