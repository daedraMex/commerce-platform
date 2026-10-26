from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

OBTAIN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"

TOKEN_OBTAIN = {
    "email": "ana@example.com",
    "password": "s3cret-pass",
}


@pytest.fixture
def user():
    return get_user_model().objects.create_user(
        email="ana@example.com",
        password="s3cret-pass",
    )


def test_obtain_returns_access_and_refresh_tokens(client, user):
    response = client.post(OBTAIN_URL, TOKEN_OBTAIN, content_type="application/json")

    assert response.status_code == 200
    body = response.json()
    assert body["access"]
    assert body["refresh"]


def test_obtain_matches_email_ignoring_case(client, user):
    credentials = {"email": "Ana@Example.COM", "password": "s3cret-pass"}

    response = client.post(OBTAIN_URL, credentials, content_type="application/json")

    assert response.status_code == 200
    assert response.json()["access"]


def test_obtain_with_wrong_password_returns_invalid_credentials(client, user):
    credentials = {"email": "ana@example.com", "password": "wrong-pass"}

    response = client.post(OBTAIN_URL, credentials, content_type="application/json")

    body = assert_problem_details(response, status=401, code="invalid_credentials")
    assert body["detail"] == "Invalid email or password."


def test_obtain_with_unknown_email_returns_invalid_credentials(client):
    credentials = {"email": "nobody@example.com", "password": "s3cret-pass"}

    response = client.post(OBTAIN_URL, credentials, content_type="application/json")

    assert_problem_details(response, status=401, code="invalid_credentials")


def test_obtain_with_missing_field_returns_validation_error(client):
    credentials = {"email": "ana@example.com"}
    response = client.post(OBTAIN_URL, credentials, content_type="application/json")

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"] == [
        {
            "field": "password",
            "code": "required",
            "detail": "This field is required.",
        }
    ]


def test_refresh_with_valid_token_returns_a_new_access_token(client, user):
    refresh = str(RefreshToken.for_user(user))

    response = client.post(REFRESH_URL, {"refresh": refresh}, content_type="application/json")

    assert response.status_code == 200
    assert response.json()["access"]


def test_refresh_with_invalid_token_returns_token_invalid(client):
    response = client.post(
        REFRESH_URL,
        {"refresh": "not-a-token"},
        content_type="application/json",
    )

    assert_problem_details(response, status=401, code="token_invalid")


def test_refresh_with_expired_token_returns_token_invalid(client, user):
    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=timedelta(seconds=-1))

    response = client.post(
        REFRESH_URL,
        {"refresh": str(refresh)},
        content_type="application/json",
    )

    assert_problem_details(response, status=401, code="token_invalid")


def test_refresh_with_missing_field_returns_validation_error(client):
    response = client.post(REFRESH_URL, {}, content_type="application/json")

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"] == [
        {
            "field": "refresh",
            "code": "required",
            "detail": "This field is required.",
        }
    ]


def test_tokens_have_the_configured_lifetimes(client, user):
    response = client.post(OBTAIN_URL, TOKEN_OBTAIN, content_type="application/json")
    body = response.json()

    access = AccessToken(body["access"])
    refresh = RefreshToken(body["refresh"])

    assert access["exp"] - access["iat"] == timedelta(minutes=15).total_seconds()
    assert refresh["exp"] - refresh["iat"] == timedelta(days=7).total_seconds()


def test_protected_endpoint_with_expired_access_token_returns_token_invalid(client, user, settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"
    access = AccessToken.for_user(user)
    access.set_exp(lifetime=timedelta(seconds=-1))

    response = client.get("/api/v1/protected/", HTTP_AUTHORIZATION=f"Bearer {access}")

    assert_problem_details(response, status=401, code="token_invalid")


def test_protected_endpoint_without_credentials_returns_not_authenticated(client, settings):
    settings.ROOT_URLCONF = "tests.api.urls_for_tests"

    response = client.get("/api/v1/protected/")

    assert_problem_details(response, status=401, code="not_authenticated")
