"""Plan the deterministic gray-world light correction (ADR-0028).

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from apps.photos.domain.errors import InvalidChannelMeans
from apps.photos.domain.pipeline import PIPELINE_VERSION

MAX_GAIN = 2.0
MIN_GAIN = 0.5
AUTOCONTRAST_CUTOFF = 1


@dataclass(frozen=True, slots=True)
class LightCorrection:
    """The white balance and autocontrast a processing run should apply."""

    enabled: bool
    red_gain: float
    green_gain: float
    blue_gain: float
    autocontrast_cutoff: int
    pipeline_version: str

    @property
    def gains(self) -> tuple[float, float, float]:
        return (self.red_gain, self.green_gain, self.blue_gain)


def plan_light_correction(
    channel_means: Sequence[float],
    *,
    enabled: bool = True,
) -> LightCorrection:
    """Build capped gray-world gains from the mean of each colour channel."""
    red, green, blue = _validate_means(channel_means)
    if not enabled:
        return _plan(enabled=False, gains=(1.0, 1.0, 1.0), cutoff=0)

    gray = (red + green + blue) / 3
    if gray <= 0:
        return _plan(enabled=True, gains=(1.0, 1.0, 1.0), cutoff=AUTOCONTRAST_CUTOFF)

    gains = tuple(
        1.0 if mean <= 0 else min(MAX_GAIN, max(MIN_GAIN, gray / mean))
        for mean in (red, green, blue)
    )
    return _plan(enabled=True, gains=gains, cutoff=AUTOCONTRAST_CUTOFF)


def _plan(*, enabled: bool, gains: tuple[float, float, float], cutoff: int) -> LightCorrection:
    return LightCorrection(
        enabled=enabled,
        red_gain=gains[0],
        green_gain=gains[1],
        blue_gain=gains[2],
        autocontrast_cutoff=cutoff,
        pipeline_version=PIPELINE_VERSION,
    )


def _validate_means(channel_means) -> tuple[float, float, float]:
    if (
        isinstance(channel_means, (str, bytes))
        or not isinstance(channel_means, Sequence)
        or len(channel_means) != 3
    ):
        raise InvalidChannelMeans("Light correction needs exactly three channel means.")
    if any(not _is_mean(value) for value in channel_means):
        raise InvalidChannelMeans("Every channel mean must be a finite non-negative number.")
    red, green, blue = channel_means
    return float(red), float(green), float(blue)


def _is_mean(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
