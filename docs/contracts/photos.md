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

When the last retry fails, the task records `failed` with `photo_processing_unavailable` and
a short message, without spending another attempt. If recording that failure itself fails,
the error is logged with the store and submission id instead of being dropped.

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

**Retries exhausted:** the last retry records `failed` with
`photo_processing_unavailable` through the `FailExhaustedProcessing` use case and the
repository, leaving `attempts` unchanged, so retry is allowed while `attempts` < 3. A
submission discarded meanwhile still records `failed` with `photo_submission_discarded`. If
recording the failure itself fails, the task logs the error with the store and submission id
(#171).

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

- Refusals: `validation_error` (a missing or over-long `Idempotency-Key`, or malformed
  `corners` or `crop`), `submission_invalid_target`, `idempotency_conflict`,
  `invalid_image`, `too_large`, `too_many_pixels`.
- The `Idempotency-Key` and the declared file size are checked before the file content is
  read; a file over 25 MB is refused with `too_large`. Authorization also runs before the
  content is read, so a user without `catalog.manage` gets 403 without the file reaching
  private storage.
- A replay with the same key and payload returns 200 with the original submission and does
  not enqueue again. When a concurrent upload loses the unique-key race after storing its
  files, both are deleted through the `MediaUploader` port before the original is replayed.

**Corners and crop:**

- Upload and redo share one serializer and validate their shape at the API edge.
- `corners`, when sent, must be a list of exactly four `{x, y}` points whose coordinates
  are finite numbers. A string, a different length, missing coordinates, booleans or
  non-numeric values return 400 `validation_error`.
- `crop`, when sent, must be an object with numeric `x`, `y`, `width` and `height`;
  anything else returns 400 `validation_error`.
- Only the shape is checked at the edge. Pixel-dependent geometry (corners inside the
  photo, a convex non-crossing quad, a positive crop inside the image) stays in the
  processing pipeline and fails later as `failed` with a `quad_*`, `crop_invalid` or
  `crop_missing_source` code.
- A redo field left out keeps its stored value; a field sent as `null` is malformed.
- A failed redo cannot be redone (it is not `ready`), and retry reuses the same corners and
  crop. Discard is then the only way out.

**Preview:** the private preview response carries `Cache-Control: private, no-store` and
`X-Content-Type-Options: nosniff`. A reader refuses a key outside `stores/{store.id}/`,
failing closed as not found.

**Redo** clears `result_media_id`: the previous Media is kept, but the submission no longer
points to it.

**Discard while queued or `processing`:** the discard's save bumps `version`, so the worker's
next save fails with `submission_concurrent_modification` and Celery retries. The retry sees
the discard and records `failed` with `photo_submission_discarded`.

**Remove on a group photo:** today it returns `catalog_store_mismatch` (404), because a group
photo has no target product. #156 changes this to a refusal.

**An applied group photo cannot be discarded**, even after its links were emptied.
