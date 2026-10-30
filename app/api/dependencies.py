from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials

    # Decode and validate the access token.
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "ACCESS_TOKEN_EXPIRED",
                "message": "Access token has expired.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_ACCESS_TOKEN",
                "message": "Access token is invalid.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Make sure this is an access token, not a refresh token.
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_ACCESS_TOKEN",
                "message": "An access token is required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_ACCESS_TOKEN",
                "message": "Token subject is missing.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate that the subject is a UUID.
    try:
        user_uuid = UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_ACCESS_TOKEN",
                "message": "Token subject is invalid.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load the user from the database.
    result = await db.execute(
        select(User).where(User.id == user_uuid)
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_ACCESS_TOKEN",
                "message": "User associated with token no longer exists.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user