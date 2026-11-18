# Photos contracts

The contracts of the photos module, as merged code implements them (ADR-0031). Each
heading is a contract id for a ticket's **Contracts** section. A pull request that changes
one updates this file and every consumer in the same pull request.

## photos.process-photo-task

**Owner:** #95 (B12 Celery processing pipeline)

| | |
|---|---|
| Task name | `apps.photos.tasks.process_photo`, set with `name=` |
| Kwargs | `store_id: int`, `submission_id: int`; never a default store |
| Producer | `photos.processing-queue` only |
| Unknown submission | returns quietly |
| Retries | up to 3, with backoff, for any error raised outside the processing step: storage or broker errors, and the domain errors `submission_concurrent_modification`, `submission_cannot_mark_ready` and `submission_cannot_mark_failed` |

The worker loads the submission, then:

- **Discarded**, whatever its status: records `failed` with `photo_submission_discarded`.
- **`uploaded`**: starts an attempt (`attempts` + 1), then processes.
- **`processing`**: processes. The submission got here through retry, redo, or a redelivery
  after the worker's own start.
- **`ready`** or **`failed`**: returns unchanged, so a redelivered message is a no-op.

Processing records `ready` with its Media, or `failed` with the domain error `code` raised
while reading or processing the original (`photo_original_missing`, `invalid_image`, the
`quad_*`, `crop_*` and `light_*` codes). These failures are not retried by Celery. Processing
never links Media to a product (ADR-0030).

**Retries exhausted:** nothing records a failure, so the submission stays `processing`.
Retry and redo refuse it, and discard is the only way out (#171).

## photos.processing-queue

**Owner:** #95

```python
class PhotoProcessingQueue(Protocol):
    def enqueue(self, store: StoreReference, submission_id: int) -> None: ...
```

- One port, one adapter: `CeleryPhotoProcessingQueue`.
- Inside a transaction the message is sent with `transaction.on_commit`, so a rolled-back
  save never reaches the worker. Outside one, it is sent at once.
- Callers: upload, retry and redo, each after saving the submission. Retry and redo save
  and enqueue outside one unit of work, so a broker refusal after the save leaves the
  submission `processing` (#172).

## photos.catalog-port

**Owner:** ADR-0030 (carousel and cover)

`PhotoCatalog` is the catalog service as photos sees it. Every call is scoped to one store.

| Operation | Contract |
|---|---|
| `get_product(store, product_id)` | `ProductRecord`, or `None` when missing or owned by another store |
| `get_variant(store, variant_id)` | `VariantRecord`, or `None` likewise |
| `get_media(store, media_id)` | `MediaRecord`, or `None` likewise |
| `create_media(store, media: NewMedia)` | creates or reuses the content-addressed Media and its renditions |
| `product_images_for_media(store, media_id)` | the product links to one Media, active or retired |
| `append_to_carousel(store, *, product_id, media_id, variant_id=None)` | see below |
| `remove_from_carousel(store, *, product_id, media_id)` | see below |

**Append:**

- An existing active link comes back unchanged.
- A retired link is reactivated at the end of the carousel.
- Otherwise a new active link goes at the end. It becomes the cover when the carousel is
  empty.

**Remove:**

- Deactivates the link; it is never deleted.
- An already inactive link is a no-op.
- When the removed image was the cover, the next image by position becomes the cover.

**Errors from the two writes:**

- `catalog_store_mismatch` (404): the product or Media belongs to another store.
- `catalog_variant_not_found`: the variant belongs to another product.
- `catalog_product_image_not_found`: remove found no link.

## photos.submission-states

**Owner:** #94 (B11 individual apply, redo, retry and discard). The group parts (apply for
several products, `/links/`) were merged by #96 and follow this table.

A **photo submission** has a status (`uploaded`, `processing`, `ready`, `failed`) and two
timestamps that are not states: **applied** (`applied_at`) and **discarded**
(`discarded_at`). `MAX_ATTEMPTS` is 3.

| Action | Allowed from | Moves to | `attempts` | Refusal `code` |
|---|---|---|---|---|
| Upload | none | `uploaded`, then enqueued | 0 | see below |
| Worker starts | `uploaded` | `processing` | + 1 | none |
| Worker finishes | `processing` | `ready` or `failed` | unchanged | none |
| Retry | `failed`, not applied or discarded, `attempts` < 3 | `processing`, then enqueued | + 1 | `submission_cannot_start_processing`, `submission_attempts_exhausted` |
| Redo (new corners or crop) | `ready`, not applied or discarded | `processing`, then enqueued | unchanged | `submission_cannot_redo` |
| Apply, individual photo | `ready`, not applied or discarded | applied; status stays `ready` | unchanged | `submission_cannot_apply` |
| Apply, group photo | `ready` with a result, not discarded; applied or not | applied; links synced to the products sent | unchanged | `submission_cannot_apply` (no products, not a group, not ready), `catalog_store_mismatch` |
| Change links, group photo | `ready`, applied | links synced to the products sent; an empty list keeps the photo applied | unchanged | `submission_cannot_change_links` |
| Remove from carousel | applied individual photo | not applied; Media kept | unchanged | `submission_cannot_remove` |
| Discard | not applied, not discarded | discarded; status unchanged; private original and preview deleted | unchanged | `submission_cannot_discard` |

**Every action:**

- Store-scoped, and requires `catalog.manage` through the Authorizer inside the use case.
- Every save checks `version`. A save on a stale one fails with
  `submission_concurrent_modification`.
- Apply and remove change the carousel through `photos.catalog-port`.

**Upload:**

- Refusals: `validation_error` (for example a missing `Idempotency-Key`),
  `submission_invalid_target`, `idempotency_conflict`, `invalid_image`, `too_large`,
  `too_many_pixels`.
- A replay with the same key and payload returns 200 with the original submission and does
  not enqueue again.

**Corners and crop:**

- They are not validated on upload or redo.
- Bad ones arrive later, from the worker, as `failed` with a `quad_*`, `crop_invalid` or
  `crop_missing_source` code.
- A redo field left out keeps its stored value.
- A failed redo cannot be redone (it is not `ready`), and retry reuses the same corners and
  crop. Discard is then the only way out.

**Redo** clears `result_media_id`: the previous Media is kept, but the submission no longer
points to it.

**Discard while queued or `processing`:** the discard's save bumps `version`, so the worker's
next save fails with `submission_concurrent_modification` and Celery retries. The retry sees
the discard and records `failed` with `photo_submission_discarded`.

**Remove on a group photo:** today it returns `catalog_store_mismatch` (404), because a group
photo has no target product. #156 changes this to a refusal.

**An applied group photo cannot be discarded**, even after its links were emptied.
