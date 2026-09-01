"""Default email templates and safe variable rendering.

Templates are stored per company and editable by recruiters. Rendering uses a Jinja2
``SandboxedEnvironment`` with autoescaping and an explicit variable allow-list, so an
edited template can never reach into application internals or inject markup - a template
is user-supplied content, and is treated as such.
"""

from __future__ import annotations

from dataclasses import dataclass

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import escape

from app.core.enums import EmailTemplateKey

#: Every variable a template may reference. Anything else raises at render time rather
#: than silently producing an empty string in a candidate-facing email.
ALLOWED_VARIABLES: frozenset[str] = frozenset(
    {
        "candidate_name",
        "candidate_first_name",
        "candidate_email",
        "job_title",
        "job_location",
        "job_reference",
        "company_name",
        "company_website",
        "recruiter_name",
        "recruiter_email",
        "application_reference",
        "application_status",
        "application_url",
        "interview_date",
        "interview_time",
        "interview_timezone",
        "interview_type",
        "interview_round",
        "interviewer_names",
        "meeting_link",
        "interview_location",
        "assessment_name",
        "assessment_url",
        "assessment_deadline",
        "offer_url",
        "offer_expiry",
        "offer_position",
        "offer_salary",
        "joining_date",
        "verification_url",
        "reset_url",
        "portal_url",
        "current_year",
        "custom_message",
    }
)

