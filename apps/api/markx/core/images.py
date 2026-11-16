"""Checking and cleaning an uploaded photo (blueprint F.6: images only).

The declared file name and content type are ignored. The bytes are decoded,
and the picture is written out again, which drops location data and anything
hidden after the image.
"""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MAX_PIXELS = 40_000_000  # a 40-megapixel phone photo


class NotAnImage(ValueError):
    pass


def sanitize_image(data: bytes) -> tuple[bytes, str]:
    """Return the cleaned image and its content type, or raise NotAnImage."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image: Image.Image = Image.open(io.BytesIO(data), formats=list(_FORMATS))
            image_format = image.format or ""
            if image.width * image.height > MAX_PIXELS:
                raise NotAnImage("the picture is too large")
            image.load()
    except NotAnImage:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise NotAnImage("not a JPEG, PNG or WebP picture") from exc
    if image_format not in _FORMATS:
        raise NotAnImage("not a JPEG, PNG or WebP picture")

    # Apply the camera's rotation before its metadata is dropped.
    image = ImageOps.exif_transpose(image)
    out = io.BytesIO()
    if image_format == "JPEG":
        image.convert("RGB").save(out, "JPEG", quality=90)
    elif image_format == "PNG":
        if image.mode not in ("RGB", "RGBA", "L"):
            image = image.convert("RGBA")
        image.save(out, "PNG")
    else:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(out, "WEBP", quality=90)
    return out.getvalue(), _FORMATS[image_format]
