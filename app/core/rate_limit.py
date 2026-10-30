import hashlib

from redis.asyncio import Redis

from app.core.config import settings

LOGIN_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60

redis_client = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
)


def get_login_key(email: str) -> str:
    """Create a Redis key without storing the raw email."""
    normalized_email = email.strip().lower()
    email_hash = hashlib.sha256(
        normalized_email.encode("utf-8")
    ).hexdigest()

    return f"login_failures:{email_hash}"


async def check_login_rate_limit(email: str) -> None:
    """Reject login requests after five failed attempts."""
    key = get_login_key(email)

    attempts = await redis_client.get(key)

    if attempts is not None and int(attempts) >= LOGIN_LIMIT:
        ttl = await redis_client.ttl(key)

        # A missing or expired TTL should not produce a negative
        # Retry-After value.
        retry_after = max(ttl, 1)

        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "LOGIN_RATE_LIMIT_EXCEEDED",
                "message": "Too many failed login attempts. Try again later.",
            },
            headers={"Retry-After": str(retry_after)},
        )


async def record_failed_login(email: str) -> None:
    """Atomically increment the failed-login counter."""
    key = get_login_key(email)

    # Increment and set the 15-minute expiration atomically.
    script = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    return count
    """

    await redis_client.eval(
        script,
        1,
        key,
        LOGIN_WINDOW_SECONDS,
    )


async def reset_failed_logins(email: str) -> None:
    """Clear failed attempts after successful authentication."""
    key = get_login_key(email)
    await redis_client.delete(key)