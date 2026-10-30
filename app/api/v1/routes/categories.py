from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse

from datetime import date
from decimal import Decimal

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.category import Category
from app.models.expense import Expense
from app.models.user import User
from app.schemas.category import CategoryResponse

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Category:
    name = payload.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_CATEGORY_NAME",
                "message": "Category name cannot be empty.",
            },
        )

    # Check for a duplicate belonging to this user.
    result = await db.execute(
        select(Category).where(
            Category.user_id == current_user.id,
            Category.name == name,
        )
    )
    existing_category = result.scalar_one_or_none()

    if existing_category:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CATEGORY_ALREADY_EXISTS",
                "message": "You already have a category with this name.",
            },
        )

    category = Category(
        user_id=current_user.id,
        name=name,
        monthly_budget=payload.monthly_budget,
    )

    db.add(category)

    try:
        await db.commit()
        await db.refresh(category)
    except IntegrityError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CATEGORY_ALREADY_EXISTS",
                "message": "You already have a category with this name.",
            },
        )

    category_data = {
    column.name: getattr(category, column.name)
    for column in Category.__table__.columns
    }

    # A newly created category has no expenses yet.
    spent_this_month = Decimal("0.00")

    category_data["spent_this_month"] = spent_this_month

    category_data["remaining_budget"] = (
        category.monthly_budget - spent_this_month
        if category.monthly_budget is not None
        else None
    )

    return category_data





@router.get("/", response_model=list[CategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    today = date.today()
    month_start = today.replace(day=1)

    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)

    spent_subquery = (
        select(
            Expense.category_id.label("category_id"),
            func.coalesce(func.sum(Expense.amount), 0)
            .label("spent_this_month"),
        )
        .where(
            Expense.user_id == current_user.id,
            Expense.spent_on >= month_start,
            Expense.spent_on < next_month,
        )
        .group_by(Expense.category_id)
        .subquery()
    )

    query = (
        select(
            Category,
            func.coalesce(
                spent_subquery.c.spent_this_month, Decimal("0.00")
            ).label("spent_this_month"),
        )
        .outerjoin(
            spent_subquery,
            Category.id == spent_subquery.c.category_id,
        )
        .where(Category.user_id == current_user.id)
        .order_by(Category.created_at.desc())
    )

    result = await db.execute(query)
    rows = result.all()

    response = []

    for category, spent in rows:
        budget = category.monthly_budget

        response.append(
            {
                "id": category.id,
                "name": category.name,
                "monthly_budget": budget,
                "created_at": category.created_at,
                "spent_this_month": spent,
                "remaining_budget": (
                    budget - spent if budget is not None else None
                ),
            }
        )

    return response


