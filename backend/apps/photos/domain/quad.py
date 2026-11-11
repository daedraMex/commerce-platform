"""Validate the four staff-tapped corners and measure the quad they describe.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

import math
from collections.abc import Mapping, Sequence

from apps.photos.domain.errors import (
    InvalidQuadCorners,
    QuadNonConvex,
    QuadOutOfBounds,
    QuadSelfIntersecting,
    QuadTooSmall,
)
from apps.photos.domain.geometry import AspectRatio, Point

MIN_QUAD_AREA_RATIO = 0.02


def to_pixels(corners, width: int, height: int) -> tuple[Point, Point, Point, Point]:
    """Scale normalized corners to pixels of the EXIF-normalized original.

    The console sends the four tapped corners as fractions between 0 and 1 of
    the EXIF-normalized original, and ``PhotoSubmission.corners`` stores those
    fractions. This converts them to the pixel corners that the quad rules use.
    """
    if width <= 0 or height <= 0:
        raise ValueError("The image dimensions must be positive.")

    points = parse_quad(corners)
    return tuple(Point(point.x * width, point.y * height) for point in points)


def validate_quad(
    pixel_corners,
    *,
    image_width: int,
    image_height: int,
) -> tuple[Point, Point, Point, Point]:
    """Return the pixel corners in canonical order, or raise the first rule they break.

    The corners are returned as top-left, top-right, bottom-right, bottom-left
    (clockwise on screen, with y pointing down), whatever order they were tapped.
    """
    if image_width <= 0 or image_height <= 0:
        raise ValueError("The image dimensions must be positive.")

    points = parse_quad(pixel_corners)
    if any(
        point.x < 0 or point.x > image_width or point.y < 0 or point.y > image_height
        for point in points
    ):
        raise QuadOutOfBounds("Every corner must lie inside the photo.")
    if _is_self_intersecting(points):
        raise QuadSelfIntersecting("The corners cross each other; drag them into order.")
    if not _is_convex(points):
        raise QuadNonConvex("The corners must form a convex quadrilateral.")
    if quad_area(points) < MIN_QUAD_AREA_RATIO * image_width * image_height:
        raise QuadTooSmall("The selected area is too small to become a product photo.")
    return _order_corners(points)


def parse_quad(corners) -> tuple[Point, Point, Point, Point]:
    """Turn the persisted list of ``{x, y}`` corners into four finite points."""
    if isinstance(corners, (str, bytes)) or not isinstance(corners, Sequence):
        raise InvalidQuadCorners("The corners must be a list of four points.")
    if len(corners) != 4:
        raise InvalidQuadCorners("A photo needs exactly four corners.")
    return tuple(_parse_point(corner) for corner in corners)


def quad_area(pixel_corners) -> float:
    """The area enclosed by the pixel corners, in square pixels."""
    points = parse_quad(pixel_corners)
    doubled = sum(
        point.x * next_point.y - next_point.x * point.y
        for point, next_point in zip(points, (*points[1:], points[0]), strict=True)
    )
    return abs(doubled) / 2


def quad_aspect_ratio(pixel_corners) -> AspectRatio:
    """The ratio of the pixel quad, averaging each pair of opposite edges."""
    top_left, top_right, bottom_right, bottom_left = _order_corners(parse_quad(pixel_corners))
    width = (_distance(top_left, top_right) + _distance(bottom_left, bottom_right)) / 2
    height = (_distance(top_right, bottom_right) + _distance(top_left, bottom_left)) / 2
    if width <= 0 or height <= 0:
        raise QuadTooSmall("The quad has no measurable width or height.")
    return AspectRatio(width, height)


def _order_corners(points: tuple[Point, Point, Point, Point]) -> tuple[Point, Point, Point, Point]:
    """Return the corners as top-left, top-right, bottom-right, bottom-left."""
    center_x = sum(point.x for point in points) / 4
    center_y = sum(point.y for point in points) / 4
    clockwise = sorted(points, key=lambda point: math.atan2(point.y - center_y, point.x - center_x))
    start = min(
        range(4),
        key=lambda index: (clockwise[index].x + clockwise[index].y, clockwise[index].x),
    )
    return tuple(clockwise[(start + offset) % 4] for offset in range(4))


def _parse_point(value) -> Point:
    if isinstance(value, Point):
        x, y = value.x, value.y
    elif isinstance(value, Mapping):
        try:
            x, y = value["x"], value["y"]
        except KeyError as error:
            raise InvalidQuadCorners("Every corner needs an 'x' and a 'y'.") from error
    else:
        raise InvalidQuadCorners("Every corner must be an object with 'x' and 'y'.")

    if not _is_finite_number(x) or not _is_finite_number(y):
        raise InvalidQuadCorners("Every corner coordinate must be a finite number.")
    return Point(float(x), float(y))


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _distance(first: Point, second: Point) -> float:
    return math.hypot(second.x - first.x, second.y - first.y)


def _is_convex(points: tuple[Point, Point, Point, Point]) -> bool:
    signs = []
    for index in range(4):
        current = points[index]
        following = points[(index + 1) % 4]
        later = points[(index + 2) % 4]
        cross = _cross(current, following, later)
        if cross == 0:
            return False
        signs.append(cross > 0)
    return all(signs) or not any(signs)


def _cross(origin: Point, first: Point, second: Point) -> float:
    return (first.x - origin.x) * (second.y - origin.y) - (first.y - origin.y) * (
        second.x - origin.x
    )


def _is_self_intersecting(points: tuple[Point, Point, Point, Point]) -> bool:
    first, second, third, fourth = points
    return _segments_intersect(first, second, third, fourth) or _segments_intersect(
        second, third, fourth, first
    )


def _segments_intersect(first: Point, second: Point, third: Point, fourth: Point) -> bool:
    first_side = _cross(first, second, third)
    second_side = _cross(first, second, fourth)
    third_side = _cross(third, fourth, first)
    fourth_side = _cross(third, fourth, second)

    if first_side == 0 and _is_on_segment(first, second, third):
        return True
    if second_side == 0 and _is_on_segment(first, second, fourth):
        return True
    if third_side == 0 and _is_on_segment(third, fourth, first):
        return True
    if fourth_side == 0 and _is_on_segment(third, fourth, second):
        return True
    return (first_side > 0) != (second_side > 0) and (third_side > 0) != (fourth_side > 0)


def _is_on_segment(first: Point, second: Point, point: Point) -> bool:
    return min(first.x, second.x) <= point.x <= max(first.x, second.x) and min(
        first.y, second.y
    ) <= point.y <= max(first.y, second.y)
