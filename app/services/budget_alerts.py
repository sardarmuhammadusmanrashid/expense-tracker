
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.expense import Expense
from app.models.notification import Notification


async def check_category_budget(
    db: AsyncSession,
    user_id,
    category_id,
    month: date,
) -> None:
    """Create notifications when monthly spending crosses 80% or 100%."""
    month_start = month.replace(day=1)

    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)

    category_result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            Category.user_id == user_id,
        )
    )
    category = category_result.scalar_one_or_none()

    if category is None or category.monthly_budget is None:
        return

    budget = Decimal(category.monthly_budget)

    if budget <= 0:
        return

    spending_result = await db.execute(
        select(Expense.amount, Expense.currency).where(
            Expense.user_id == user_id,
            Expense.category_id == category_id,
            Expense.spent_on >= month_start,
            Expense.spent_on < next_month,
        )
    )

    # This first version assumes expenses for a category use the same currency.
    # Currency conversion will be added before final submission.
    amounts = spending_result.all()

    if not amounts:
        spent = Decimal("0.00")
    else:
        currencies = {currency for _, currency in amounts}
        if len(currencies) != 1:
            raise ValueError(
                "Budget calculation requires expenses in one currency per category."
            )
        spent = sum(
            (Decimal(amount) for amount, _ in amounts),
            Decimal("0.00"),
        )

    percentage = spent / budget * 100

    for level, threshold in ((80, Decimal("80")), (100, Decimal("100"))):
        if percentage < threshold:
            continue

        title = (
            "Budget limit reached"
            if level == 100
            else "Budget getting close"
        )
        message = (
            f"{category.name}: spending is {percentage:.2f}% "
            f"of the monthly budget."
        )

        statement = (
            insert(Notification)
            .values(
                user_id=user_id,
                category_id=category_id,
                month=month_start,
                level=level,
                title=title,
                message=message,
                is_read=False,
            )
            .on_conflict_do_nothing(
                constraint="uq_notification_budget_level"
            )
        )
        await db.execute(statement)
