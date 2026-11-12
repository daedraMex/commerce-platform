---
status: accepted
---

# Catalog photos are processed asynchronously from private originals and linked through active product images

Phase 4b gives staff one way to turn phone photos into catalog images from Quetzal. The original is uploaded through the API as multipart, behind a `MediaUploader` port so Phase 4d's video can switch to presigned direct-to-R2 uploads without changing callers. Upload normalizes the file (HEIC decoded with pillow-heif, EXIF orientation applied, metadata stripped, JPEG) and stores it in a private bucket, never the public media bucket; a downscaled preview is generated once and served by an authorized endpoint. Processing runs in Celery, introduced here ahead of Phase 6, and produces a content-addressed Media plus 320 px and 800 px WebP renditions. Rendition keys are derived from the original storage key with the size and a rendition version, so changing a size or the algorithm writes new keys and never breaks the immutable cache; Media gains no rendition columns.

There is no ML in Phase 4b. Background removal was dropped for its paid model license, CPU cost and unproven quality, so contour products get an individual rectangular crop and group photos cover many items at once. Rectangle photos are straightened from four staff-tapped corners and cropped to the photographed size's ratio; rectangle categories without size dimensions keep the quad's ratio; contour photos use the shared draggable crop frame with the size's ratio and fall back to 4:5; group photos are always 4:5. Light correction is deterministic gray-world white balance with capped gains and a small autocontrast cutoff, staff can switch it off, and `pipeline_version` records the result so it can be reproduced.

A Photo submission is the unit: `uploaded`, `processing`, `ready` or `failed`, with a client idempotency key unique per store and creator and a 409 when a replay carries a different payload. Retries and redos never delete; a redo creates a new result and keeps the old one. An individual photo targets a Product, records the photographed Variant, and becomes its main image; a group photo is linked as a gallery image to many products while reusing one Media. Catalog keeps Media creation and the product-image rules behind a service, and the pipeline lives in a new clean-architecture module, `apps/photos/`, which never writes catalog models. `ProductMedia` gains `is_active`, its one-main constraint covers active links only, and `(product, media)` becomes unique; links are deactivated, reactivated and upserted without losing position, and every reader returns active links only. Video is Phase 4d; no video fields are added now.

## Considered Options

- Presigned direct-to-R2 uploads now: deferred. At this volume API multipart keeps validation before storage and avoids bucket CORS and abandoned-upload cleanup; video is the case that needs direct upload later.
- ML background removal (`rembg` with `isnet-general-use`, or `bria-rmbg`): dropped. The best default model needs a paid commercial license, and CPU cost and quality were not justified before real photos exist.
- Contour products covered only by group photos: rejected, because a figure pillow still needs an individual main image.
- Main image owned by the Variant: rejected for now. Product-targeted with the variant recorded matches the glossary and lets per-size mains arrive later without moving data.
- Originals in the public media bucket: rejected by AGENTS.md; the bucket holds public product media only.
- Catalog use cases around photo linking: rejected. Catalog stays CRUD-only and exposes a product-image service; the photos module owns the state machine, idempotency, quad validation and Authorizer calls.

## Consequences

- Human-reviewed migrations: `Store.accent_color`, the `ProductMedia` changes, the token blacklist app, and the photos models.
- A second, private R2 bucket (RustFS in the level-2 end-to-end stack) with new environment variables. These are platform infrastructure, not per-store integration credentials, so ADR-0020 does not apply.
- A Celery worker joins `docker-compose.yml` for development and the level-2 stack, with eager execution in tests and no beat.
- The console fetches the private preview as a blob through its axios instance, because a plain `<img src>` cannot send the `X-Store` or CSRF headers of the ADR-0027 proxy.
- `ROADMAP.md` Phase 4b and `phase-prompts.md` still describe background removal and must be rewritten at `/to-spec` to match this decision.

## Amendment (2026-11-12)

MinIO withdrew the `minio/minio` and `minio/mc` images from Docker Hub on
2026-09-11 and closed anonymous pulls on quay.io on 2026-09-24, so MinIO could
no longer run local development or the level-2 end-to-end stack. Local
development and CI now run RustFS (`rustfs/rustfs`) and create the buckets with
the AWS CLI (`amazon/aws-cli`): the public bucket gets an anonymous
`s3:GetObject` bucket policy and the private bucket gets none. Staging and
production are unchanged and still use R2. The private bucket remains platform
infrastructure, not a per-store credential, so ADR-0020 still does not apply.
