"""Choose and fit the crop ratio for one photo (ADR-0028).

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from apps.photos.domain.errors import CropSourceMissing, InvalidPhotographedSize
from apps.photos.domain.geometry import AspectRatio, is_positive_number
from apps.photos.domain.quad import quad_aspect_ratio
from apps.photos.domain.submission import SubmissionKind

FALLBACK_CROP_RATIO = AspectRatio(4, 5)


@dataclass(frozen=True, slots=True)
class CropRect:
    """A pixel rectangle inside the source photo."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("A crop rectangle uses integer pixels.")
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError("A crop rectangle needs a non-negative origin and a positive size.")


def crop_ratio(
    *,
    kind: SubmissionKind,
    size: tuple[float, float] | None = None,
    corners=None,
) -> AspectRatio:
    """Pick the target ratio from the photographed size, the quad or the 4:5 fallback."""
    kind = SubmissionKind(kind)
    if kind is SubmissionKind.GROUP:
        return FALLBACK_CROP_RATIO

    photographed = _size_ratio(size)
    if photographed is not None:
        return photographed
    if kind is SubmissionKind.CONTOUR:
        return FALLBACK_CROP_RATIO
    if corners is None:
        raise CropSourceMissing("A rectangle photo needs a size or its four corners.")
    return quad_aspect_ratio(corners)


def fit_crop(frame: CropRect, ratio: AspectRatio) -> CropRect:
    """Shrink the frame around its centre to the target ratio, never enlarging it."""
    target = ratio.value
    current = frame.width / frame.height
    if math.isclose(current, target, rel_tol=1e-9):
        return frame

    if current > target:
        width = max(1, round(frame.height * target))
        return CropRect(
            x=frame.x + (frame.width - width) // 2,
            y=frame.y,
            width=width,
            height=frame.height,
        )

    height = max(1, round(frame.width / target))
    return CropRect(
        x=frame.x,
        y=frame.y + (frame.height - height) // 2,
        width=frame.width,
        height=height,
    )


def _size_ratio(size) -> AspectRatio | None:
    if size is None:
        return None
    if isinstance(size, (str, bytes)) or not isinstance(size, Sequence) or len(size) != 2:
        raise InvalidPhotographedSize("A photographed size is a (width, height) pair.")
    width, height = size
    if not is_positive_number(width) or not is_positive_number(height):
        raise InvalidPhotographedSize("The photographed size must be positive.")
    return AspectRatio(float(width), float(height))