_BASE_LAYOUT = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6f8;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:12px;border:1px solid #e5e7eb;overflow:hidden;">
<tr><td style="padding:24px 32px;border-bottom:1px solid #f0f1f3;">
<span style="font-size:18px;font-weight:700;color:#111827;letter-spacing:-0.02em;">{{ company_name }}</span>
</td></tr>
<tr><td style="padding:32px;color:#374151;font-size:15px;line-height:1.6;">
__BODY__
</td></tr>
<tr><td style="padding:20px 32px;background:#fafafa;border-top:1px solid #f0f1f3;color:#9ca3af;font-size:12px;line-height:1.5;">
This message was sent by {{ company_name }} via HireHQ regarding your application.<br>
&copy; {{ current_year }} {{ company_name }}
</td></tr>
</table>
</td></tr></table>
</body></html>"""

_BUTTON = (
    '<a href="{{ %s }}" style="display:inline-block;background:#111827;color:#ffffff;'
    'text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;'
    'font-size:14px;margin:8px 0;">%s</a>'
)


def _layout(body: str) -> str:
    return _BASE_LAYOUT.replace("__BODY__", body)


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    key: EmailTemplateKey
    name: str
    subject: str
    body_html: str
    variables: tuple[str, ...]


DEFAULT_TEMPLATES: tuple[TemplateDefinition, ...] = (
    TemplateDefinition(
        key=EmailTemplateKey.APPLICATION_RECEIVED,
        name="Application received",
        subject="We received your application for {{ job_title }}",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>Thank you for applying for the <strong>{{ job_title }}</strong> role at "
            "{{ company_name }}. Your application reference is "
            "<strong>{{ application_reference }}</strong>.</p>"
            "<p>Our team is reviewing applications now. We will be in touch as soon as "
            "there is an update.</p>"
            + (_BUTTON % ("application_url", "Track your application"))
            + "<p>Best regards,<br>{{ company_name }} Talent Team</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name",
            "application_reference", "application_url",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.SHORTLISTED,
        name="Candidate shortlisted",
        subject="Good news about your {{ job_title }} application",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>We have reviewed your application for <strong>{{ job_title }}</strong> and "
            "would like to move you forward to the next stage.</p>"
            "<p>{{ custom_message }}</p>"
            "<p>Someone from our team will contact you shortly with next steps.</p>"
            + (_BUTTON % ("application_url", "View your application"))
            + "<p>Best regards,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "recruiter_name",
            "custom_message", "application_url",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.SCREENING_INVITATION,
        name="Screening invitation",
        subject="Next step for your {{ job_title }} application",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>We would like to invite you to a short screening conversation for the "
            "<strong>{{ job_title }}</strong> role.</p>"
            "<p>{{ custom_message }}</p>"
            + (_BUTTON % ("application_url", "View details"))
            + "<p>Best regards,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "recruiter_name",
            "custom_message", "application_url",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.INTERVIEW_INVITATION,
        name="Interview invitation",
        subject="Interview scheduled: {{ job_title }} at {{ company_name }}",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>Your <strong>{{ interview_type }}</strong> interview for "
            "<strong>{{ job_title }}</strong> has been scheduled.</p>"
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            'style="margin:16px 0;border:1px solid #e5e7eb;border-radius:8px;width:100%;">'
            '<tr><td style="padding:14px 16px;border-bottom:1px solid #f0f1f3;">'
            '<strong>Date</strong><br>{{ interview_date }}</td></tr>'
            '<tr><td style="padding:14px 16px;border-bottom:1px solid #f0f1f3;">'
            '<strong>Time</strong><br>{{ interview_time }} ({{ interview_timezone }})</td></tr>'
            '<tr><td style="padding:14px 16px;">'
            '<strong>Round</strong><br>{{ interview_round }}</td></tr>'
            "</table>"
            + (_BUTTON % ("meeting_link", "Join the interview"))
            + "<p style='color:#6b7280;font-size:13px;'>If the time does not work for you, "
            "reply to this email and we will find another slot.</p>"
            "<p>Best regards,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "interview_type",
            "interview_date", "interview_time", "interview_timezone", "interview_round",
            "meeting_link", "recruiter_name",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.INTERVIEW_RESCHEDULED,
        name="Interview rescheduled",
        subject="Your {{ job_title }} interview has been rescheduled",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>Your interview for <strong>{{ job_title }}</strong> has been moved to a new "
            "time.</p>"
            "<p><strong>New date:</strong> {{ interview_date }}<br>"
            "<strong>New time:</strong> {{ interview_time }} ({{ interview_timezone }})</p>"
            + (_BUTTON % ("meeting_link", "Join the interview"))
            + "<p>Apologies for any inconvenience.</p>"
            "<p>Best regards,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "interview_date",
            "interview_time", "interview_timezone", "meeting_link", "recruiter_name",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.INTERVIEW_REMINDER,
        name="Interview reminder",
        subject="Reminder: your {{ job_title }} interview is coming up",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>This is a reminder about your <strong>{{ interview_type }}</strong> interview "
            "for <strong>{{ job_title }}</strong>.</p>"
            "<p><strong>{{ interview_date }}</strong> at <strong>{{ interview_time }}</strong> "
            "({{ interview_timezone }})</p>"
            + (_BUTTON % ("meeting_link", "Join the interview"))
            + "<p>Best of luck,<br>{{ company_name }} Talent Team</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "interview_type",
            "interview_date", "interview_time", "interview_timezone", "meeting_link",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.ASSESSMENT_INVITATION,
        name="Assessment invitation",
        subject="Complete your assessment for {{ job_title }}",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>As the next step for <strong>{{ job_title }}</strong>, please complete the "
            "<strong>{{ assessment_name }}</strong> assessment.</p>"
            "<p>Please complete it by <strong>{{ assessment_deadline }}</strong>.</p>"
            + (_BUTTON % ("assessment_url", "Start the assessment"))
            + "<p>Best regards,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "assessment_name",
            "assessment_deadline", "assessment_url", "recruiter_name",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.SELECTED,
        name="Candidate selected",
        subject="Great news about your application for {{ job_title }}",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>We are delighted to let you know that you have been selected for the "
            "<strong>{{ job_title }}</strong> role at {{ company_name }}.</p>"
            "<p>{{ custom_message }}</p>"
            "<p>Your formal offer will follow shortly.</p>"
            "<p>Congratulations,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "recruiter_name",
            "custom_message",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.REJECTED,
        name="Application not progressing",
        subject="Update on your application for {{ job_title }}",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>Thank you for your interest in the <strong>{{ job_title }}</strong> role at "
            "{{ company_name }}, and for the time you invested in the process.</p>"
            "<p>On this occasion we have decided to move forward with other candidates. This "
            "was a difficult decision and it is not a reflection of your abilities.</p>"
            "<p>{{ custom_message }}</p>"
            "<p>We would be glad to hear from you about future openings.</p>"
            "<p>Best wishes,<br>{{ company_name }} Talent Team</p>"
        ),
        variables=(
            "candidate_first_name", "job_title", "company_name", "custom_message",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.ON_HOLD,
        name="Application on hold",
        subject="Your {{ job_title }} application is on hold",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>We wanted to update you on your application for <strong>{{ job_title }}</strong>. "
            "The role is currently on hold, so there will be a pause before we can move "
            "forward.</p>"
            "<p>{{ custom_message }}</p>"
            "<p>Thank you for your patience,<br>{{ company_name }} Talent Team</p>"
        ),
        variables=("candidate_first_name", "job_title", "company_name", "custom_message"),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.OFFER,
        name="Offer letter",
        subject="Your offer from {{ company_name }}",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>We are pleased to offer you the position of "
            "<strong>{{ offer_position }}</strong> at {{ company_name }}.</p>"
            "<p><strong>Proposed start date:</strong> {{ joining_date }}<br>"
            "<strong>Offer valid until:</strong> {{ offer_expiry }}</p>"
            "<p>Please review the full details and let us know your decision.</p>"
            + (_BUTTON % ("offer_url", "View and respond to your offer"))
            + "<p>Warm regards,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "company_name", "offer_position", "joining_date",
            "offer_expiry", "offer_url", "recruiter_name",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.OFFER_REMINDER,
        name="Offer reminder",
        subject="Reminder: your offer from {{ company_name }} expires soon",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>A friendly reminder that your offer for <strong>{{ offer_position }}</strong> "
            "is valid until <strong>{{ offer_expiry }}</strong>.</p>"
            + (_BUTTON % ("offer_url", "Respond to your offer"))
            + "<p>If you have any questions, just reply to this email.</p>"
            "<p>Best regards,<br>{{ recruiter_name }}<br>{{ company_name }}</p>"
        ),
        variables=(
            "candidate_first_name", "company_name", "offer_position", "offer_expiry",
            "offer_url", "recruiter_name",
        ),
    ),
    TemplateDefinition(
        key=EmailTemplateKey.JOINING_REMINDER,
        name="Joining reminder",
        subject="Looking forward to welcoming you on {{ joining_date }}",
        body_html=_layout(
            "<p>Hi {{ candidate_first_name }},</p>"
            "<p>We are looking forward to welcoming you to {{ company_name }} as "
            "<strong>{{ offer_position }}</strong> on <strong>{{ joining_date }}</strong>.</p>"
            "<p>{{ custom_message }}</p>"
            + (_BUTTON % ("portal_url", "Complete your onboarding"))
            + "<p>See you soon,<br>{{ company_name }} People Team</p>"
        ),
        variables=(
            "candidate_first_name", "company_name", "offer_position", "joining_date",
            "custom_message", "portal_url",
        ),
    ),
)

TEMPLATES_BY_KEY: dict[EmailTemplateKey, TemplateDefinition] = {
    definition.key: definition for definition in DEFAULT_TEMPLATES
}


# --------------------------------------------------------------- rendering
_env = SandboxedEnvironment(
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


class TemplateRenderError(ValueError):
    """Raised when a template references an unknown variable or fails to render."""


def render_template(source: str, variables: dict[str, object]) -> str:
    """Render a template against the allow-listed variable set.

    Values are HTML-escaped by autoescaping. Unknown variables raise rather than
    rendering as empty, so a typo in an edited template is caught when the recruiter
    saves it rather than being discovered by a candidate.
    """
    safe_context = {
        key: ("" if value is None else value)
        for key, value in variables.items()
        if key in ALLOWED_VARIABLES
    }
    for name in ALLOWED_VARIABLES:
        safe_context.setdefault(name, "")

    try:
        return _env.from_string(source).render(**safe_context)
    except Exception as exc:
        raise TemplateRenderError(str(exc)) from exc


def validate_template_source(source: str) -> list[str]:
    """Return the variables a template uses that are not in the allow-list."""
    from jinja2 import meta

    try:
        parsed = _env.parse(source)
    except Exception as exc:
        raise TemplateRenderError(f"Template syntax error: {exc}") from exc
    return sorted(meta.find_undeclared_variables(parsed) - ALLOWED_VARIABLES)


def plain_text_preview(html: str) -> str:
    from app.providers.email import _html_to_text

    return _html_to_text(html)


def safe(value: object) -> str:
    return str(escape(str(value)))
