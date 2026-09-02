"""Authentication service: registration, login, tokens, verification and passwords."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import AuditAction, RoleName, UserStatus
from app.core.exceptions import (
    AccountInactive,
    BusinessRuleError,
    DuplicateResource,
    InvalidCredentials,
    InvalidToken,
    ResourceNotFound,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.permissions import permissions_for_roles
from app.core.security import (
    create_token,
    decode_token,
    generate_url_token,
    hash_password,
    hash_url_token,
    verify_password,
)
from app.models.user import RefreshToken, Role, User, VerificationToken
from app.modules.auth.schemas import TokenPair
from app.providers.email import email_verification_required
from app.services.audit import AuditService

logger = get_logger(__name__)

#: Lock an account after this many consecutive failures, for this long. Slows credential
#: stuffing without letting an attacker lock a known user out indefinitely.
MAX_FAILED_LOGINS = 8
LOCKOUT_MINUTES = 15

PURPOSE_EMAIL_VERIFY = "EMAIL_VERIFY"
PURPOSE_PASSWORD_RESET = "PASSWORD_RESET"


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ------------------------------------------------------------ registration
    async def register_candidate(
        self,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, str]:
        """Create a candidate account. Returns ``(user, raw_verification_token)``."""
        email = email.strip().lower()
        existing = await self.session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise DuplicateResource(
                "An account with this email already exists",
                code="EMAIL_ALREADY_REGISTERED",
            )

        role = await self._get_system_role(RoleName.CANDIDATE)
        user = User(
            email=email,
            hashed_password=hash_password(password),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone.strip() if phone else None,
            # Only park the account as unverified if verification is actually enforced.
            # Otherwise every account would sit in PENDING_VERIFICATION for good, which
            # reads as "waiting on the candidate" in every admin view when in fact nothing
            # is ever going to arrive for them to act on.
            status=(
                UserStatus.PENDING_VERIFICATION
                if email_verification_required()
                else UserStatus.ACTIVE
            ),
        )
        user.roles.append(role)
        self.session.add(user)
        await self.session.flush()

        raw_token = await self.issue_verification_token(user, PURPOSE_EMAIL_VERIFY)
        await self.audit.record(
            action=AuditAction.CREATE,
            entity_type="User",
            entity_id=user.id,
            summary=f"Candidate account registered for {email}",
            actor_id=user.id,
            actor_email=email,
            actor_roles=[RoleName.CANDIDATE.value],
            ip_address=ip_address,
        )
        logger.info("user_registered", user_id=str(user.id), role="CANDIDATE")
        return user, raw_token

    async def _get_system_role(self, name: RoleName) -> Role:
        role = await self.session.scalar(
            select(Role).where(Role.name == name.value, Role.company_id.is_(None))
        )
        if role is None:
            raise BusinessRuleError(
                f"The built-in role {name.value} is missing. Run the database seed.",
                code="ROLE_NOT_SEEDED",
            )
        return role

    # ------------------------------------------------------------------ login
    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, TokenPair]:
        email = email.strip().lower()
        stmt = (
            select(User)
            .where(User.email == email, User.deleted_at.is_(None))
            .options(selectinload(User.roles))
        )
        user = (await self.session.execute(stmt)).unique().scalar_one_or_none()

        if user is None:
            # Hash anyway so a missing account and a wrong password take the same time.
            verify_password(password, "$2b$12$" + "x" * 53)
            await self._record_failed_login(email, ip_address, reason="unknown_account")
            raise InvalidCredentials()

        now = datetime.now(UTC)
        if user.locked_until and user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds() / 60) + 1
            raise AccountInactive(
                f"Too many failed sign-in attempts. Try again in {remaining} minute(s).",
                code="ACCOUNT_LOCKED",
            )

        if not verify_password(password, user.hashed_password):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                logger.warning("account_locked", user_id=str(user.id))
            await self._record_failed_login(
                email, ip_address, reason="bad_password", user_id=user.id
            )
            raise InvalidCredentials()

        if user.status == UserStatus.PENDING_VERIFICATION and email_verification_required():
            from app.core.exceptions import EmailNotVerified

            raise EmailNotVerified()
        if user.status in (UserStatus.INACTIVE, UserStatus.SUSPENDED):
            raise AccountInactive(f"This account is {user.status.value.lower()}")

        # Reaching here while still marked PENDING_VERIFICATION means verification is not
        # being enforced, so the status is describing a wait that will never end. Clear it
        # on a successful sign-in; accounts created before the setting changed heal
        # themselves rather than needing a manual fix.
        if user.status == UserStatus.PENDING_VERIFICATION:
            user.status = UserStatus.ACTIVE

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now

        tokens = await self.issue_tokens(user, ip_address=ip_address, user_agent=user_agent)
        await self.audit.record(
            action=AuditAction.LOGIN,
            entity_type="User",
            entity_id=user.id,
            summary=f"{user.email} signed in",
            company_id=user.company_id,
            actor_id=user.id,
            actor_email=user.email,
            actor_roles=sorted(user.role_names),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return user, tokens

    async def _record_failed_login(
        self,
        email: str,
        ip_address: str | None,
        *,
        reason: str,
        user_id: uuid.UUID | None = None,
    ) -> None:
        await self.audit.record(
            action=AuditAction.LOGIN_FAILED,
            entity_type="User",
            entity_id=user_id,
            summary=f"Failed sign-in attempt for {email}",
            actor_email=email,
            meta={"reason": reason},
            ip_address=ip_address,
        )

    # ----------------------------------------------------------------- tokens
    async def issue_tokens(
        self,
        user: User,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        roles = sorted(user.role_names)
        access, _, _ = create_token(
            subject=str(user.id),
            token_type="access",
            company_id=str(user.company_id) if user.company_id else None,
            roles=roles,
        )
        refresh, jti, expires_at = create_token(
            subject=str(user.id),
            token_type="refresh",
            company_id=str(user.company_id) if user.company_id else None,
        )
        self.session.add(
            RefreshToken(
                jti=jti,
                user_id=user.id,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=(user_agent or "")[:512] or None,
            )
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.JWT_ACCESS_EXPIRE_MINUTES * 60,
        )

    async def refresh_tokens(
        self,
        refresh_token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, TokenPair]:
        """Rotate a refresh token, detecting replay.

        If a token that has already been rotated is presented again, the whole family is
        revoked: either it leaked, or a client is badly broken. Either way, forcing a new
        sign-in is the safe response.
        """
        import jwt as pyjwt

        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except pyjwt.ExpiredSignatureError as exc:
            raise InvalidToken("This session has expired, please sign in again") from exc
        except pyjwt.PyJWTError as exc:
            raise InvalidToken() from exc

        record = await self.session.scalar(
            select(RefreshToken).where(RefreshToken.jti == payload["jti"])
        )
        if record is None:
            raise InvalidToken("Unknown refresh token")

        if record.revoked_at is not None:
            logger.warning("refresh_token_replay", user_id=str(record.user_id))
            await self.revoke_all_sessions(record.user_id, reason="refresh_token_replay")
            raise InvalidToken("This session is no longer valid, please sign in again")

        if record.expires_at <= datetime.now(UTC):
            raise InvalidToken("This session has expired, please sign in again")

        stmt = (
            select(User)
            .where(User.id == record.user_id, User.deleted_at.is_(None))
            .options(selectinload(User.roles))
        )
        user = (await self.session.execute(stmt)).unique().scalar_one_or_none()
        if user is None or not user.is_active:
            raise InvalidToken("This account is no longer active")

        tokens = await self.issue_tokens(user, ip_address=ip_address, user_agent=user_agent)
        if settings.JWT_REFRESH_ROTATION:
            record.revoked_at = datetime.now(UTC)
            new_payload = decode_token(tokens.refresh_token, expected_type="refresh")
            record.replaced_by_jti = new_payload["jti"]
        return user, tokens

    async def logout(self, refresh_token: str | None, user_id: uuid.UUID) -> None:
        if refresh_token:
            try:
                payload = decode_token(refresh_token, expected_type="refresh")
                await self.session.execute(
                    update(RefreshToken)
                    .where(RefreshToken.jti == payload["jti"], RefreshToken.user_id == user_id)
                    .values(revoked_at=datetime.now(UTC))
                )
            except Exception:
                # A malformed token on logout is not worth failing the request over.
                logger.debug("logout_token_undecodable")

    async def revoke_all_sessions(self, user_id: uuid.UUID, *, reason: str) -> None:
        """Revoke every refresh token and invalidate outstanding access tokens."""
        now = datetime.now(UTC)
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await self.session.execute(
            update(User).where(User.id == user_id).values(tokens_valid_from=now)
        )
        logger.info("sessions_revoked", user_id=str(user_id), reason=reason)

    # ---------------------------------------------------- verification tokens
    async def issue_verification_token(self, user: User, purpose: str) -> str:
        """Mint a single-use token, invalidating any outstanding one for this purpose."""
        await self.session.execute(
            update(VerificationToken)
            .where(
                VerificationToken.user_id == user.id,
                VerificationToken.purpose == purpose,
                VerificationToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )

        raw = generate_url_token()
        ttl = (
            timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)
            if purpose == PURPOSE_EMAIL_VERIFY
            else timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
        )
        self.session.add(
            VerificationToken(
                token_hash=hash_url_token(raw),
                purpose=purpose,
                user_id=user.id,
                expires_at=datetime.now(UTC) + ttl,
            )
        )
        return raw

    async def _consume_token(self, raw_token: str, purpose: str) -> User:
        record = await self.session.scalar(
            select(VerificationToken).where(
                VerificationToken.token_hash == hash_url_token(raw_token),
                VerificationToken.purpose == purpose,
            )
        )
        if record is None or record.used_at is not None:
            raise InvalidToken("This link is invalid or has already been used")
        if record.expires_at <= datetime.now(UTC):
            raise InvalidToken("This link has expired. Please request a new one.")

        record.used_at = datetime.now(UTC)
        user = await self.session.get(User, record.user_id)
        if user is None:
            raise ResourceNotFound("User", record.user_id)
        return user

    async def verify_email(self, raw_token: str) -> User:
        user = await self._consume_token(raw_token, PURPOSE_EMAIL_VERIFY)
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
        if user.status == UserStatus.PENDING_VERIFICATION:
            user.status = UserStatus.ACTIVE
        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="User",
            entity_id=user.id,
            summary=f"{user.email} verified their email address",
            company_id=user.company_id,
            actor_id=user.id,
            actor_email=user.email,
        )
        return user

    async def start_password_reset(self, email: str) -> tuple[User, str] | None:
        """Return ``(user, token)``, or None when no such account exists.

        The caller must respond identically either way so this endpoint cannot be used to
        enumerate registered email addresses.
        """
        user = await self.session.scalar(
            select(User).where(User.email == email.strip().lower(), User.deleted_at.is_(None))
        )
        if user is None:
            logger.info("password_reset_unknown_email")
            return None
        raw = await self.issue_verification_token(user, PURPOSE_PASSWORD_RESET)
        return user, raw

    async def complete_password_reset(self, raw_token: str, new_password: str) -> User:
        user = await self._consume_token(raw_token, PURPOSE_PASSWORD_RESET)
        user.hashed_password = hash_password(new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        if user.status == UserStatus.PENDING_VERIFICATION:
            # Completing a reset proves control of the mailbox.
            user.status = UserStatus.ACTIVE
            user.email_verified_at = user.email_verified_at or datetime.now(UTC)
        await self.revoke_all_sessions(user.id, reason="password_reset")
        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="User",
            entity_id=user.id,
            summary=f"{user.email} reset their password",
            company_id=user.company_id,
            actor_id=user.id,
            actor_email=user.email,
        )
        return user

    async def change_password(
        self, user: User, *, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.hashed_password):
            raise InvalidCredentials("Your current password is incorrect")
        if verify_password(new_password, user.hashed_password):
            raise ValidationError("The new password must differ from the current one")

        user.hashed_password = hash_password(new_password)
        await self.revoke_all_sessions(user.id, reason="password_change")
        await self.audit.record(
            action=AuditAction.UPDATE,
            entity_type="User",
            entity_id=user.id,
            summary=f"{user.email} changed their password",
            company_id=user.company_id,
            actor_id=user.id,
            actor_email=user.email,
        )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def resolve_permissions(user: User) -> list[str]:
        permissions = set(permissions_for_roles(list(user.role_names)))
        for role in user.roles:
            if not role.is_system:
                permissions |= role.permission_codes
        return sorted(permissions)
