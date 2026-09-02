"""Email transport abstraction.

The critical rule (s69): **never report an email as sent when it was not**. The console
provider exists so local development works end to end, but it returns
``NOT_SENT_NO_PROVIDER`` and every layer above - the database row, the API response and
the recruiter UI - carries that through truthfully.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings
from app.core.enums import EmailDeliveryStatus
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class OutgoingEmail:
    to: list[str]
    subject: str
    body_html: str
    body_text: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: str | None = None
    from_address: str | None = None
    from_name: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)


@dataclass(slots=True)
class DeliveryResult:
    status: EmailDeliveryStatus
    transport: str
    message_id: str | None = None
    detail: str | None = None

    @property
    def was_transmitted(self) -> bool:
        return self.status == EmailDeliveryStatus.SENT


class EmailProvider(ABC):
    name: str = "abstract"
    #: False means "this transport does not actually deliver mail anywhere".
    transmits: bool = False

    @abstractmethod
    async def send(self, message: OutgoingEmail) -> DeliveryResult: ...


class ConsoleEmailProvider(EmailProvider):
    """Development transport. Logs a summary and reports honestly that nothing was sent."""

    name = "console"
    transmits = False

    async def send(self, message: OutgoingEmail) -> DeliveryResult:
        logger.info(
            "email_not_transmitted",
            reason="no SMTP provider configured",
            to_count=len(message.to),
            subject=message.subject,
        )
        return DeliveryResult(
            status=EmailDeliveryStatus.NOT_SENT_NO_PROVIDER,
            transport=self.name,
            detail=(
                "Recorded but not transmitted: no email provider is configured. "
                "Set EMAIL_PROVIDER=smtp and SMTP_HOST to deliver mail."
            ),
        )


class SMTPEmailProvider(EmailProvider):
    """Real SMTP delivery via ``aiosmtplib``."""

    name = "smtp"
    transmits = True

    def __init__(self) -> None:
        if not settings.SMTP_HOST:
            from app.core.exceptions import ProviderNotConfigured

            raise ProviderNotConfigured("SMTP", hint="Set SMTP_HOST (and credentials).")

    async def send(self, message: OutgoingEmail) -> DeliveryResult:
        from email.message import EmailMessage as MimeMessage

        import aiosmtplib

        mime = MimeMessage()
        sender = message.from_address or settings.EMAIL_FROM_ADDRESS
        sender_name = message.from_name or settings.EMAIL_FROM_NAME
        mime["From"] = f"{sender_name} <{sender}>"
        mime["To"] = ", ".join(message.to)
        if message.cc:
            mime["Cc"] = ", ".join(message.cc)
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        mime["Subject"] = message.subject
        for key, value in message.headers.items():
            mime[key] = value

        mime.set_content(message.body_text or _html_to_text(message.body_html))
        mime.add_alternative(message.body_html, subtype="html")

        for filename, content, content_type in message.attachments:
            maintype, _, subtype = content_type.partition("/")
            mime.add_attachment(
                content, maintype=maintype or "application", subtype=subtype or "octet-stream",
                filename=filename,
            )

        try:
            response = await aiosmtplib.send(
                mime,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                start_tls=settings.SMTP_USE_TLS,
                recipients=[*message.to, *message.cc, *message.bcc],
                timeout=30,
            )
        except Exception as exc:
            logger.warning("email_send_failed", error=str(exc), subject=message.subject)
            return DeliveryResult(
                status=EmailDeliveryStatus.FAILED, transport=self.name, detail=str(exc)[:500]
            )

        message_id = mime.get("Message-ID")
        logger.info("email_sent", to_count=len(message.to), subject=message.subject)
        return DeliveryResult(
            status=EmailDeliveryStatus.SENT,
            transport=self.name,
            message_id=message_id,
            detail=str(response[1])[:200] if isinstance(response, tuple) else None,
        )


def _html_to_text(html: str) -> str:
    """Minimal HTML -> text for the plain-text alternative part."""
    import re

    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    if settings.EMAIL_PROVIDER == "smtp" and settings.SMTP_HOST:
        logger.info("email_provider_selected", provider="smtp", host=settings.SMTP_HOST)
        return SMTPEmailProvider()
    if settings.EMAIL_PROVIDER == "smtp":
        logger.warning(
            "email_provider_downgraded",
            reason="EMAIL_PROVIDER=smtp but SMTP_HOST is not set",
            using="console",
        )
    logger.info("email_provider_selected", provider="console", transmits=False)
    return ConsoleEmailProvider()


def reset_email_provider() -> None:
    get_email_provider.cache_clear()


def email_verification_required() -> bool:
    """Whether an unverified account should be refused sign-in.

    Requiring verification is only meaningful if the verification link can reach the
    person: with a provider that records but does not transmit, the link is generated,
    stored, and never delivered, so the requirement can never be satisfied by anyone.
    Enforcing it then is not a security control, it is a lockout of every user including
    the first administrator.

    So the default is to follow the provider's actual capability. ``REQUIRE_EMAIL_
    VERIFICATION`` overrides it in either direction when you want to decide explicitly.
    """
    if settings.REQUIRE_EMAIL_VERIFICATION is not None:
        return settings.REQUIRE_EMAIL_VERIFICATION
    return get_email_provider().transmits


async def send_email(message: OutgoingEmail) -> DeliveryResult:
    return await get_email_provider().send(message)


__all__ = [
    "ConsoleEmailProvider",
    "DeliveryResult",
    "EmailProvider",
    "OutgoingEmail",
    "SMTPEmailProvider",
    "email_verification_required",
    "get_email_provider",
    "reset_email_provider",
    "send_email",
]
