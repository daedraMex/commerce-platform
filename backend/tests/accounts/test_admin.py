import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client_by_email(client):
    get_user_model().objects.create_superuser(
        email="owner@example.com", password="s3cret-pass"
    )
    client.post(
        "/admin/login/",
        {"username": "owner@example.com", "password": "s3cret-pass"},
    )
    return client


def test_superuser_logs_into_the_admin_with_email(admin_client_by_email):
    response = admin_client_by_email.get("/admin/")

    assert response.status_code == 200


def test_admin_creates_a_user_with_email(admin_client_by_email):
    response = admin_client_by_email.post(
        "/admin/accounts/user/add/",
        {
            "email": "staff@example.com",
            "password1": "Long-enough-pass-123",
            "password2": "Long-enough-pass-123",
            "usable_password": "true",
        },
    )

    assert response.status_code == 302
    assert get_user_model().objects.filter(email="staff@example.com").exists()
