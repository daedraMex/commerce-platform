import math

import pytest

from apps.photos.domain.crop import (
    FALLBACK_CROP_RATIO,
    CropRect,
    crop_ratio,
    fit_crop,
)
from apps.photos.domain.errors import CropSourceMissing, InvalidPhotographedSize
from apps.photos.domain.geometry import AspectRatio
from apps.photos.domain.submission import SubmissionKind

SIZE = (210.0, 160.0)
TALL_QUAD = [
    {"x": 100, "y": 100},
    {"x": 300, "y": 100},
    {"x": 300, "y": 500},
    {"x": 100, "y": 500},
]


def test_a_group_photo_is_always_four_by_five():
    assert crop_ratio(kind=SubmissionKind.GROUP) == FALLBACK_CROP_RATIO
    assert crop_ratio(kind=SubmissionKind.GROUP, size=SIZE) == FALLBACK_CROP_RATIO
    assert FALLBACK_CROP_RATIO == AspectRatio(4, 5)


def test_a_contour_photo_uses_the_photographed_size_ratio():
    assert crop_ratio(kind=SubmissionKind.CONTOUR, size=SIZE) == AspectRatio(210, 160)


def test_a_contour_photo_without_a_size_falls_back_to_four_by_five():
    assert crop_ratio(kind=SubmissionKind.CONTOUR) == FALLBACK_CROP_RATIO


def test_a_rectangle_photo_uses_the_photographed_size_ratio():
    assert crop_ratio(kind=SubmissionKind.RECTANGLE, size=SIZE, corners=TALL_QUAD) == (
        AspectRatio(210, 160)
    )


def test_a_rectangle_photo_without_a_size_uses_the_quad_ratio():
    assert crop_ratio(kind=SubmissionKind.RECTANGLE, corners=TALL_QUAD) == AspectRatio(200, 400)


def test_a_rectangle_photo_without_a_size_or_corners_is_rejected():
    with pytest.raises(CropSourceMissing) as error:
        crop_ratio(kind=SubmissionKind.RECTANGLE)

    assert error.value.code == "crop_missing_source"


@pytest.mark.parametrize(
    "size",
    [
        (0, 160),
        (-1, 160),
        (210, 0),
        ("210", 160),
        (math.nan, 160),
        (210, math.inf),
        (True, 160),
    ],
)
def test_an_invalid_photographed_size_is_rejected(size):
    with pytest.raises(InvalidPhotographedSize) as error:
        crop_ratio(kind=SubmissionKind.CONTOUR, size=size)

    assert error.value.code == "crop_invalid_size"


def test_fitting_a_square_to_four_by_five_crops_the_sides():
    fitted = fit_crop(CropRect(x=0, y=0, width=1000, height=1000), FALLBACK_CROP_RATIO)

    assert fitted == CropRect(x=100, y=0, width=800, height=1000)


def test_fitting_a_wide_frame_to_a_square_crops_the_sides():
    fitted = fit_crop(CropRect(x=0, y=0, width=1000, height=500), AspectRatio(1, 1))

    assert fitted == CropRect(x=250, y=0, width=500, height=500)


def test_fitting_a_tall_frame_to_a_square_crops_the_ends():
    fitted = fit_crop(CropRect(x=0, y=0, width=500, height=1000), AspectRatio(1, 1))

    assert fitted == CropRect(x=0, y=250, width=500, height=500)


def test_fitting_an_offset_frame_keeps_its_centre():
    fitted = fit_crop(CropRect(x=50, y=20, width=1000, height=1000), FALLBACK_CROP_RATIO)

    assert fitted == CropRect(x=150, y=20, width=800, height=1000)


def test_a_frame_already_at_the_target_ratio_is_unchanged():
    frame = CropRect(x=10, y=20, width=800, height=1000)

    assert fit_crop(frame, FALLBACK_CROP_RATIO) == frame
