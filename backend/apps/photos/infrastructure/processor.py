"""Pillow implementation of the PhotoProcessor port (ADR-0028)."""

import math
from io import BytesIO

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from apps.photos.application.ports import ProcessedPhoto
from apps.photos.domain.crop import CropRect, crop_ratio, fit_crop
from apps.photos.domain.errors import InvalidCrop, InvalidImage
from apps.photos.domain.light import plan_light_correction
from apps.photos.domain.quad import to_pixels, validate_quad
from apps.photos.domain.submission import SubmissionKind
from apps.photos.infrastructure.media_uploader import encode_jpeg


class PillowPhotoProcessor:
    """Crop, straighten, colour-correct and encode the private original."""

    def process(self, submission, size, original: bytes) -> ProcessedPhoto:
        image = self._decode(original)
        image = self._crop(image, submission, size)
        image = self._correct(image, submission)
        content = encode_jpeg(image)
        return ProcessedPhoto(content=content, width=image.width, height=image.height)

    def _decode(self, original: bytes) -> Image.Image:
        try:
            with Image.open(BytesIO(original)) as source:
                source.load()
                return source.convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise InvalidImage("The private original cannot be decoded.") from error

    def _crop(self, image: Image.Image, submission, size) -> Image.Image:
        kind = submission.kind
        if kind is SubmissionKind.RECTANGLE:
            return self._straighten(image, submission, size)

        if kind is SubmissionKind.GROUP:
            ratio = crop_ratio(kind=kind)
            frame = CropRect(0, 0, image.width, image.height)
        else:
            ratio = crop_ratio(kind=kind, size=size)
            frame = self._contour_frame(submission.crop)

        fitted = fit_crop(frame, ratio)
        return image.crop((fitted.x, fitted.y, fitted.x + fitted.width, fitted.y + fitted.height))

    def _straighten(self, image: Image.Image, submission, size) -> Image.Image:
        pixel_corners = to_pixels(submission.corners, image.width, image.height)
        ordered = validate_quad(pixel_corners, image_width=image.width, image_height=image.height)
        ratio = crop_ratio(kind=SubmissionKind.RECTANGLE, size=size, pixel_corners=ordered)

        top_left, top_right, bottom_right, bottom_left = ordered
        average_width = (_distance(top_left, top_right) + _distance(bottom_left, bottom_right)) / 2
        average_height = (_distance(top_right, bottom_right) + _distance(top_left, bottom_left)) / 2
        frame = CropRect(0, 0, max(1, round(average_width)), max(1, round(average_height)))
        fitted = fit_crop(frame, ratio)

        source = tuple(
            coordinate
            for point in (top_left, top_right, bottom_right, bottom_left)
            for coordinate in (point.x, point.y)
        )
        return image.transform(
            (fitted.width, fitted.height),
            Image.Transform.QUAD,
            data=source,
            resample=Image.Resampling.BILINEAR,
        )

    def _contour_frame(self, crop) -> CropRect:
        if not isinstance(crop, dict):
            raise InvalidCrop("A contour photo needs a crop rectangle.")
        try:
            return CropRect(
                x=crop["x"],
                y=crop["y"],
                width=crop["width"],
                height=crop["height"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidCrop("The crop rectangle is malformed.") from error

    def _correct(self, image: Image.Image, submission) -> Image.Image:
        plan = plan_light_correction(
            ImageStat.Stat(image).mean,
            enabled=submission.light_correction,
        )
        if not plan.enabled:
            return image

        red, green, blue = image.split()
        corrected = Image.merge(
            "RGB",
            (
                red.point(lambda value: _apply_gain(value, plan.red_gain)),
                green.point(lambda value: _apply_gain(value, plan.green_gain)),
                blue.point(lambda value: _apply_gain(value, plan.blue_gain)),
            ),
        )
        if plan.autocontrast_cutoff:
            corrected = ImageOps.autocontrast(corrected, cutoff=plan.autocontrast_cutoff)
        return corrected


def _distance(first, second) -> float:
    return math.hypot(second.x - first.x, second.y - first.y)


def _apply_gain(value: int, gain: float) -> int:
    return max(0, min(255, round(value * gain)))
