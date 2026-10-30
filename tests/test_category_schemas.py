from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.category import CategoryCreate


def test_category_accepts_valid_data():
    category = CategoryCreate(
        name="Groceries",
        monthly_budget="5000.00",
    )

    assert category.name == "Groceries"
    assert category.monthly_budget == Decimal("5000.00")


def test_category_allows_no_budget():
    category = CategoryCreate(name="Transport")

    assert category.monthly_budget is None


def test_category_rejects_empty_name():
    with pytest.raises(ValidationError):
        CategoryCreate(name="")


def test_category_rejects_zero_budget():
    with pytest.raises(ValidationError):
        CategoryCreate(
            name="Groceries",
            monthly_budget="0",
        )


def test_category_rejects_negative_budget():
    with pytest.raises(ValidationError):
        CategoryCreate(
            name="Groceries",
            monthly_budget="-100",
        )