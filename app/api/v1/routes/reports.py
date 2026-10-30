
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.expense import Expense
from app.models.category import Category
from app.services.exchange_rates import convert_to_currency
from uuid import UUID
router = APIRouter(prefix="/reports", tags=["Reports"])

PERCENT_QUANTUM = Decimal("0.01")


def calculate_percent(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


@router.get("/monthly")
async def monthly_report(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report_currency = (currency or current_user.base_currency).upper()

    start_date = date(year, month, 1)

    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    if month == 1:
        previous_start = date(year - 1, 12, 1)
    else:
        previous_start = date(year, month - 1, 1)

    expenses_result = await db.execute(
        select(
            Expense,
            Category.id,
            Category.name,
            Category.monthly_budget,
        )
        .join(Category, Expense.category_id == Category.id)
        .where(
            Expense.user_id == current_user.id,
            Expense.spent_on >= previous_start,
            Expense.spent_on < end_date,
        )
        .order_by(Expense.spent_on, Expense.id)
    )

    rows = expenses_result.all()

    current_total = Decimal("0.00")
    previous_total = Decimal("0.00")

    # Key categories by ID, not name.
    category_totals: dict[UUID, dict] = {}

    for expense, category_id, category_name, monthly_budget in rows:
        converted = await convert_to_currency(
            db=db,
            amount=expense.amount,
            source_currency=expense.currency,
            target_currency=report_currency,
            on_date=expense.spent_on,
        )

        if expense.spent_on >= start_date:
            current_total += converted

            if category_id not in category_totals:
                category_totals[category_id] = {
                    "category": category_name,
                    "spent": Decimal("0.00"),
                    "budget": monthly_budget,
                }

            category_totals[category_id]["spent"] += converted
        else:
            previous_total += converted

    categories = []

    for category_id, data in category_totals.items():
        spent = data["spent"]
        budget = data["budget"]

        # Category budgets are assumed to be in the user's base currency.
        # Convert them to the report currency for a meaningful comparison.
        converted_budget = None

        if budget is not None:
            converted_budget = await convert_to_currency(
                db=db,
                amount=budget,
                source_currency=current_user.base_currency,
                target_currency=report_currency,
                on_date=start_date,
            )

        budget_used_percent = None

        if converted_budget is not None and converted_budget > 0:
            budget_used_percent = calculate_percent(
                spent / converted_budget * Decimal("100")
            )

        categories.append(
            {
                "category_id": str(category_id),
                "category": data["category"],
                "spent": spent,
                "budget": converted_budget,
                "budget_used_percent": budget_used_percent,
            }
        )

    change_percent = None

    if previous_total > 0:
        change_percent = calculate_percent(
            (current_total - previous_total)
            / previous_total
            * Decimal("100")
        )

    return {
        "year": year,
        "month": month,
        "currency": report_currency,
        "total_spent": current_total,
        "previous_month_spent": previous_total,
        "change_percent": change_percent,
        "categories": categories,
    }
