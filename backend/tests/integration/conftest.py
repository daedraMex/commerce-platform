import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def admin_client_by_email(client):
    get_user_model().objects.create_superuser(email="owner@example.com", password="s3cret-pass")
    client.post(
        "/admin/login/",
        {"username": "owner@example.com", "password": "s3cret-pass"},
    )
    return client
