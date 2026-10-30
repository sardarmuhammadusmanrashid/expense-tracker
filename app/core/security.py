from pwdlib import PasswordHash


import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from app.core.config import settings


def create_access_token(user_id: str) -> str:
    """Create a short-lived JWT access token."""
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        ),
    }

    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def create_refresh_token(user_id: str) -> tuple[str, str, str]:
    """
    Create a refresh token.

    Returns:
        token: Encoded JWT refresh token.
        jti: Unique token identifier.
        token_hash: SHA-256 hash of the encoded token.
    """
    now = datetime.now(timezone.utc)
    jti = str(uuid4())

    payload = {
        "sub": user_id,
        "jti": jti,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        ),
    }

    token = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    return token, jti, token_hash



password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plain-text password before storing it."""
    return password_hash.hash(password)
def hash_token(token: str) -> str:
    """Return a SHA-256 hash of a token."""
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """Check a plain-text password against its stored hash."""
    return password_hash.verify(plain_password, hashed_password)