
import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.outbox import OutboxEvent
from app.services.budget_alerts import check_category_budget
from app.services.storage import delete_object


async def process_one_event(session: AsyncSession) -> bool:
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.status == "pending",
            OutboxEvent.available_at <= now,
        )
        .order_by(OutboxEvent.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )

    event = result.scalar_one_or_none()

    if event is None:
        return False

    event_id = event.id
    event_type = event.event_type
    payload = dict(event.payload)
    attempt_number = event.attempts + 1

    try:
        if event_type == "expense.changed":
            await check_category_budget(
                session,
                user_id=payload["user_id"],
                category_id=payload["category_id"],
                month=date.fromisoformat(payload["month"]),
            )

        elif event_type == "receipt.delete":
            await delete_object(payload["receipt_key"])

        else:
            raise ValueError(f"Unsupported event type: {event_type}")

        event.attempts = attempt_number
        event.status = "processed"
        event.processed_at = datetime.now(timezone.utc)
        event.last_error = None

        await session.commit()

    except Exception as exc:
        await session.rollback()

        retry_result = await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .with_for_update()
        )

        retry_event = retry_result.scalar_one_or_none()

        if retry_event is not None and retry_event.status == "pending":
            retry_event.attempts = max(
                retry_event.attempts,
                attempt_number,
            )
            retry_event.last_error = str(exc)[:2000]

            if retry_event.attempts >= 5:
                retry_event.status = "failed"
            else:
                retry_event.available_at = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=2 ** retry_event.attempts)
                )

            await session.commit()

    return True


async def main():
    while True:
        async with AsyncSessionLocal() as session:
            found = await process_one_event(session)

        if not found:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
