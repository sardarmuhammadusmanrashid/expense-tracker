
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.category import Category
from app.models.expense import Expense
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseResponse


from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Response,
    status,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.category import Category
from app.models.expense import Expense
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseResponse, ExpenseUpdate


from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import Query
from fastapi import Response

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import Header
from fastapi.responses import JSONResponse
from sqlalchemy.dialects.postgresql import insert

from app.models.idempotency import IdempotencyRecord
from app.models.outbox import OutboxEvent
from uuid import uuid4

from fastapi import Body, Query

from app.services import storage
router = APIRouter(prefix="/expenses", tags=["Expenses"])





# @router.post(
#     "",
#     response_model=ExpenseResponse,
#     status_code=status.HTTP_201_CREATED,
# )
# async def create_expense(
#     payload: ExpenseCreate,
#     db: AsyncSession = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ) -> Expense:
#     # Verify that the category belongs to the logged-in user.
#     category_result = await db.execute(
#         select(Category).where(
#             Category.id == payload.category_id,
#             Category.user_id == current_user.id,
#         )
#     )
#     category = category_result.scalar_one_or_none()

#     if category is None:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail={
#                 "code": "CATEGORY_NOT_FOUND",
#                 "message": "Category not found.",
#             },
#         )

#     expense = Expense(
#         user_id=current_user.id,
#         category_id=payload.category_id,
#         amount=payload.amount,
#         currency=payload.currency,
#         description=payload.description,
#         spent_on=payload.spent_on,
#     )

#     db.add(expense)

#     try:
#         await db.commit()
#         await db.refresh(expense)
#     except Exception:
#         await db.rollback()
#         raise

#     return expense


def queue_budget_check(
    db,
    user_id,
    category_id,
    spent_on,
):
    db.add(
        OutboxEvent(
            event_type="expense.changed",
            payload={
                "user_id": str(user_id),
                "category_id": str(category_id),
                "month": spent_on.replace(day=1).isoformat(),
            },
        )
    )

@router.get("")
async def list_expenses(
    category_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: Decimal | None = Query(default=None, ge=0),
    max_amount: Decimal | None = Query(default=None, ge=0),
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    ),
    q: str | None = Query(default=None, max_length=200),
    cursor_spent_on: date | None = None,
    cursor_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # A cursor must contain both values or neither.
    if (cursor_spent_on is None) != (cursor_id is None):
        raise HTTPException(
            status_code=422,
            detail="Both cursor_spent_on and cursor_id are required together.",
        )

    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from cannot be after date_to.",
        )

    if min_amount is not None and max_amount is not None:
        if min_amount > max_amount:
            raise HTTPException(
                status_code=422,
                detail="min_amount cannot exceed max_amount.",
            )

    stmt = select(Expense).where(Expense.user_id == current_user.id)

    if category_id is not None:
        stmt = stmt.where(Expense.category_id == category_id)

    if date_from is not None:
        stmt = stmt.where(Expense.spent_on >= date_from)

    if date_to is not None:
        stmt = stmt.where(Expense.spent_on <= date_to)

    if min_amount is not None:
        stmt = stmt.where(Expense.amount >= min_amount)

    if max_amount is not None:
        stmt = stmt.where(Expense.amount <= max_amount)

    if currency is not None:
        stmt = stmt.where(Expense.currency == currency)

    if q is not None and q.strip():
        stmt = stmt.where(Expense.description.ilike(f"%{q.strip()}%"))

    # Keyset pagination: newest date first, then highest UUID first.
    if cursor_spent_on is not None and cursor_id is not None:
        stmt = stmt.where(
            (Expense.spent_on < cursor_spent_on)
            | (
                (Expense.spent_on == cursor_spent_on)
                & (Expense.id < cursor_id)
            )
        )

    stmt = stmt.order_by(
        Expense.spent_on.desc(),
        Expense.id.desc(),
    ).limit(limit + 1)

    result = await db.execute(stmt)
    expenses = list(result.scalars().all())

    has_more = len(expenses) > limit
    expenses = expenses[:limit]

    next_cursor = None
    if has_more and expenses:
        last_expense = expenses[-1]
        next_cursor = {
            "cursor_spent_on": last_expense.spent_on.isoformat(),
            "cursor_id": str(last_expense.id),
        }

    return {
        "items": [
            ExpenseResponse.model_validate(expense).model_dump(mode="json")
            for expense in expenses
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.get("/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Expense:
    result = await db.execute(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.user_id == current_user.id,
        )
    )
    expense = result.scalar_one_or_none()

    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "EXPENSE_NOT_FOUND",
                "message": "Expense not found.",
            },
        )

    response.headers["ETag"] = f'"{expense.version}"'

    return expense



