"""Small geometry value objects shared by the photo domain rules."""

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class AspectRatio:
    """A width-to-height ratio; its float value is ``width / height``."""

    width: float
    height: float

    def __post_init__(self) -> None:
        if not is_positive_number(self.width) or not is_positive_number(self.height):
            raise ValueError("An aspect ratio needs two positive dimensions.")

    @property
    def value(self) -> float:
        return self.width / self.height


def is_positive_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )
