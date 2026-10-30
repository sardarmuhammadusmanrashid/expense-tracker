
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExpenseCreate(BaseModel):
    category_id: UUID
    amount: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
    )
    spent_on: date


class ExpenseUpdate(BaseModel):
    category_id: UUID | None = None
    amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
    )
    spent_on: date | None = None


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    amount: Decimal
    currency: str
    description: str | None
    spent_on: date
    version: int
    created_at: datetime
    updated_at: datetime
