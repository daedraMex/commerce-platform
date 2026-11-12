"""Render a submission's original with Pillow: straighten, crop and correct the light."""

import math
import warnings
from io import BytesIO

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from apps.photos.application.ports import RenderedPhoto
from apps.photos.domain.errors import InvalidImage
from apps.photos.domain.light import plan_light_correction
from apps.photos.domain.processing import ProcessingPlan, plan_processing
from apps.photos.domain.submission import PhotoSubmission
from apps.photos.infrastructure.media_uploader import (
    convert_to_srgb,
    encode_jpeg,
    flatten_to_rgb,
)


class PillowPhotoRenderer:
    """The PhotoRenderer adapter over the deterministic Pillow pipeline."""

    def render(self, submission: PhotoSubmission, original: bytes) -> RenderedPhoto:
        image = _decode(original)
        plan = plan_processing(
            kind=submission.kind,
            crop=submission.crop,
            corners=submission.corners,
            light_correction=submission.light_correction,
            image_width=image.width,
            image_height=image.height,
        )
        rendered = _apply_plan(image, plan)
        content = encode_jpeg(rendered)
        return RenderedPhoto(
            content=content,
            width=rendered.width,
            height=rendered.height,
            mime_type="image/jpeg",
            extension="jpg",
            metadata={
                "format": "JPEG",
                "bytes": len(content),
                "pipeline_version": plan.pipeline_version,
                "light_correction": plan.light_correction,
            },
        )


def _decode(content: bytes) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                return flatten_to_rgb(convert_to_srgb(oriented))
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise InvalidImage("The private original is not an image this service can read.") from error


def _apply_plan(image: Image.Image, plan: ProcessingPlan) -> Image.Image:
    if plan.pixel_corners is not None:
        image = _straighten(image, plan.pixel_corners)
    else:
        frame = plan.source_frame
        image = image.crop((frame.x, frame.y, frame.x + frame.width, frame.y + frame.height))
    image = _crop_to_ratio(image, plan.target_ratio.value)
    return _correct_light(image, plan.light_correction)


def _straighten(image: Image.Image, corners) -> Image.Image:
    top_left, top_right, bottom_right, bottom_left = corners
    width = max(
        1, round((_distance(top_left, top_right) + _distance(bottom_left, bottom_right)) / 2)
    )
    height = max(
        1, round((_distance(top_right, bottom_right) + _distance(top_left, bottom_left)) / 2)
    )
    data = (
        top_left.x,
        top_left.y,
        bottom_left.x,
        bottom_left.y,
        bottom_right.x,
        bottom_right.y,
        top_right.x,
        top_right.y,
    )
    return image.transform(
        (width, height),
        Image.Transform.QUAD,
        data,
        Image.Resampling.BICUBIC,
    )


def _crop_to_ratio(image: Image.Image, target: float) -> Image.Image:
    width, height = image.size
    current = width / height
    if math.isclose(current, target, rel_tol=1e-9):
        return image
    if current > target:
        new_width = max(1, round(height * target))
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = max(1, round(width / target))
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def _correct_light(image: Image.Image, enabled: bool) -> Image.Image:
    if not enabled:
        return image
    means = ImageStat.Stat(image).mean
    plan = plan_light_correction(means, enabled=True)
    channels = [
        channel.point(lambda value, gain=gain: min(255, round(value * gain)))
        for channel, gain in zip(image.split(), plan.gains, strict=True)
    ]
    corrected = Image.merge("RGB", channels)
    return ImageOps.autocontrast(corrected, cutoff=plan.autocontrast_cutoff)


def _distance(first, second) -> float:
    return math.hypot(second.x - first.x, second.y - first.y)
