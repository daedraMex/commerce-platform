"""Turn a submission's staff choices into the deterministic processing plan (ADR-0028).

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from apps.photos.domain.crop import (
    FALLBACK_CROP_RATIO,
    CropRect,
    crop_ratio,
    fit_crop,
)
from apps.photos.domain.errors import InvalidCrop
from apps.photos.domain.geometry import AspectRatio, Point
from apps.photos.domain.pipeline import PIPELINE_VERSION
from apps.photos.domain.quad import to_pixels, validate_quad
from apps.photos.domain.submission import SubmissionKind


@dataclass(frozen=True, slots=True)
class ProcessingPlan:
    """Where to read pixels from, how to align them and whether to correct the light."""

    source_frame: CropRect
    target_ratio: AspectRatio
    pixel_corners: tuple[Point, Point, Point, Point] | None
    light_correction: bool
    pipeline_version: str = PIPELINE_VERSION


def plan_processing(
    *,
    kind: SubmissionKind,
    crop: Mapping | None,
    corners,
    light_correction: bool,
    image_width: int,
    image_height: int,
) -> ProcessingPlan:
    """Choose the frame and ratio for one of the three submission kinds."""
    kind = SubmissionKind(kind)
    if image_width <= 0 or image_height <= 0:
        raise ValueError("The image dimensions must be positive.")

    frame = _parse_crop(crop) if crop is not None else _full_frame(image_width, image_height)

    if kind is SubmissionKind.RECTANGLE and corners is not None:
        pixel_corners = validate_quad(
            to_pixels(corners, image_width, image_height),
            image_width=image_width,
            image_height=image_height,
        )
        ratio = (
            _frame_ratio(frame)
            if crop is not None
            else crop_ratio(kind=kind, pixel_corners=pixel_corners)
        )
        return ProcessingPlan(
            source_frame=_full_frame(image_width, image_height),
            target_ratio=ratio,
            pixel_corners=pixel_corners,
            light_correction=light_correction,
        )

    if kind is SubmissionKind.RECTANGLE:
        ratio = (
            _frame_ratio(frame) if crop is not None else crop_ratio(kind=kind, pixel_corners=None)
        )
    elif kind is SubmissionKind.CONTOUR:
        ratio = _frame_ratio(frame) if crop is not None else FALLBACK_CROP_RATIO
    else:
        ratio = FALLBACK_CROP_RATIO

    return ProcessingPlan(
        source_frame=fit_crop(frame, ratio),
        target_ratio=ratio,
        pixel_corners=None,
        light_correction=light_correction,
    )


def _parse_crop(crop: Mapping) -> CropRect:
    if not isinstance(crop, Mapping):
        raise InvalidCrop("The crop frame must be an object with x, y, width and height.")
    try:
        values = {name: crop[name] for name in ("x", "y", "width", "height")}
    except KeyError as error:
        raise InvalidCrop("The crop frame needs x, y, width and height.") from error
    if any(not _is_integer(value) for value in values.values()):
        raise InvalidCrop("The crop frame fields must be integer pixels.")
    try:
        return CropRect(
            x=int(values["x"]),
            y=int(values["y"]),
            width=int(values["width"]),
            height=int(values["height"]),
        )
    except ValueError as error:
        raise InvalidCrop(
            "The crop frame needs a non-negative origin and a positive size."
        ) from error


def _is_integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _full_frame(width: int, height: int) -> CropRect:
    return CropRect(x=0, y=0, width=width, height=height)


def _frame_ratio(frame: CropRect) -> AspectRatio:
    return AspectRatio(frame.width, frame.height)


def _ensure_inside(frame: CropRect, image_width: int, image_height: int) -> None:
    if frame.x + frame.width > image_width or frame.y + frame.height > image_height:
        raise InvalidCrop("The crop frame must lie inside the photo.")
