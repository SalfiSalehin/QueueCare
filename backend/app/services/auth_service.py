"""Authentication business logic: registration, login, rotating refresh tokens, sessions, resets.

Security properties
- Argon2id hashes; dummy verification for unknown emails (no timing oracle).
- Failed-login counter with timed lockout; the failure is committed before the error is raised.
- Refresh tokens are opaque, stored hashed, single-use, and rotated on every refresh.
  Presenting an already-used token (outside a small grace window for concurrent tabs)
  is treated as theft: the whole session is revoked.
- Password change/reset revokes all sessions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import Settings
from app.models import OneTimeToken, RefreshToken, User, UserSession
from app.services.audit_service import record_audit
from app.services.email import EmailMessage, EmailProvider


class AuthError(Exception):
    """Raised for any authentication failure. `message` is safe to show to clients."""

    def __init__(self, message: str = "Invalid email or password.", status: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class IssuedSession:
    user: User
    session_id: uuid.UUID
    access_token: str
    refresh_token: str
    csrf_token: str


class AuthService:
    def __init__(self, db: Session, settings: Settings, email: EmailProvider) -> None:
        self.db = db
        self.s = settings
        self.email = email

    # ------------------------------------------------------------- register
    def register(self, *, email: str, password: str, full_name: str, phone: str | None, ip: str | None) -> User:
        email = email.strip().lower()
        user = User(email=email, password_hash=security.hash_password(password), full_name=full_name, phone=phone)
        self.db.add(user)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise AuthError("Unable to register with these details.", status=409) from None
        record_audit(self.db, action="auth.register", actor_user_id=user.id, entity_type="user",
                     entity_id=user.id, ip=ip)
        self._send_one_time(user, "EMAIL_VERIFY", timedelta(hours=self.s.email_verify_ttl_hours))
        self.db.commit()
        return user

    # ---------------------------------------------------------------- login
    def login(self, *, email: str, password: str, ip: str | None, user_agent: str | None) -> IssuedSession:
        now = security.utcnow()
        user = self.db.scalar(select(User).where(User.email == email.strip().lower()))

        if user is None:
            security.dummy_verify(password)
            record_audit(self.db, action="auth.login_failed", ip=ip, metadata={"reason": "unknown_user"})
            self.db.commit()
            raise AuthError()

        if user.locked_until and user.locked_until > now:
            security.dummy_verify(password)
            record_audit(self.db, action="auth.login_blocked", actor_user_id=user.id, ip=ip,
                         metadata={"reason": "locked"})
            self.db.commit()
            raise AuthError()  # identical to a wrong password: do not reveal the lock

        if not user.is_active or not security.verify_password(user.password_hash, password):
            user.failed_login_count += 1
            reason = "bad_password" if user.is_active else "inactive"
            if user.failed_login_count >= self.s.login_max_attempts:
                user.locked_until = now + timedelta(minutes=self.s.login_lockout_minutes)
                user.failed_login_count = 0
                reason = "lockout_triggered"
            record_audit(self.db, action="auth.login_failed", actor_user_id=user.id, ip=ip,
                         metadata={"reason": reason})
            self.db.commit()  # persist the failure even though we raise
            raise AuthError()

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if security.needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(password)
        issued = self._start_session(user, ip=ip, user_agent=user_agent)
        record_audit(self.db, action="auth.login", actor_user_id=user.id, ip=ip)
        self.db.commit()
        return issued

    def _start_session(self, user: User, *, ip: str | None, user_agent: str | None) -> IssuedSession:
        now = security.utcnow()
        session = UserSession(
            user_id=user.id, ip=ip, user_agent=(user_agent or "")[:300] or None,
            expires_at=now + timedelta(days=self.s.session_absolute_max_days),
        )
        self.db.add(session)
        self.db.flush()
        refresh = self._new_refresh_token(session, family_id=uuid.uuid4())
        return self._issue(user, session.id, refresh)

    def _new_refresh_token(self, session: UserSession, family_id: uuid.UUID) -> str:
        raw = security.generate_opaque_token()
        expires = min(security.utcnow() + timedelta(days=self.s.refresh_token_ttl_days), session.expires_at)
        self.db.add(RefreshToken(session_id=session.id, family_id=family_id,
                                 token_hash=security.hash_token(raw), expires_at=expires))
        return raw

    def _issue(self, user: User, session_id: uuid.UUID, refresh_raw: str) -> IssuedSession:
        access, _ = security.create_access_token(user.id, session_id, self.s)
        return IssuedSession(user, session_id, access, refresh_raw, security.create_csrf_token(session_id, self.s))

    # -------------------------------------------------------------- refresh
    def refresh(self, *, refresh_token: str, ip: str | None, user_agent: str | None) -> IssuedSession:
        now = security.utcnow()
        token = self.db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(refresh_token)).with_for_update()
        )
        if token is None:
            raise AuthError("Session expired. Please sign in again.")

        session = self.db.get(UserSession, token.session_id, with_for_update=True)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise AuthError("Session expired. Please sign in again.")

        if token.used_at is not None:
            # A rotated token came back. Within the grace window it is likely two tabs racing;
            # otherwise assume theft and kill the whole session.
            if (now - token.used_at).total_seconds() > self.s.refresh_reuse_grace_seconds:
                self._revoke_session(session, reason="refresh_reuse_detected")
                record_audit(self.db, action="auth.refresh_reuse_detected", actor_user_id=session.user_id,
                             entity_type="session", entity_id=session.id, ip=ip)
                self.db.commit()
            raise AuthError("Session expired. Please sign in again.")

        if token.revoked_at is not None or token.expires_at <= now:
            raise AuthError("Session expired. Please sign in again.")

        user = self.db.get(User, session.user_id)
        if user is None or not user.is_active:
            self._revoke_session(session, reason="user_inactive")
            self.db.commit()
            raise AuthError("Session expired. Please sign in again.")

        token.used_at = now
        session.last_seen_at = now
        if ip:
            session.ip = ip
        new_raw = self._new_refresh_token(session, family_id=token.family_id)
        issued = self._issue(user, session.id, new_raw)
        self.db.commit()
        return issued

    # --------------------------------------------------------------- logout
    def _revoke_session(self, session: UserSession, reason: str = "logout") -> None:
        now = security.utcnow()
        session.revoked_at = session.revoked_at or now
        self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.session_id == session.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def logout(self, session_id: uuid.UUID, *, ip: str | None) -> None:
        session = self.db.get(UserSession, session_id)
        if session is not None and session.revoked_at is None:
            self._revoke_session(session)
            record_audit(self.db, action="auth.logout", actor_user_id=session.user_id,
                         entity_type="session", entity_id=session.id, ip=ip)
            self.db.commit()

    def revoke_all_sessions(self, user_id: uuid.UUID, *, except_session: uuid.UUID | None = None) -> int:
        stmt = select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        count = 0
        for session in self.db.scalars(stmt):
            if session.id != except_session:
                self._revoke_session(session)
                count += 1
        return count

    def logout_all(self, user_id: uuid.UUID, *, ip: str | None) -> int:
        count = self.revoke_all_sessions(user_id)
        record_audit(self.db, action="auth.logout_all", actor_user_id=user_id, ip=ip, metadata={"sessions": count})
        self.db.commit()
        return count

    def revoke_one(self, user_id: uuid.UUID, session_id: uuid.UUID, *, ip: str | None) -> bool:
        session = self.db.get(UserSession, session_id)
        if session is None or session.user_id != user_id:  # ownership check: no IDOR
            return False
        self._revoke_session(session)
        record_audit(self.db, action="auth.session_revoked", actor_user_id=user_id,
                     entity_type="session", entity_id=session_id, ip=ip)
        self.db.commit()
        return True

    # ------------------------------------------------- one-time-token flows
    def _send_one_time(self, user: User, purpose: str, ttl: timedelta) -> None:
        raw = security.generate_opaque_token(32)
        self.db.add(OneTimeToken(user_id=user.id, purpose=purpose, token_hash=security.hash_token(raw),
                                 expires_at=security.utcnow() + ttl))
        path = "reset-password" if purpose == "PASSWORD_RESET" else "verify-email"
        subject = "Reset your QueueCare password" if purpose == "PASSWORD_RESET" else "Verify your QueueCare email"
        self.email.send(EmailMessage(
            to=user.email, subject=subject, kind=purpose.lower(),
            body=f"Demonstration system. Use this link: {self.s.frontend_url}/{path}?token={raw}",
        ))

    def forgot_password(self, email: str, *, ip: str | None) -> None:
        """Always succeeds silently so the endpoint cannot be used to enumerate accounts."""
        user = self.db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is not None and user.is_active:
            self._send_one_time(user, "PASSWORD_RESET", timedelta(minutes=self.s.password_reset_ttl_minutes))
            record_audit(self.db, action="auth.password_reset_requested", actor_user_id=user.id, ip=ip)
            self.db.commit()
        else:
            security.dummy_verify("x")  # keep timing close to the real path

    def _consume_token(self, raw: str, purpose: str) -> OneTimeToken:
        now = security.utcnow()
        token = self.db.scalar(
            select(OneTimeToken)
            .where(OneTimeToken.token_hash == security.hash_token(raw), OneTimeToken.purpose == purpose)
            .with_for_update()
        )
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise AuthError("This link is invalid or has expired.", status=400)
        token.used_at = now
        return token

    def reset_password(self, *, token: str, new_password: str, ip: str | None) -> None:
        record = self._consume_token(token, "PASSWORD_RESET")
        user = self.db.get(User, record.user_id)
        if user is None:
            raise AuthError("This link is invalid or has expired.", status=400)
        user.password_hash = security.hash_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        self.revoke_all_sessions(user.id)
        record_audit(self.db, action="auth.password_reset", actor_user_id=user.id, ip=ip)
        self.db.commit()

    def verify_email(self, *, token: str, ip: str | None) -> None:
        record = self._consume_token(token, "EMAIL_VERIFY")
        user = self.db.get(User, record.user_id)
        if user is not None:
            user.email_verified = True
            record_audit(self.db, action="auth.email_verified", actor_user_id=user.id, ip=ip)
        self.db.commit()

    # ----------------------------------------------------------- validation
    def session_is_valid(self, session_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> bool:
        session = self.db.get(UserSession, session_id)
        return bool(session and session.user_id == user_id and session.revoked_at is None and session.expires_at > now)
