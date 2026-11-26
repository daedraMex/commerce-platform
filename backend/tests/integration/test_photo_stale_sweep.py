from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.photos.application.sweep_stale_processing import SweepStaleProcessing
from apps.photos.infrastructure.repository import DjangoPhotoSubmissionRepository
from apps.photos.models import PhotoSubmission
from apps.shared.domain.store import StoreReference
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def make_store(slug):
    return Store.objects.create(slug=slug, name=slug.title())


def make_submission(store, user, *, key, status, age):
    submission = PhotoSubmission.objects.create(
        store=store,
        created_by=user,
        kind=PhotoSubmission.Kind.GROUP,
        idempotency_key=key,
        request_fingerprint="a" * 64,
        status=status,
        attempts=1 if status == PhotoSubmission.Status.PROCESSING else 0,
    )
    PhotoSubmission.objects.filter(pk=submission.pk).update(
        updated_at=timezone.now() - timedelta(minutes=age)
    )
    submission.refresh_from_db()
    return submission


def test_the_repository_finds_stale_processing_or_uploaded_in_the_requested_store():
    home = make_store("home")
    anime = make_store("anime")
    user = get_user_model().objects.create_user(email="ana@example.com")
    home_stale = make_submission(
        home, user, key="home-stale", status=PhotoSubmission.Status.PROCESSING, age=20
    )
    home_uploaded_stale = make_submission(
        home, user, key="home-uploaded-stale", status=PhotoSubmission.Status.UPLOADED, age=20
    )
    make_submission(
        anime, user, key="anime-stale", status=PhotoSubmission.Status.PROCESSING, age=20
    )
    make_submission(
        anime, user, key="anime-uploaded-stale", status=PhotoSubmission.Status.UPLOADED, age=20
    )
    make_submission(home, user, key="home-fresh", status=PhotoSubmission.Status.PROCESSING, age=1)
    make_submission(
        home, user, key="home-uploaded-fresh", status=PhotoSubmission.Status.UPLOADED, age=1
    )
    make_submission(home, user, key="home-ready", status=PhotoSubmission.Status.READY, age=20)
    make_submission(home, user, key="home-failed", status=PhotoSubmission.Status.FAILED, age=20)
    repository = DjangoPhotoSubmissionRepository()
    cutoff = timezone.now() - timedelta(minutes=15)

    assert repository.store_ids_with_stale_processing(cutoff) == sorted([home.id, anime.id])

    rows = repository.list_stale_processing(StoreReference(id=home.id, slug=home.slug), cutoff)

    assert [row.id for row in rows] == [home_stale.id, home_uploaded_stale.id]
    assert [row.status.value for row in rows] == ["processing", "uploaded"]


def test_the_sweep_marks_every_stores_stale_submission_failed():
    home = make_store("home")
    anime = make_store("anime")
    user = get_user_model().objects.create_user(email="ana@example.com")
    home_stale = make_submission(
        home, user, key="home-stale", status=PhotoSubmission.Status.PROCESSING, age=20
    )
    home_uploaded_stale = make_submission(
        home, user, key="home-uploaded-stale", status=PhotoSubmission.Status.UPLOADED, age=20
    )
    anime_stale = make_submission(
        anime, user, key="anime-stale", status=PhotoSubmission.Status.PROCESSING, age=20
    )
    anime_uploaded_stale = make_submission(
        anime, user, key="anime-uploaded-stale", status=PhotoSubmission.Status.UPLOADED, age=20
    )
    fresh = make_submission(
        home, user, key="home-fresh", status=PhotoSubmission.Status.PROCESSING, age=1
    )
    fresh_uploaded = make_submission(
        home, user, key="home-uploaded-fresh", status=PhotoSubmission.Status.UPLOADED, age=1
    )
    ready = make_submission(
        home, user, key="home-ready", status=PhotoSubmission.Status.READY, age=20
    )
    failed = make_submission(
        home, user, key="home-failed", status=PhotoSubmission.Status.FAILED, age=20
    )

    SweepStaleProcessing(
        repository=DjangoPhotoSubmissionRepository(),
        stale_after=timedelta(minutes=15),
    )(timezone.now())

    for submission in (home_stale, anime_stale, home_uploaded_stale, anime_uploaded_stale):
        submission.refresh_from_db()
        assert submission.status == PhotoSubmission.Status.FAILED
        assert submission.failure_code == "photo_processing_unavailable"
        assert submission.failure_message
        assert submission.attempts == 1
    fresh.refresh_from_db()
    assert fresh.status == PhotoSubmission.Status.PROCESSING
    assert fresh.failure_code == ""
    fresh_uploaded.refresh_from_db()
    assert fresh_uploaded.status == PhotoSubmission.Status.UPLOADED
    assert fresh_uploaded.failure_code == ""
    assert fresh_uploaded.attempts == 0
    ready.refresh_from_db()
    assert ready.status == PhotoSubmission.Status.READY
    failed.refresh_from_db()
    assert failed.status == PhotoSubmission.Status.FAILED
    assert failed.failure_code == ""
