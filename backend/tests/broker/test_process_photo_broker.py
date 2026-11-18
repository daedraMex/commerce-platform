"""A photo travels through a real Redis broker to a real Celery worker (#149).

The upload's queue adapter sends ``apps.photos.tasks.process_photo`` by name; the
embedded worker consumes it. A task registered under another name never runs, so the
submission stays ``uploaded`` and the wait times out. Runs only with ``-m real_broker``.
"""

import time
import uuid

import pytest
from celery.contrib.testing.worker import start_worker
from django.contrib.auth import get_user_model

from apps.accounts.services import grant_membership
from apps.photos.models import PhotoSubmission
from apps.stores.models import Store
from config.celery import app
from tests.api.test_staff_photos import upload

pytestmark = [
    pytest.mark.real_broker,
    pytest.mark.no_celery_eager,
    # Committed rows, so the worker thread's own connection sees them; serialized_rollback
    # restores the seeded roles the flush would otherwise wipe for the next broker test.
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]

WAIT_SECONDS = 30


@pytest.fixture
def private_storage(tmp_path, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path / "private"},
        },
    }
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_BASE_URL = "https://media.example.com"


@pytest.fixture
def worker(monkeypatch):
    app.loader.import_default_modules()
    # A queue of its own, so a docker-compose worker on the same Redis cannot take the
    # message (it would look for the submission in the development database).
    queue = f"broker-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(app.conf, "task_default_queue", queue)
    monkeypatch.delattr(app.amqp, "queues", raising=False)
    monkeypatch.delattr(app.amqp, "router", raising=False)
    # Results are ignored in this project, so the ping check (which waits for one) is off.
    with start_worker(
        app, perform_ping_check=False, shutdown_timeout=30, queues=[queue]
    ) as running:
        yield running


def wait_until_processed(submission_id):
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        submission = PhotoSubmission.objects.get(pk=submission_id)
        if submission.status not in ("uploaded", "processing"):
            return submission
        time.sleep(0.2)
    raise AssertionError(
        f"submission {submission_id} is still {submission.status} after {WAIT_SECONDS}s: "
        "the worker never ran apps.photos.tasks.process_photo"
    )


def test_an_uploaded_photo_is_processed_by_a_worker_through_redis(client, private_storage, worker):
    store = Store.objects.create(slug="home", name="Home")
    user = get_user_model().objects.create_user(email="ana@example.com", password="s3cret-pass")
    grant_membership(user=user, store=store, role_name="content_editor")

    response = upload(client, user)

    assert response.status_code == 201
    submission = wait_until_processed(response.json()["id"])
    assert submission.attempts == 1
    assert submission.status == "ready", (submission.failure_code, submission.failure_message)
    assert submission.result_media_id is not None
