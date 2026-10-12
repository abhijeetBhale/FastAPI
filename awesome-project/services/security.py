"""Password hashing and session tokens.

Passwords use PBKDF2-HMAC-SHA256 from the standard library. Argon2id or bcrypt
would be preferable, but both need a compiled dependency; PBKDF2 with a high
iteration count is an acceptable, dependency-free choice here. The digest format
stores the algorithm, iteration count and salt alongside the hash, so the work
factor can be raised later without invalidating existing passwords.

Tokens are JWTs carried in an httpOnly cookie. httpOnly matters: it means
JavaScript cannot read the token, so an XSS bug cannot exfiltrate a session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models.user import User

# ---- password hashing ------------------------------------------------------- #

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 260_000
SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`."""
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return "$".join(
        [
            ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time comparison. Returns False for unset or malformed hashes."""
    if not stored:
        return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt_b64),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    # hmac.compare_digest avoids leaking the match position through timing.
    return hmac.compare_digest(candidate, expected)


# ---- password strength ------------------------------------------------------ #

#: Short passwords that pass a naive length check but are trivially guessable.
COMMON_PASSWORDS = {
    "password", "password1", "12345678", "123456789", "qwerty123",
    "qwerty12", "qwertyui", "letmein1", "welcome1", "admin123",
    "abc12345", "passw0rd", "11111111", "iloveyou", "sunshine1",
    "monkey123", "football", "baseball", "trustno1", "dragon12",
}


def password_problems(password: str) -> list[str]:
    """Return a list of human-readable problems; empty means acceptable."""
    problems: list[str] = []
    if len(password) < 8:
        problems.append("must be at least 8 characters")
    if len(password) > 128:
        problems.append("must be at most 128 characters")
    if password and not any(c.isalpha() for c in password):
        problems.append("must contain a letter")
    if password and not any(c.isdigit() for c in password):
        problems.append("must contain a digit")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("is too common — choose something less predictable")
    return problems


# ---- tokens ----------------------------------------------------------------- #

COOKIE_NAME = "session_token"


def create_access_token(user: User, *, expires_hours: int = 12) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        # A per-token id, so a specific session can be revoked by record.
        "jti": secrets.token_urlsafe(8),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session."
        )


def set_session_cookie(response, token: str, *, expires_hours: int = 12) -> None:
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=expires_hours * 3600,
        httponly=True,          # unreadable from JavaScript
        samesite="strict",      # not sent on cross-site requests
        secure=settings.cookie_secure,  # HTTPS-only in production
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


# ---- current-user dependency ------------------------------------------------ #

#: Declared so OpenAPI emits a `bearerAuth` security scheme, which is what gives
#: Swagger UI its "Authorize" button. Without it /docs offers no way to sign in.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description=(
        "Paste the `session_token` JWT from POST /auth/login's Set-Cookie "
        "header. The browser portal uses the httpOnly cookie instead and needs "
        "nothing here."
    ),
)


def get_current_user(
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the signed-in user, or raise 401.

    Two credentials are accepted, carrying the identical JWT:

    * the httpOnly session cookie — used by the portal,
    * `Authorization: Bearer <jwt>` — used by Swagger UI, curl and scripts,
      because Swagger's Authorize button cannot hold a cookie.

    The bearer form is checked second so an existing cookie keeps working
    unchanged.
    """
    raw = token
    if not raw and credentials and credentials.scheme.lower() == "bearer":
        raw = credentials.credentials

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in.",
        )

    payload = decode_access_token(raw)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session."
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is no longer active.",
        )
    return user


def require_current_user(user: User = Depends(get_current_user)) -> User:
    """Explicit alias, used by the portal routes."""
    return user