
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.notification import Notification

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Notification).where(
        Notification.user_id == current_user.id
    )

    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))

    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    notifications = result.scalars().all()

    return {
        "items": [
            {
                "id": str(item.id),
                "category_id": str(item.category_id),
                "month": item.month.isoformat(),
                "level": item.level,
                "title": item.title,
                "message": item.message,
                "is_read": item.is_read,
                "created_at": item.created_at.isoformat(),
            }
            for item in notifications
        ],
        "count": len(notifications),
    }


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .values(is_read=True)
        .returning(Notification.id)
    )

    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOTIFICATION_NOT_FOUND",
                "message": "Notification not found.",
            },
        )

    await db.commit()
    return {"message": "Notification marked as read."}