@router.patch(
    "/{expense_id}",
    response_model=ExpenseResponse,
)
async def update_expense(
    expense_id: UUID,
    payload: ExpenseUpdate,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Expense:
    # If-Match is mandatory.
    if if_match is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "PRECONDITION_REQUIRED",
                "message": "If-Match header is required.",
            },
        )

    # Our ETag format is a quoted integer, for example: "1".
    try:
        expected_version = int(if_match.strip('"'))
        if expected_version < 1:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_ETAG",
                "message": 'If-Match must contain a version such as "1".',
            },
        )

    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EMPTY_UPDATE",
                "message": "Provide at least one field to update.",
            },
        )

    # Required database fields cannot be explicitly set to null.
    for field in ("category_id", "amount", "currency", "spent_on"):
        if field in changes and changes[field] is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_FIELD",
                    "message": f"{field} cannot be null.",
                },
            )

    # If changing the category, it must belong to this user.
    if changes.get("category_id") is not None:
        category_result = await db.execute(
            select(Category.id).where(
                Category.id == changes["category_id"],
                Category.user_id == current_user.id,
            )
        )

        if category_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "CATEGORY_NOT_FOUND",
                    "message": "Category not found.",
                },
            )
    old_result = await db.execute(
    select(Expense.category_id, Expense.spent_on).where(
        Expense.id == expense_id,
        Expense.user_id == current_user.id,
        Expense.version == expected_version,
    )
    )
    old_expense = old_result.one_or_none()
    # The version check and update happen atomically in ONE SQL statement.
    stmt = (
        update(Expense)
        .where(
            Expense.id == expense_id,
            Expense.user_id == current_user.id,
            Expense.version == expected_version,
        )
        .values(
            **changes,
            version=Expense.version + 1,
            updated_at=func.now(),
        )
        .returning(Expense)
    )

    result = await db.execute(stmt)
    expense = result.scalar_one_or_none()

    if expense is None:
        # Determine whether the expense is missing or its version is stale.
        existing_result = await db.execute(
            select(Expense.id, Expense.version).where(
                Expense.id == expense_id,
                Expense.user_id == current_user.id,
            )
        )
        existing = existing_result.one_or_none()

        await db.rollback()

        if existing is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "EXPENSE_NOT_FOUND",
                    "message": "Expense not found.",
                },
            )

        raise HTTPException(
            status_code=412,
            detail={
                "code": "VERSION_CONFLICT",
                "message": "The expense has changed. Fetch it again before updating.",
            },
        )
    # Recheck the old category and month.
    if old_expense is not None:
        queue_budget_check(
            db,
            current_user.id,
            old_expense.category_id,
            old_expense.spent_on,
        )

    # Recheck the updated category and month.
    queue_budget_check(
        db,
        current_user.id,
        expense.category_id,
        expense.spent_on,
    )

    await db.commit()

    response.headers["ETag"] = f'"{expense.version}"'
    return expense




@router.delete(
    "/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_expense(
    expense_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    stmt = (
        delete(Expense)
        .where(
            Expense.id == expense_id,
            Expense.user_id == current_user.id,
        )
        .returning(
            Expense.id,
            Expense.category_id,
            Expense.spent_on,
            Expense.receipt_key,
        )
    )
    result = await db.execute(stmt)
    deleted = result.one_or_none()

    if deleted is None:
        await db.rollback()
        raise HTTPException(
            status_code=404,
            detail={
                "code": "EXPENSE_NOT_FOUND",
                "message": "Expense not found.",
            },
        )


    queue_budget_check(
    db,
    current_user.id,
    deleted.category_id,
    deleted.spent_on,
    )
    if deleted.receipt_key:
        db.add(
            OutboxEvent(
                event_type="receipt.delete",
                payload={"receipt_key": deleted.receipt_key},
            )
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/", response_model=ExpenseResponse, status_code=201)
async def create_expense(
    payload: ExpenseCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)

    request_data = payload.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(
            request_data,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    try:
        # Replay an existing response if the key is still valid.
        existing_result = await db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == current_user.id,
                IdempotencyRecord.key == idempotency_key,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            if existing.expires_at <= now:
                await db.delete(existing)
                await db.flush()
            else:
                if existing.request_hash != request_hash:
                    await db.rollback()
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "IDEMPOTENCY_KEY_REUSED",
                            "message": "This key was already used with a different request body.",
                        },
                    )

                saved_body = existing.response_body
                saved_status = existing.response_status
                await db.rollback()
                return JSONResponse(
                    content=saved_body,
                    status_code=saved_status,
                )

        # Confirm that the category belongs to this user.
        category_result = await db.execute(
            select(Category.id).where(
                Category.id == payload.category_id,
                Category.user_id == current_user.id,
            )
        )

        if category_result.scalar_one_or_none() is None:
            await db.rollback()
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "CATEGORY_NOT_FOUND",
                    "message": "Category not found.",
                },
            )

        # Create the expense inside the same transaction as its key record.
        expense = Expense(
            user_id=current_user.id,
            category_id=payload.category_id,
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            spent_on=payload.spent_on,
        )
        db.add(expense)

        await db.flush()

        queue_budget_check(
            db,
            current_user.id,
            expense.category_id,
            expense.spent_on,
        )

        # Continue with your existing idempotency record code below

        response_body = ExpenseResponse.model_validate(
            expense
        ).model_dump(mode="json")

        # The unique constraint handles simultaneous requests with the same key.
        statement = (
            insert(IdempotencyRecord)
            .values(
                user_id=current_user.id,
                key=idempotency_key,
                request_hash=request_hash,
                response_status=201,
                response_body=response_body,
                created_at=now,
                expires_at=now + timedelta(hours=24),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecord.user_id,
                    IdempotencyRecord.key,
                ]
            )
            .returning(IdempotencyRecord.id)
        )

        inserted = await db.execute(statement)
        record_id = inserted.scalar_one_or_none()

        if record_id is None:
            # Another request won the race. Roll back our expense.
            await db.rollback()

            retry_result = await db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == current_user.id,
                    IdempotencyRecord.key == idempotency_key,
                )
            )
            existing = retry_result.scalar_one_or_none()

            if existing is None:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency conflict. Please retry the request.",
                )

            if existing.request_hash != request_hash:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": "This key was used with a different request body.",
                    },
                )

            return JSONResponse(
                content=existing.response_body,
                status_code=existing.response_status,
            )

        await db.commit()
        return response_body

    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise





