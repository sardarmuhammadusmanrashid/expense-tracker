
import asyncio
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert

from app.db.session import AsyncSessionLocal
from app.models.exchange_rate import ExchangeRate

# Illustrative development rates: units of currency per 1 USD.
# Replace these with verified historical rates before final submission.
SAMPLE_RATES = {
    "USD": Decimal("1.00000000"),
    "PKR": Decimal("280.00000000"),
    "AED": Decimal("3.67250000"),
    "EUR": Decimal("0.92000000"),
}


async def seed_exchange_rates() -> None:
    today = date.today()
    rows = []

    for days_ago in range(89, -1, -1):
        valid_on = today - timedelta(days=days_ago)

        for currency, rate in SAMPLE_RATES.items():
            rows.append(
                {
                    "currency": currency,
                    "valid_on": valid_on,
                    "rate_to_usd": rate,
                }
            )

    async with AsyncSessionLocal() as session:
        statement = (
            insert(ExchangeRate)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    ExchangeRate.currency,
                    ExchangeRate.valid_on,
                ]
            )
        )

        result = await session.execute(statement)
        await session.commit()

        print(f"Seed completed. Rows inserted: {result.rowcount}")


if __name__ == "__main__":
    asyncio.run(seed_exchange_rates())




# python -m app.scripts.seed_exchange_rates