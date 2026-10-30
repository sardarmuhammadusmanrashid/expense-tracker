
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exchange_rate import ExchangeRate


async def get_rate_to_usd(
    db: AsyncSession,
    currency: str,
    on_date: date,
) -> Decimal:
    result = await db.execute(
        select(ExchangeRate.rate_to_usd)
        .where(
            ExchangeRate.currency == currency.upper(),
            ExchangeRate.valid_on <= on_date,
        )
        .order_by(ExchangeRate.valid_on.desc())
        .limit(1)
    )

    rate = result.scalar_one_or_none()

    if rate is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EXCHANGE_RATE_NOT_FOUND",
                "message": f"No rate found for {currency} on or before {on_date}.",
            },
        )

    if rate <= 0:
        raise HTTPException(status_code=500, detail="Invalid exchange rate.")

    return rate


async def convert_to_currency(
    db: AsyncSession,
    amount: Decimal,
    source_currency: str,
    target_currency: str,
    on_date: date,
) -> Decimal:
    source = source_currency.upper()
    target = target_currency.upper()

    if source == target:
        return amount.quantize(Decimal("0.01"))

    source_rate = await get_rate_to_usd(db, source, on_date)
    target_rate = await get_rate_to_usd(db, target, on_date)

    converted = (amount / source_rate) * target_rate

    return converted.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