RECEIPT_PREFIX = "receipts"


@router.post("/{expense_id}/receipt/upload-url")
async def create_receipt_upload_url(
    expense_id: UUID,
    content_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if content_type not in storage.ALLOWED_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Only JPG, PNG, and PDF receipts are allowed.",
        )

    result = await db.execute(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.user_id == current_user.id,
        )
    )
    expense = result.scalar_one_or_none()

    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found.")

    extension = storage.ALLOWED_TYPES[content_type][0]

    key = (
        f"receipts/{current_user.id}/"
        f"{expense.id}/{uuid4()}{extension}"
    )

    try:
        upload = await storage.create_upload(key, content_type)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Receipt storage is temporarily unavailable.",
        )

    return {
        "upload_url": upload["url"],
        "fields": upload["fields"],
        "receipt_key": key,
        "max_size_bytes": storage.MAX_RECEIPT_SIZE,
        "expires_in_seconds": 600,
    }



@router.post("/{expense_id}/receipt/confirm")
async def confirm_receipt_upload(
    expense_id: UUID,
    receipt_key: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.user_id == current_user.id,
        )
    )
    expense = result.scalar_one_or_none()

    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found.")

    expected_prefix = f"receipts/{current_user.id}/{expense.id}/"

    if not receipt_key.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="Invalid receipt key.")

    # Only allow one filename after the expected directory.
    filename = receipt_key[len(expected_prefix):]

    if "/" in filename or not filename:
        raise HTTPException(status_code=400, detail="Invalid receipt key.")

    extension = "." + filename.rsplit(".", 1)[-1].lower()

    extension_to_type = {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".pdf": "application/pdf",
    }

    expected_type = extension_to_type.get(extension)

    if expected_type is None:
        raise HTTPException(status_code=422, detail="Unsupported receipt type.")

    # Ensure the filename contains a valid UUID.
    try:
        UUID(filename[: -len(extension)])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid receipt filename.")

    try:
        verified_extension = await storage.verify_receipt(
            receipt_key,
            expected_type,
        )

        if verified_extension != extension:
            raise HTTPException(
                status_code=422,
                detail="Receipt extension does not match its content.",
            )

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not verify the uploaded receipt.",
        )

    old_key = expense.receipt_key
    expense.receipt_key = receipt_key

    if old_key and old_key != receipt_key:
        db.add(
            OutboxEvent(
                event_type="receipt.delete",
                payload={"receipt_key": old_key},
            )
        )

    await db.commit()

    return {
        "message": "Receipt uploaded successfully.",
        "receipt_key": receipt_key,
    }


@router.get("/{expense_id}/receipt")
async def get_receipt_download_url(
    expense_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.user_id == current_user.id,
        )
    )
    expense = result.scalar_one_or_none()

    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found.")

    if not expense.receipt_key:
        raise HTTPException(status_code=404, detail="No receipt attached.")

    try:
        url = await storage.create_download_url(expense.receipt_key)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Receipt storage is temporarily unavailable.",
        )

    return {
        "download_url": url,
        "expires_in_seconds": 900,
    }



