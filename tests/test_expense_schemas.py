
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.expense import ExpenseCreate, ExpenseUpdate


def test_expense_create_valid_data():
    payload = ExpenseCreate(
        category_id=uuid4(),
        amount="1250.50",
        currency="PKR",
        description="Grocery shopping",
        spent_on=date(2026, 10, 29),
    )

    assert payload.amount == Decimal("1250.50")
    assert payload.currency == "PKR"


def test_expense_amount_must_be_positive():
    with pytest.raises(ValidationError):
        ExpenseCreate(
            category_id=uuid4(),
            amount="-100.00",
            currency="PKR",
            spent_on=date(2026, 10, 29),
        )


def test_expense_rejects_invalid_currency():
    with pytest.raises(ValidationError):
        ExpenseCreate(
            category_id=uuid4(),
            amount="100.00",
            currency="pkr",
            spent_on=date(2026, 10, 29),
        )


def test_expense_update_allows_partial_data():
    payload = ExpenseUpdate(amount="500.00")

    assert payload.amount == Decimal("500.00")
    assert payload.category_id is None


def test_expense_update_rejects_zero_amount():
    with pytest.raises(ValidationError):
        ExpenseUpdate(amount="0.00")
