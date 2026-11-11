import math

import pytest

from apps.photos.domain.errors import InvalidChannelMeans
from apps.photos.domain.light import (
    AUTOCONTRAST_CUTOFF,
    MAX_GAIN,
    MIN_GAIN,
    plan_light_correction,
)
from apps.photos.domain.pipeline import PIPELINE_VERSION


def test_a_neutral_image_needs_unit_gains():
    plan = plan_light_correction((100, 100, 100))

    assert plan.enabled is True
    assert plan.gains == (1.0, 1.0, 1.0)
    assert plan.autocontrast_cutoff == AUTOCONTRAST_CUTOFF
    assert plan.pipeline_version == PIPELINE_VERSION


def test_gray_world_balances_a_colour_cast():
    plan = plan_light_correction((95, 100, 105))

    assert plan.red_gain == pytest.approx(100 / 95)
    assert plan.green_gain == pytest.approx(1.0)
    assert plan.blue_gain == pytest.approx(100 / 105)


def test_the_caps_are_gentle_corrections():
    assert MAX_GAIN == 1.15
    assert MIN_GAIN == 0.85


def test_gains_are_capped_when_a_channel_is_far_off():
    plan = plan_light_correction((1, 100, 100))

    assert plan.red_gain == MAX_GAIN
    assert plan.green_gain == MIN_GAIN
    assert plan.blue_gain == MIN_GAIN
    assert plan.red_gain <= MAX_GAIN


def test_low_gains_are_capped_too():
    plan = plan_light_correction((1000, 10, 10))

    assert plan.red_gain == MIN_GAIN
    assert plan.green_gain == MAX_GAIN
    assert plan.blue_gain == MAX_GAIN
    assert all(MIN_GAIN <= gain <= MAX_GAIN for gain in plan.gains)


def test_a_zero_channel_does_not_divide_by_zero():
    plan = plan_light_correction((0, 100, 100))

    assert plan.red_gain == 1.0
    assert plan.pipeline_version == PIPELINE_VERSION


def test_staff_can_switch_light_correction_off():
    plan = plan_light_correction((1, 100, 100), enabled=False)

    assert plan.enabled is False
    assert plan.gains == (1.0, 1.0, 1.0)
    assert plan.autocontrast_cutoff == 0
    assert plan.pipeline_version == PIPELINE_VERSION


@pytest.mark.parametrize(
    "means",
    [
        (100, 100),
        (100, 100, 100, 100),
        (-1, 100, 100),
        (100, math.nan, 100),
        (100, math.inf, 100),
        (True, 100, 100),
        ("100", 100, 100),
    ],
)
def test_invalid_channel_means_are_rejected(means):
    with pytest.raises(InvalidChannelMeans) as error:
        plan_light_correction(means)

    assert error.value.code == "light_invalid_channel_means"
