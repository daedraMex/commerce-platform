import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError

pytestmark = pytest.mark.django_db


def test_user_is_identified_by_email():
    User = get_user_model()

    user = User.objects.create_user(email="ana@Example.COM", password="s3cret-pass")

    assert User.USERNAME_FIELD == "email"
    assert user.email == "ana@example.com"
    assert user.check_password("s3cret-pass")
    assert not user.is_staff
    assert not user.is_superuser
    assert "username" not in {field.name for field in User._meta.get_fields()}


def test_user_logs_in_with_email_and_password():
    get_user_model().objects.create_user(
        email="ana@example.com", password="s3cret-pass"
    )

    user = authenticate(email="ana@example.com", password="s3cret-pass")

    assert user is not None
    assert user.email == "ana@example.com"


def test_create_user_requires_an_email():
    with pytest.raises(ValueError, match="email"):
        get_user_model().objects.create_user(email="", password="s3cret-pass")


def test_email_is_unique():
    User = get_user_model()
    User.objects.create_user(email="ana@example.com", password="s3cret-pass")

    with pytest.raises(IntegrityError):
        User.objects.create_user(email="ana@example.com", password="other-pass")


def test_create_superuser_can_enter_the_admin():
    admin = get_user_model().objects.create_superuser(
        email="owner@example.com", password="s3cret-pass"
    )

    assert admin.is_staff
    assert admin.is_superuser


def test_email_is_stored_lowercase():
    User = get_user_model()

    user = User.objects.create_user(email="Ana@X.com", password="s3cret-pass")

    user.refresh_from_db()
    assert user.email == "ana@x.com"


def test_email_is_lowercased_when_saving_the_model():
    User = get_user_model()
    user = User(email="Ana@X.com")
    user.set_password("s3cret-pass")

    user.save()

    user.refresh_from_db()
    assert user.email == "ana@x.com"


def test_same_email_in_different_case_is_rejected():
    User = get_user_model()
    User.objects.create_user(email="Ana@x.com", password="s3cret-pass")

    with pytest.raises(IntegrityError):
        User.objects.create_user(email="ana@x.com", password="other-pass")


def test_database_rejects_case_variant_emails_that_bypass_save():
    User = get_user_model()
    User.objects.create_user(email="ana@x.com", password="s3cret-pass")
    other = User.objects.create_user(email="bob@x.com", password="s3cret-pass")

    with pytest.raises(IntegrityError):
        User.objects.filter(pk=other.pk).update(email="ANA@x.com")


def test_user_logs_in_with_email_in_any_case():
    get_user_model().objects.create_user(email="ana@x.com", password="s3cret-pass")

    user = authenticate(email="Ana@X.com", password="s3cret-pass")

    assert user is not None
