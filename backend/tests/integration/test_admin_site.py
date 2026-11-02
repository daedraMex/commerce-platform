import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

pytestmark = pytest.mark.django_db


def admin_page_urls(*, include_add_pages=True):
    urls = [reverse("admin:index")]
    for model in admin.site._registry:
        prefix = f"admin:{model._meta.app_label}_{model._meta.model_name}"
        urls.append(reverse(f"{prefix}_changelist"))
        if include_add_pages:
            urls.append(reverse(f"{prefix}_add"))
    return urls


@pytest.fixture
def staff_with_every_permission(client):
    staff = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)
    staff.user_permissions.set(Permission.objects.all())
    client.force_login(staff)
    return client


def test_staff_with_every_django_permission_cannot_open_any_admin_page(
    staff_with_every_permission,
):
    login_url = reverse("admin:login")

    for url in admin_page_urls():
        response = staff_with_every_permission.get(url)

        assert response.status_code == 302, url
        assert response.url.startswith(login_url), url


def test_superuser_opens_the_index_and_every_changelist(client):
    operator = get_user_model().objects.create_superuser(
        email="operator@example.com", password="s3cret-pass"
    )
    client.force_login(operator)

    for url in admin_page_urls(include_add_pages=False):
        assert client.get(url).status_code == 200, url
