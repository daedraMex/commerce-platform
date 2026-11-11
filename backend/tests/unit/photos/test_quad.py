import math

import pytest

from apps.photos.domain.errors import (
    InvalidQuadCorners,
    QuadNonConvex,
    QuadOutOfBounds,
    QuadSelfIntersecting,
    QuadTooSmall,
)
from apps.photos.domain.geometry import AspectRatio, Point
from apps.photos.domain.quad import (
    MIN_QUAD_AREA_RATIO,
    quad_area,
    quad_aspect_ratio,
    to_pixels,
    validate_quad,
)

IMAGE_WIDTH = 1000
IMAGE_HEIGHT = 1000
SQUARE = [
    {"x": 100, "y": 100},
    {"x": 900, "y": 100},
    {"x": 900, "y": 900},
    {"x": 100, "y": 900},
]
TALL = [
    {"x": 100, "y": 100},
    {"x": 300, "y": 100},
    {"x": 300, "y": 500},
    {"x": 100, "y": 500},
]
NORMALIZED_SQUARE = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]


def validate(corners):
    return validate_quad(corners, image_width=IMAGE_WIDTH, image_height=IMAGE_HEIGHT)


def test_a_convex_quad_is_returned_in_canonical_order():
    reversed_square = list(reversed(SQUARE))

    expected = (
        Point(100, 100),
        Point(900, 100),
        Point(900, 900),
        Point(100, 900),
    )
    assert validate(SQUARE) == expected
    assert validate(reversed_square) == expected


def test_a_counter_clockwise_quad_from_another_corner_is_reordered():
    counter_clockwise_from_bottom_right = [
        {"x": 900, "y": 900},
        {"x": 900, "y": 100},
        {"x": 100, "y": 100},
        {"x": 100, "y": 900},
    ]

    assert validate(counter_clockwise_from_bottom_right) == (
        Point(100, 100),
        Point(900, 100),
        Point(900, 900),
        Point(100, 900),
    )


def test_corners_may_touch_the_image_edges():
    corners = [
        {"x": 0, "y": 0},
        {"x": 1000, "y": 0},
        {"x": 1000, "y": 1000},
        {"x": 0, "y": 1000},
    ]

    assert validate(corners)[0] == Point(0, 0)


@pytest.mark.parametrize(
    "corners",
    [
        SQUARE[:3],
        [*SQUARE, {"x": 500, "y": 500}],
        [{**point, "y": None} for point in SQUARE],
        [{**point, "x": "100"} for point in SQUARE],
        [{**point, "x": True} for point in SQUARE],
        [{**point, "x": math.nan} for point in SQUARE],
        ["not-a-point", *SQUARE[1:]],
    ],
)
def test_a_malformed_quad_is_rejected(corners):
    with pytest.raises(InvalidQuadCorners) as error:
        validate(corners)

    assert error.value.code == "quad_invalid_corners"


@pytest.mark.parametrize(
    "outside",
    [
        {"x": -1, "y": 100},
        {"x": 1001, "y": 100},
        {"x": 100, "y": -1},
        {"x": 100, "y": 1001},
    ],
)
def test_a_corner_outside_the_image_is_rejected(outside):
    corners = [outside, *SQUARE[1:]]

    with pytest.raises(QuadOutOfBounds) as error:
        validate(corners)

    assert error.value.code == "quad_out_of_bounds"


def test_a_self_intersecting_quad_is_rejected():
    bowtie = [
        {"x": 100, "y": 100},
        {"x": 900, "y": 900},
        {"x": 900, "y": 100},
        {"x": 100, "y": 900},
    ]

    with pytest.raises(QuadSelfIntersecting) as error:
        validate(bowtie)

    assert error.value.code == "quad_self_intersecting"


def test_a_concave_quad_is_rejected():
    concave = [
        {"x": 100, "y": 100},
        {"x": 900, "y": 100},
        {"x": 900, "y": 900},
        {"x": 500, "y": 300},
    ]

    with pytest.raises(QuadNonConvex) as error:
        validate(concave)

    assert error.value.code == "quad_non_convex"


def test_a_quad_below_the_minimum_area_is_rejected():
    tiny = [
        {"x": 100, "y": 100},
        {"x": 150, "y": 100},
        {"x": 150, "y": 150},
        {"x": 100, "y": 150},
    ]

    with pytest.raises(QuadTooSmall) as error:
        validate(tiny)

    assert error.value.code == "quad_too_small"
    assert MIN_QUAD_AREA_RATIO > 0


def test_to_pixels_scales_normalized_corners_to_the_image():
    assert to_pixels(NORMALIZED_SQUARE, 4000, 3000) == (
        Point(400, 300),
        Point(3600, 300),
        Point(3600, 2700),
        Point(400, 2700),
    )


def test_the_same_normalized_quad_has_the_photographed_ratio_on_each_orientation():
    landscape = quad_aspect_ratio(to_pixels(NORMALIZED_SQUARE, 4000, 3000))
    portrait = quad_aspect_ratio(to_pixels(NORMALIZED_SQUARE, 3000, 4000))

    assert landscape == AspectRatio(3200, 2400)
    assert portrait == AspectRatio(2400, 3200)
    assert landscape.value == pytest.approx(4 / 3)
    assert portrait.value == pytest.approx(3 / 4)


def test_the_area_uses_the_shoelace_formula():
    assert quad_area(SQUARE) == 800 * 800


def test_the_quad_ratio_averages_opposite_edges():
    assert quad_aspect_ratio(SQUARE) == AspectRatio(800, 800)
    assert quad_aspect_ratio(TALL) == AspectRatio(200, 400)
    assert quad_aspect_ratio(TALL).value == 0.5
