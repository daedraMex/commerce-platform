import pytest
from django.contrib.auth import get_user_model

from apps.stores.models import Store


@pytest.fixture
def admin_client_by_email(client):
    get_user_model().objects.create_superuser(email="owner@example.com", password="s3cret-pass")
    client.post(
        "/admin/login/",
        {"username": "owner@example.com", "password": "s3cret-pass"},
    )
    return client


@pytest.fixture
def user():
    return get_user_model().objects.create_user(email="staff@example.com")


@pytest.fixture
def store():
    return Store.objects.create(slug="home", name="Home")
