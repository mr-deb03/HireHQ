"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import EmailDeliveryStatus
from app.core.responses import SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CurrentUser
from app.modules.auth.schemas import (
    AuthenticatedUser,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenPair,
    UpdateProfileRequest,
    UserProfile,
    VerifyEmailRequest,
)
from app.modules.auth.service import PURPOSE_EMAIL_VERIFY, AuthService
from app.providers.email import OutgoingEmail, get_email_provider

router = APIRouter(prefix="/auth", tags=["Authentication"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _to_authenticated(user, permissions: list[str]) -> AuthenticatedUser:
    return AuthenticatedUser.model_validate(
        {**UserProfile.model_validate(user).model_dump(), "permissions": permissions}
    )


async def _send_account_email(
    *, to: str, subject: str, heading: str, body: str, link: str, cta: str
) -> EmailDeliveryStatus:
    """Send a platform (non-tenant) email such as verification or password reset.

    These are not company templates - they come from HireHQ itself - so they bypass the
    per-company template store and go straight to the transport.
    """
    html = f"""<!DOCTYPE html><html><body style="margin:0;background:#f5f6f8;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;"><tr><td align="center">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#fff;
border:1px solid #e5e7eb;border-radius:12px;">
<tr><td style="padding:28px 32px;">
<div style="font-size:18px;font-weight:700;color:#111827;margin-bottom:20px;">HireHQ</div>
<h1 style="font-size:20px;color:#111827;margin:0 0 12px;">{heading}</h1>
<p style="color:#4b5563;font-size:15px;line-height:1.6;margin:0 0 20px;">{body}</p>
<a href="{link}" style="display:inline-block;background:#111827;color:#fff;text-decoration:none;
padding:12px 24px;border-radius:8px;font-weight:600;font-size:14px;">{cta}</a>
<p style="color:#9ca3af;font-size:12px;margin-top:24px;line-height:1.5;">
If the button does not work, copy this link into your browser:<br>
<span style="word-break:break-all;">{link}</span></p>
</td></tr></table></td></tr></table></body></html>"""

    result = await get_email_provider().send(
        OutgoingEmail(to=[to], subject=subject, body_html=html)
    )
    return result.status


def _delivery_capability() -> str:
    """Whether this deployment can transmit email, as a delivery-status value.

    Used on the enumeration-resistant endpoints, where we must not say whether a
    particular address was mailed but must still not claim a link is "on its way" when
    no provider exists to send it.
    """
    return (
        EmailDeliveryStatus.SENT
        if get_email_provider().transmits
        else EmailDeliveryStatus.NOT_SENT_NO_PROVIDER
    )


# ------------------------------------------------------------------ register
@router.post(
    "/register",
    response_model=SuccessResponse[RegisterResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Register a candidate account",
    description=(
        "Creates a candidate account and sends a verification email. Self-registration "
        "always produces a CANDIDATE; staff accounts are created by a company admin."
    ),
)
async def register(
    payload: RegisterRequest, request: Request, session: DbSession
) -> SuccessResponse[RegisterResponse]:
    service = AuthService(session)
    user, raw_token = await service.register_candidate(
        email=payload.email,
        password=payload.password,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        ip_address=_client_ip(request),
    )
    await session.flush()

    verify_url = f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw_token}"
    email_status = await _send_account_email(
        to=user.email,
        subject="Verify your HireHQ account",
        heading="Confirm your email address",
        body=(
            f"Welcome, {user.first_name}. Confirm your email address to activate your "
            "HireHQ account and start applying for roles."
        ),
        link=verify_url,
        cta="Verify email address",
    )

    message = "Account created. Check your email to verify your address."
    if email_status != EmailDeliveryStatus.SENT:
        message = (
            "Account created. The verification email could not be delivered because no "
            "email provider is configured on this server - ask an administrator to "
            "verify your account or configure SMTP."
        )

    return SuccessResponse(
        data=RegisterResponse(
            user=UserProfile.model_validate(user),
            verification_email_status=email_status.value,
            message=message,
        ),
        message=message,
    )


# --------------------------------------------------------------------- login
@router.post(
    "/login",
    response_model=SuccessResponse[LoginResponse],
    summary="Sign in",
    description="Exchange email and password for an access/refresh token pair.",
)
async def login(
    payload: LoginRequest, request: Request, session: DbSession
) -> SuccessResponse[LoginResponse]:
    service = AuthService(session)
    user, tokens = await service.authenticate(
        email=payload.email,
        password=payload.password,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SuccessResponse(
        data=LoginResponse(
            tokens=tokens,
            user=_to_authenticated(user, AuthService.resolve_permissions(user)),
        ),
        message="Signed in successfully",
    )


@router.post(
    "/refresh",
    response_model=SuccessResponse[TokenPair],
    summary="Refresh the access token",
    description=(
        "Exchanges a refresh token for a new pair. Tokens rotate: the presented token is "
        "revoked. Re-presenting a rotated token revokes every session for that account."
    ),
)
async def refresh(
    payload: RefreshRequest, request: Request, session: DbSession
) -> SuccessResponse[TokenPair]:
    service = AuthService(session)
    _, tokens = await service.refresh_tokens(
        payload.refresh_token,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SuccessResponse(data=tokens, message="Token refreshed")


@router.post(
    "/logout",
    response_model=SuccessResponse[MessageResponse],
    summary="Sign out",
)
async def logout(
    payload: RefreshRequest, principal: CurrentUser, session: DbSession
) -> SuccessResponse[MessageResponse]:
    await AuthService(session).logout(payload.refresh_token, principal.id)
    return SuccessResponse(
        data=MessageResponse(message="Signed out"), message="Signed out successfully"
    )


@router.post(
    "/logout-all",
    response_model=SuccessResponse[MessageResponse],
    summary="Sign out of every device",
)
async def logout_all(
    principal: CurrentUser, session: DbSession
) -> SuccessResponse[MessageResponse]:
    await AuthService(session).revoke_all_sessions(principal.id, reason="user_requested")
    return SuccessResponse(
        data=MessageResponse(message="All sessions have been signed out"),
        message="All sessions revoked",
    )


# -------------------------------------------------------------- verification
@router.post(
    "/verify-email",
    response_model=SuccessResponse[MessageResponse],
    summary="Verify an email address",
)
async def verify_email(
    payload: VerifyEmailRequest, session: DbSession
) -> SuccessResponse[MessageResponse]:
    user = await AuthService(session).verify_email(payload.token)
    return SuccessResponse(
        data=MessageResponse(message=f"{user.email} is now verified"),
        message="Email verified. You can now sign in.",
    )


@router.post(
    "/resend-verification",
    response_model=SuccessResponse[MessageResponse],
    summary="Resend the verification email",
    description=(
        "Always returns the same response whether or not the address is registered, so "
        "it cannot be used to discover which emails have accounts. `email_delivery` "
        "reports whether this server can send email at all - a property of the "
        "deployment, not of the account."
    ),
)
async def resend_verification(
    payload: ResendVerificationRequest, session: DbSession
) -> SuccessResponse[MessageResponse]:
    from sqlalchemy import select

    from app.models.user import User

    generic = "If that address has an unverified account, a verification email is on its way."
    user = await session.scalar(
        select(User).where(User.email == payload.email.strip().lower(), User.deleted_at.is_(None))
    )
    if user is not None and user.email_verified_at is None:
        service = AuthService(session)
        raw_token = await service.issue_verification_token(user, PURPOSE_EMAIL_VERIFY)
        await session.flush()
        await _send_account_email(
            to=user.email,
            subject="Verify your HireHQ account",
            heading="Confirm your email address",
            body="Confirm your email address to activate your HireHQ account.",
            link=f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw_token}",
            cta="Verify email address",
        )
    return SuccessResponse(
        data=MessageResponse(message=generic, email_delivery=_delivery_capability()),
        message=generic,
    )


# ------------------------------------------------------------------ password
@router.post(
    "/forgot-password",
    response_model=SuccessResponse[MessageResponse],
    summary="Request a password reset",
    description=(
        "Always returns the same response regardless of whether the address exists, to "
        "prevent account enumeration.\n\n"
        "`email_delivery` reports whether this deployment can transmit email at all. It "
        "describes the server, not the account, so it reveals nothing about whether the "
        "address is registered - but it stops the UI from promising a link that no "
        "configured provider could send."
    ),
)
async def forgot_password(
    payload: ForgotPasswordRequest, session: DbSession
) -> SuccessResponse[MessageResponse]:
    generic = "If that address has an account, a password reset link is on its way."
    outcome = await AuthService(session).start_password_reset(payload.email)
    if outcome is not None:
        user, raw_token = outcome
        await session.flush()
        await _send_account_email(
            to=user.email,
            subject="Reset your HireHQ password",
            heading="Reset your password",
            body=(
                "We received a request to reset your password. This link expires in "
                f"{settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes. If you did not "
                "request it, you can safely ignore this email."
            ),
            link=f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}",
            cta="Reset password",
        )
    return SuccessResponse(
        data=MessageResponse(message=generic, email_delivery=_delivery_capability()),
        message=generic,
    )


@router.post(
    "/reset-password",
    response_model=SuccessResponse[MessageResponse],
    summary="Complete a password reset",
)
async def reset_password(
    payload: ResetPasswordRequest, session: DbSession
) -> SuccessResponse[MessageResponse]:
    await AuthService(session).complete_password_reset(payload.token, payload.password)
    message = "Your password has been reset. Please sign in with your new password."
    return SuccessResponse(data=MessageResponse(message=message), message=message)


@router.post(
    "/change-password",
    response_model=SuccessResponse[MessageResponse],
    summary="Change your password",
    description="Signs out every other session, since the credential has changed.",
)
async def change_password(
    payload: ChangePasswordRequest, principal: CurrentUser, session: DbSession
) -> SuccessResponse[MessageResponse]:
    await AuthService(session).change_password(
        principal.user,
        current_password=payload.current_password,
        new_password=payload.password,
    )
    message = "Password changed. Please sign in again."
    return SuccessResponse(data=MessageResponse(message=message), message=message)


# ------------------------------------------------------------------- profile
@router.get(
    "/me",
    response_model=SuccessResponse[AuthenticatedUser],
    summary="Get the signed-in user",
    description="Returns the profile plus the resolved permission set for UI gating.",
)
async def me(principal: CurrentUser) -> SuccessResponse[AuthenticatedUser]:
    return SuccessResponse(
        data=_to_authenticated(principal.user, sorted(principal.permissions))
    )


@router.patch(
    "/me",
    response_model=SuccessResponse[UserProfile],
    summary="Update your profile",
)
async def update_me(
    payload: UpdateProfileRequest, principal: CurrentUser, session: DbSession
) -> SuccessResponse[UserProfile]:
    user = principal.user
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    await session.flush()
    return SuccessResponse(
        data=UserProfile.model_validate(user), message="Profile updated"
    )
