import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, RegisterRequest


def test_register_request_accepts_valid_data():
    request = RegisterRequest(
        email="user@example.com",
        password="StrongPassword123!",
    )

    assert request.email == "user@example.com"
    assert request.password == "StrongPassword123!"
    assert request.base_currency == "PKR"


def test_register_request_rejects_short_password():
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            password="short",
        )


def test_register_request_rejects_invalid_email():
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="not-an-email",
            password="StrongPassword123!",
        )


def test_login_request_accepts_valid_data():
    request = LoginRequest(
        email="user@example.com",
        password="StrongPassword123!",
    )

    assert request.email == "user@example.com"
    assert request.password == "StrongPassword123!"