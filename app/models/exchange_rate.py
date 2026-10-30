from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Date,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    __table_args__ = (
        UniqueConstraint(
            "currency",
            "valid_on",
            name="uq_exchange_rates_currency_valid_on",
        ),
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        primary_key=True,
        nullable=False,
    )

    valid_on: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
        nullable=False,
    )

    rate_to_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )