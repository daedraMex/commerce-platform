from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from tests.api.helpers import assert_problem_details

pytestmark = pytest.mark.django_db

OBTAIN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
LOGOUT_URL = "/api/v1/auth/logout/"

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


def _refresh(client, refresh):
    return client.post(REFRESH_URL, {"refresh": refresh}, content_type="application/json")


def _logout(client, refresh, *, as_user):
    access = AccessToken.for_user(as_user)
    return client.post(
        LOGOUT_URL,
        {"refresh": refresh},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )


@pytest.fixture
def other_user():
    return get_user_model().objects.create_user(
        email="bruno@example.com",
        password="s3cret-pass",
    )


def test_refresh_returns_a_new_access_and_refresh_token_pair(client, user):
    refresh = str(RefreshToken.for_user(user))

    response = _refresh(client, refresh)

    assert response.status_code == 200
    body = response.json()
    assert AccessToken(body["access"])["user_id"] == str(user.id)
    assert body["refresh"] != refresh
    assert RefreshToken(body["refresh"])["user_id"] == str(user.id)


def test_refresh_with_a_used_refresh_token_returns_token_invalid(client, user):
    refresh = str(RefreshToken.for_user(user))
    _refresh(client, refresh)

    response = _refresh(client, refresh)

    body = assert_problem_details(response, status=401, code="token_invalid")
    assert body["detail"] == "Token is invalid"


def test_refresh_with_the_rotated_refresh_token_succeeds(client, user):
    rotated = _refresh(client, str(RefreshToken.for_user(user))).json()["refresh"]

    response = _refresh(client, rotated)

    assert response.status_code == 200


def test_refresh_for_a_user_deactivated_after_login_returns_token_invalid(client, user):
    refresh = str(RefreshToken.for_user(user))
    user.is_active = False
    user.save(update_fields=["is_active"])

    response = _refresh(client, refresh)

    body = assert_problem_details(response, status=401, code="token_invalid")
    assert body["detail"] == "Token is invalid"


def test_refresh_for_a_deleted_user_returns_token_invalid(client, user):
    refresh = str(RefreshToken.for_user(user))
    user.delete()

    response = _refresh(client, refresh)

    assert_problem_details(response, status=401, code="token_invalid")


def test_logout_blacklists_the_refresh_token(client, user):
    refresh = str(RefreshToken.for_user(user))

    response = _logout(client, refresh, as_user=user)

    assert response.status_code == 204
    assert response.content == b""
    assert_problem_details(_refresh(client, refresh), status=401, code="token_invalid")


def test_logout_twice_with_the_same_token_returns_204(client, user):
    refresh = str(RefreshToken.for_user(user))
    _logout(client, refresh, as_user=user)

    response = _logout(client, refresh, as_user=user)

    assert response.status_code == 204


def test_logout_with_another_users_refresh_token_returns_token_invalid(client, user, other_user):
    refresh = str(RefreshToken.for_user(other_user))

    response = _logout(client, refresh, as_user=user)

    body = assert_problem_details(response, status=401, code="token_invalid")
    assert body["detail"] == "Token is invalid"
    assert _refresh(client, refresh).status_code == 200


def test_logout_with_an_invalid_refresh_token_returns_token_invalid(client, user):
    response = _logout(client, "not-a-token", as_user=user)

    body = assert_problem_details(response, status=401, code="token_invalid")
    assert body["detail"] == "Token is invalid"


def test_logout_with_an_expired_refresh_token_returns_token_invalid(client, user):
    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=timedelta(seconds=-1))

    response = _logout(client, str(refresh), as_user=user)

    body = assert_problem_details(response, status=401, code="token_invalid")
    assert body["detail"] == "Token is invalid"


def test_logout_with_an_access_token_in_the_body_returns_token_invalid(client, user):
    access = str(AccessToken.for_user(user))

    response = _logout(client, access, as_user=user)

    assert_problem_details(response, status=401, code="token_invalid")


def test_logout_without_credentials_returns_not_authenticated(client, user):
    refresh = str(RefreshToken.for_user(user))

    response = client.post(LOGOUT_URL, {"refresh": refresh}, content_type="application/json")

    assert_problem_details(response, status=401, code="not_authenticated")
    assert _refresh(client, refresh).status_code == 200


def test_logout_with_missing_field_returns_validation_error(client, user):
    access = AccessToken.for_user(user)

    response = client.post(
        LOGOUT_URL, {}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {access}"
    )

    body = assert_problem_details(response, status=400, code="validation_error")
    assert body["errors"] == [
        {
            "field": "refresh",
            "code": "required",
            "detail": "This field is required.",
        }
    ]


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
