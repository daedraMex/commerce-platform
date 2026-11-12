"""Build the stable fingerprint that makes a photo upload idempotent (ADR-0028).

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

import hashlib
import json

from apps.photos.domain.submission import SubmissionKind


def photo_request_fingerprint(
    *,
    kind: SubmissionKind,
    target_product_id: int | None,
    photographed_variant_id: int | None,
    corners,
    crop,
    light_correction: bool,
    content: bytes,
) -> str:
    """Hash the whole request, file bytes included, into one deterministic digest."""
    payload = {
        "kind": SubmissionKind(kind).value,
        "target_product_id": target_product_id,
        "photographed_variant_id": photographed_variant_id,
        "corners": corners,
        "crop": crop,
        "light_correction": bool(light_correction),
        "file_sha256": hashlib.sha256(content).hexdigest(),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
