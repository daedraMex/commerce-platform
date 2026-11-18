# Photos contracts

The contracts of the photos module, as merged code implements them (ADR-0031). Each
heading is a contract id for a ticket's `Contracts:` line. A pull request that changes one
updates this file and every consumer in the same pull request.

## photos.process-photo-task

**Owner:** #95 (B12 Celery processing pipeline)

| | |
|---|---|
| Task name | `apps.photos.tasks.process_photo`, set with `name=` |
| Kwargs | `store_id: int`, `submission_id: int`; never a default store |
| Producer | `photos.processing-queue` only |
| Retries | transient errors retry up to 3 times with backoff; a domain failure is recorded on the submission and never retried; an unknown submission returns quietly |

The worker:

- **Discarded** submission: whatever its status, recorded as `failed` with code
  `photo_submission_discarded`.
- **`uploaded`**: starts an attempt (`attempts` + 1), then processes.
- **`processing`**: processes; the attempt was started by retry or redo.
- **`ready`** or **`failed`**: returns unchanged, so a redelivered message is a no-op.

Processing records `ready` with its Media, or `failed` with a domain error `code`. It never
links Media to a product (ADR-0030).

## photos.processing-queue

**Owner:** #95

```python
class PhotoProcessingQueue(Protocol):
    def enqueue(self, store: StoreReference, submission_id: int) -> None: ...
```

- One port, one adapter: `CeleryPhotoProcessingQueue`.
- Inside a transaction, the message is sent with `transaction.on_commit`, so a rolled-back
  save never reaches the worker.
- Callers: upload, retry and redo, each after saving the submission.

## photos.catalog-port

**Owner:** ADR-0030 (carousel and cover)

`PhotoCatalog` is the catalog service as photos sees it. Every call is scoped to one store,
and a record another store owns comes back as `None`.

| Operation | Contract |
|---|---|
| `get_product(store, product_id)` | `ProductRecord` or `None` |
| `get_variant(store, variant_id)` | `VariantRecord` or `None` |
| `get_media(store, media_id)` | `MediaRecord` or `None` |
| `create_media(store, media: NewMedia)` | creates or reuses the content-addressed Media and its renditions |
| `product_images_for_media(store, media_id)` | the product links to one Media, active or retired |
| `append_to_carousel(store, *, product_id, media_id, variant_id=None)` | appends an active link at the end of the carousel; it becomes the cover when the carousel is empty |
| `remove_from_carousel(store, *, product_id, media_id)` | deactivates the link, never deletes it, and promotes the next image to cover |

## photos.submission-states

**Owner:** #94 (B11 apply, redo, retry and discard)

A **photo submission** has a status (`uploaded`, `processing`, `ready`, `failed`) and two
timestamps that are not states: **applied** (`applied_at`) and **discarded**
(`discarded_at`). `MAX_ATTEMPTS` is 3.

| Action | Allowed from | Moves to | `attempts` | Refusal `code` |
|---|---|---|---|---|
| Upload | none | `uploaded`, then enqueued | 0 | `submission_invalid_target`, `idempotency_conflict` |
| Worker starts | `uploaded` | `processing` | + 1 | none |
| Worker finishes | `processing` | `ready` or `failed` | unchanged | none |
| Retry | `failed`, not applied or discarded, `attempts` < 3 | `processing`, then enqueued | + 1 | `submission_cannot_start_processing`, `submission_attempts_exhausted` |
| Redo (new corners or crop) | `ready`, not applied or discarded | `processing`, then enqueued; the previous Media is kept | unchanged | `submission_cannot_redo` |
| Apply (approve) | `ready`, not applied or discarded | applied; status stays `ready` | unchanged | `submission_cannot_apply` |
| Remove from carousel | applied | not applied; Media kept | unchanged | `submission_cannot_remove` |
| Discard | any status, not applied | discarded; the private original and preview are deleted | unchanged | `submission_cannot_discard` |

- Every action is store-scoped and requires `catalog.manage` through the Authorizer, inside
  the use case.
- Every save checks `version`; a save on a stale one fails with
  `submission_concurrent_modification`.
- An apply or remove also changes the carousel through `photos.catalog-port`.
- **Discard while queued or `processing`:** a worker that loads the submission after the
  discard records `failed` with `photo_submission_discarded`. A worker already past that
  check still records its result (`ready`, or `failed` with `photo_original_missing` when
  the deleted original was not read yet), and the submission stays discarded, so it can
  never be applied.
- **Group photos:** apply links them to each product they are approved for; the links can be
  changed afterwards (`submission_cannot_change_links`).
