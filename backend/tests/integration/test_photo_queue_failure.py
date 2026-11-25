import pytest
from django.contrib.auth import get_user_model

from apps.photos.infrastructure import processing_queue
from apps.photos.infrastructure.processing_queue import CeleryPhotoProcessingQueue
from apps.photos.models import PhotoSubmission
from apps.shared.domain.store import StoreReference
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_submission(store, user, *, status, attempts):
    return PhotoSubmission.objects.create(
        store=store,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key=f"key-{status}-{attempts}",
        request_fingerprint="a" * 64,
        status=status,
        attempts=attempts,
    )


@pytest.mark.parametrize(
    ("status", "attempts", "expected_attempts"),
    [
        (PhotoSubmission.Status.UPLOADED, 0, 1),
        (PhotoSubmission.Status.PROCESSING, 1, 1),
    ],
)
def test_a_broker_send_failure_marks_the_submission_unavailable(
    monkeypatch, django_capture_on_commit_callbacks, status, attempts, expected_attempts
):
    store = Store.objects.create(slug="home", name="Home")
    user = get_user_model().objects.create_user(email="ana@example.com")
    submission = make_submission(store, user, status=status, attempts=attempts)

    def refuse(name, kwargs):
        raise RuntimeError("the broker is down")

    monkeypatch.setattr(processing_queue.app, "send_task", refuse)

    with django_capture_on_commit_callbacks(execute=True):
        CeleryPhotoProcessingQueue().enqueue(
            StoreReference(id=store.id, slug=store.slug), submission.pk
        )

    submission.refresh_from_db()
    assert submission.status == PhotoSubmission.Status.FAILED
    assert submission.failure_code == "photo_processing_unavailable"
    assert submission.failure_message
    assert submission.attempts == expected_attempts


def test_a_send_failure_never_marks_another_stores_submission(
    monkeypatch, django_capture_on_commit_callbacks
):
    home = Store.objects.create(slug="home", name="Home")
    anime = Store.objects.create(slug="anime", name="Anime")
    user = get_user_model().objects.create_user(email="ana@example.com")
    submission = make_submission(home, user, status=PhotoSubmission.Status.PROCESSING, attempts=1)

    def refuse(name, kwargs):
        raise RuntimeError("the broker is down")

    monkeypatch.setattr(processing_queue.app, "send_task", refuse)

    with django_capture_on_commit_callbacks(execute=True):
        CeleryPhotoProcessingQueue().enqueue(
            StoreReference(id=anime.id, slug=anime.slug), submission.pk
        )

    submission.refresh_from_db()
    assert submission.status == PhotoSubmission.Status.PROCESSING
    assert submission.failure_code == ""
