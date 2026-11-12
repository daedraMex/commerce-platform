"""Image fixtures shared by upload tests.

Every upload entry point is tested against the same hostile inputs: GPS EXIF,
sideways phone photos, non-sRGB profiles, broken profiles and decompression
bombs. Keep them here so a new upload path reuses the cases instead of
inventing weaker ones.
"""

import math
import struct
import zlib
from fractions import Fraction
from io import BytesIO

from PIL import Image, ImageCms


def image_bytes(image_format="JPEG", size=(12, 8), color=(20, 30, 40)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


def jpeg_with_exif(*, size=(12, 8), orientation=None, gps=False):
    image = Image.new("RGB", size, (20, 30, 40))
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    if gps:
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (Fraction(1, 1), Fraction(2, 1), Fraction(3, 1))
        gps_ifd[3] = "E"
        gps_ifd[4] = (Fraction(4, 1), Fraction(5, 1), Fraction(6, 1))
        exif[0x8825] = gps_ifd
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def non_srgb_profile():
    """An RGB ICC profile whose channels differ from sRGB."""
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    content = bytearray(profile.tobytes())
    tag_count = struct.unpack_from(">I", content, 128)[0]
    scales = {b"rXYZ": 1.2, b"gXYZ": 0.8, b"bXYZ": 0.6}
    for index in range(tag_count):
        record = 132 + index * 12
        tag = bytes(content[record : record + 4])
        if tag in scales:
            values = struct.unpack_from(">I", content, record + 4)[0] + 8
            x, y, z = struct.unpack_from(">3i", content, values)
            struct.pack_into(
                ">3i",
                content,
                values,
                int(x * scales[tag]),
                int(y * scales[tag]),
                int(z * scales[tag]),
            )
    return bytes(content)


def jpeg_with_icc_profile(profile, *, size=(12, 8), color=(200, 100, 50)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG", icc_profile=profile)
    return buffer.getvalue()


def png_with_declared_size(width, height):
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buffer, format="PNG")
    content = bytearray(buffer.getvalue())
    struct.pack_into(">II", content, 16, width, height)
    struct.pack_into(">I", content, 29, zlib.crc32(content[12:29]) & 0xFFFFFFFF)
    return bytes(content)


def png_of_declared_pixels(pixels):
    side = math.isqrt(pixels) + 1
    return png_with_declared_size(side, side)


def heic_bytes(*, size=(12, 8), color=(20, 30, 40)):
    from pillow_heif import register_heif_opener

    register_heif_opener()
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="HEIF")
    return buffer.getvalue()
