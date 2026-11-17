from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import StrictModel

PASSWORD_MIN = 12
PASSWORD_MAX = 128

# Tiny blocklist of the most common choices. A real deployment should use a breached-password check.
_COMMON_PASSWORDS = {
    "password1234", "password12345", "123456789012", "qwertyuiop12", "administrator", "welcome12345",
    "letmein12345", "iloveyou1234", "changeme1234", "queuecare1234", "passw0rd1234", "abcd12345678",
}


def validate_password_strength(password: str, *, email: str | None = None) -> str:
    if not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        raise ValueError(f"Password must be between {PASSWORD_MIN} and {PASSWORD_MAX} characters")
    if not password.strip():
        raise ValueError("Password cannot be blank")
    if len(set(password)) < 5:
        raise ValueError("Password is too repetitive")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common")
    if email:
        local = email.split("@", 1)[0].lower()
        if len(local) >= 4 and local in password.lower():
            raise ValueError("Password must not contain your email name")
    return password


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str = Field(max_length=PASSWORD_MAX + 64)
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=32, pattern=r"^[0-9+()\- ]{6,32}$")

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str, info: object) -> str:
        return validate_password_strength(value)

    def check_password_against_email(self) -> None:
        validate_password_strength(self.password, email=str(self.email))


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX + 64)


class ForgotPasswordRequest(StrictModel):
    email: EmailStr


class ResetPasswordRequest(StrictModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _strength(cls, value: str) -> str:
        return validate_password_strength(value)


class VerifyEmailRequest(StrictModel):
    token: str = Field(min_length=20, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    email_verified: bool
    platform_role: str


class MembershipOut(BaseModel):
    clinic_id: uuid.UUID
    role: str


class AuthResponse(BaseModel):
    user: UserOut
    csrf_token: str


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
    csrf_token: str | None


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool
