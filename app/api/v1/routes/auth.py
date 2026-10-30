from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import RegisterRequest, UserResponse
from datetime import datetime, timedelta, timezone
from app.api.dependencies import get_current_user
from app.schemas.auth import UserResponse
from fastapi import HTTPException, status
from sqlalchemy import select
from app.core.rate_limit import (
    check_login_rate_limit,
    record_failed_login,
    reset_failed_logins,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.schemas.auth import LoginRequest, TokenResponse


from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
)
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import TokenResponse

import jwt

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_token
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.schemas.auth import LogoutRequest


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    email = str(payload.email).strip().lower()
    # await check_login_rate_limit(email)
    # Check whether this email is already registered.
    result = await db.execute(
        select(User).where(User.email == email)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_ALREADY_REGISTERED",
                "message": "An account with this email already exists.",
            },
        )

    # Create the user with a hashed password.
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        base_currency=payload.base_currency.upper(),
    )

    db.add(user)

    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        # Another request could have registered this email
        # between our check and database commit.
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_ALREADY_REGISTERED",
                "message": "An account with this email already exists.",
            },
        )

    return user



@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login_user(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    email = str(payload.email).strip().lower()
    await check_login_rate_limit(email)
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    # Use the same response for an unknown email and wrong password.
    if user is None or not verify_password(
        payload.password,
        user.password_hash,
    ):
        await record_failed_login(email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Email or password is incorrect.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(str(user.id))

    refresh_token, jti, token_hash = create_refresh_token(
        str(user.id)
    )

    refresh_token_record = RefreshToken(
        user_id=user.id,
        jti=jti,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(refresh_token_record)
    await db.commit()
    await reset_failed_logins(email)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )




@router.post(
    "/refresh",
    response_model=TokenResponse,
)
async def refresh_access_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    # 1. Decode and validate the JWT.
    try:
        payload = jwt.decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "REFRESH_TOKEN_EXPIRED",
                "message": "Refresh token has expired.",
            },
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token is invalid.",
            },
        )

    # 2. Ensure this is a refresh token, not an access token.
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "A refresh token is required.",
            },
        )

    user_id = payload.get("sub")
    jti = payload.get("jti")

    if not user_id or not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token claims are missing.",
            },
        )

    # 3. Lock the token record to prevent concurrent rotation.
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.jti == jti)
        .with_for_update()
    )

    token_record = result.scalar_one_or_none()

    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token is not recognized.",
            },
        )

    # 4. Verify the token belongs to this user and matches its hash.
    if (
        str(token_record.user_id) != user_id
        or token_record.token_hash != hash_token(refresh_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token is invalid.",
            },
        )

    # 5. If an old token is reused, revoke all the user's tokens.
    if token_record.revoked_at is not None:
        result = await db.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == token_record.user_id)
            .with_for_update()
        )

        user_tokens = result.scalars().all()
        now = datetime.now(timezone.utc)

        for user_token in user_tokens:
            if user_token.revoked_at is None:
                user_token.revoked_at = now

        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "REFRESH_TOKEN_REUSED",
                "message": "Refresh token reuse detected. Please log in again.",
            },
        )

    # 6. Check that the database record has not expired.
    now = datetime.now(timezone.utc)

    if token_record.expires_at <= now:
        token_record.revoked_at = now
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "REFRESH_TOKEN_EXPIRED",
                "message": "Refresh token has expired.",
            },
        )

    # 7. Revoke the old token.
    token_record.revoked_at = now

    # 8. Create new access and refresh tokens.
    access_token = create_access_token(user_id)

    new_refresh_token, new_jti, new_token_hash = (
        create_refresh_token(user_id)
    )

    new_token_record = RefreshToken(
        user_id=token_record.user_id,
        jti=new_jti,
        token_hash=new_token_hash,
        expires_at=now
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(new_token_record)

    # 9. Commit old-token revocation and new-token creation together.
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout_user(
    payload: LogoutRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    refresh_token = payload.refresh_token

    # 1. Decode and validate the JWT.
    try:
        token_payload = jwt.decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token is invalid or expired.",
            },
        )

    # 2. Confirm this is a refresh token.
    if token_payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "A refresh token is required.",
            },
        )

    jti = token_payload.get("jti")

    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token identifier is missing.",
            },
        )

    # 3. Find the matching database record.
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.jti == jti)
        .with_for_update()
    )

    token_record = result.scalar_one_or_none()

    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token is not recognized.",
            },
        )

    # 4. Verify the stored hash matches the supplied token.
    if token_record.token_hash != hash_token(refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token is invalid.",
            },
        )

    # 5. Revoke the token if it has not already been revoked.
    if token_record.revoked_at is None:
        token_record.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    # 204 responses must not contain a response body.
    return None




@router.get(
    "/me",
    response_model=UserResponse,
)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user
