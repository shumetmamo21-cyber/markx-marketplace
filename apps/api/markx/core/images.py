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


# -- the product image pipeline (blueprint F.6, D.26, P5; D-062) ----------------------


class ImageTooComplex(ValueError):
    """The picture could not be brought under its byte budget at any size."""


class RenderedImage:
    """One WebP file the pipeline produced."""

    __slots__ = ("data", "height", "width")

    def __init__(self, data: bytes, width: int, height: int) -> None:
        self.data = data
        self.width = width
        self.height = height


# Quality steps tried at each size before the picture is made smaller.
_QUALITIES = (82, 74, 66, 58, 50, 42)
_SHRINK = 0.85
_SMALLEST_SIDE = 64


def decode_clean(data: bytes) -> Image.Image:
    """Decode a picture already cleaned by `sanitize_image` and return it
    upright, in RGB or RGBA, with nothing but pixels: no EXIF, XMP, ICC
    profile or comments survive into what is rendered from it."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            image: Image.Image = Image.open(io.BytesIO(data), formats=list(_FORMATS))
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
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    mode = "RGBA" if has_alpha else "RGB"
    converted = image.convert(mode)
    # A new image from the raw pixels carries no `info` at all.
    return Image.frombytes(mode, converted.size, converted.tobytes())


def render_webp(image: Image.Image, *, longest_side: int, max_bytes: int) -> RenderedImage:
    """The picture as WebP, fitted inside a square of `longest_side` pixels
    (never enlarged) and no larger than `max_bytes`: lower quality first,
    then smaller, until it fits. Nothing but pixels is written."""
    scale = min(1.0, longest_side / max(image.width, image.height))
    while True:
        width = max(1, round(image.width * scale))
        height = max(1, round(image.height * scale))
        if min(width, height) < _SMALLEST_SIDE and scale < 1.0:
            raise ImageTooComplex(f"could not fit the picture in {max_bytes} bytes")
        sized = image if (width, height) == image.size else image.resize(
            (width, height), Image.Resampling.LANCZOS
        )  # fmt: skip
        for quality in _QUALITIES:
            out = io.BytesIO()
            sized.save(out, "WEBP", quality=quality, method=6, exif=b"", xmp=b"", icc_profile=b"")
            if out.tell() <= max_bytes:
                return RenderedImage(out.getvalue(), width, height)
        scale *= _SHRINK
