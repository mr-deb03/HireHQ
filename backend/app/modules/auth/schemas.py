"""Request/response schemas for authentication."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.enums import RoleName, UserStatus
from app.core.security import password_strength_errors


class PasswordMixin:
    @field_validator("password", check_fields=False)
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if errors := password_strength_errors(value):
            raise ValueError("Password " + "; ".join(errors))
        return value


class RegisterRequest(BaseModel, PasswordMixin):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    #: Self-registration only ever creates a CANDIDATE. Staff accounts are created by a
    #: company admin through the users API, so nobody can grant themselves a role here.
    accept_terms: bool = Field(description="Must be true to create an account")

    @field_validator("accept_terms")
    @classmethod
    def _must_accept(cls, value: bool) -> bool:
        if not value:
            raise ValueError("You must accept the terms and privacy policy to register")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel, PasswordMixin):
    token: str
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel, PasswordMixin):
    current_password: str
    password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None = None


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    full_name: str
    phone: str | None = None
    avatar_url: str | None = None
    job_title: str | None = None
    timezone: str
    locale: str
    status: UserStatus
    email_verified_at: datetime | None = None
    last_login_at: datetime | None = None
    company_id: uuid.UUID | None = None
    company: CompanySummary | None = None
    roles: list[RoleSummary] = Field(default_factory=list)
    created_at: datetime


class AuthenticatedUser(UserProfile):
    """Profile plus the resolved permission set the frontend uses to gate UI."""

    permissions: list[str] = Field(default_factory=list)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds")


class LoginResponse(BaseModel):
    tokens: TokenPair
    user: AuthenticatedUser


class RegisterResponse(BaseModel):
    user: UserProfile
    #: Email delivery is reported truthfully - see ``EmailDeliveryStatus``.
    verification_email_status: str
    message: str


class UpdateProfileRequest(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=150)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=10)
    avatar_url: str | None = Field(default=None, max_length=512)
    notification_preferences: dict | None = None


class MessageResponse(BaseModel):
    message: str
    #: Whether this server can actually transmit email. It is a property of the
    #: deployment, not of the account, so returning it leaks nothing about whether an
    #: address is registered - while still keeping the product from claiming a link was
    #: delivered when no provider is configured (s69).
    email_delivery: str | None = Field(
        default=None,
        description=(
            "SENT | NOT_SENT_NO_PROVIDER | FAILED, or null when this response did not "
            "involve sending an email."
        ),
    )


__all__ = [
    "AuthenticatedUser",
    "ChangePasswordRequest",
    "CompanySummary",
    "ForgotPasswordRequest",
    "LoginRequest",
    "LoginResponse",
    "MessageResponse",
    "RefreshRequest",
    "RegisterRequest",
    "RegisterResponse",
    "ResendVerificationRequest",
    "ResetPasswordRequest",
    "RoleName",
    "RoleSummary",
    "TokenPair",
    "UpdateProfileRequest",
    "UserProfile",
    "VerifyEmailRequest",
]
