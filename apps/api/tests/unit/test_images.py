"""The picture renderer (blueprint F.6, D.26; D-062): two fixed sizes within
their byte budgets, upright, and with nothing but pixels inside."""

from __future__ import annotations

import io
import random

import pytest
from PIL import ExifTags, Image

from markx.core.images import ImageTooComplex, NotAnImage, decode_clean, render_webp, sanitize_image
from markx.images.service import MAIN_MAX_BYTES, MAIN_SIDE, THUMB_MAX_BYTES, THUMB_SIDE


def noisy_photo(width: int = 4000, height: int = 3000, *, seed: int = 7) -> Image.Image:
    """Random noise compresses worst of all: the hardest case for a budget."""
    rng = random.Random(seed)  # noqa: S311 - test pixels, not secrets
    return Image.frombytes("RGB", (width, height), rng.randbytes(width * height * 3))


def phone_jpeg(
    width: int = 400, height: int = 300, *, orientation: int = 6, gps: bool = True
) -> bytes:
    """A JPEG as a phone writes it: a rotation flag and the place it was taken."""
    image = Image.new("RGB", (width, height), "white")
    image.paste((200, 30, 30), (0, 0, width // 2, height))  # left half red
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = orientation
    exif[ExifTags.Base.Make] = "PhoneCo"
    if gps:
        place = exif.get_ifd(ExifTags.IFD.GPSInfo)
        place[ExifTags.GPS.GPSLatitudeRef] = "N"
        place[ExifTags.GPS.GPSLatitude] = (9.0, 1.0, 30.0)
        place[ExifTags.GPS.GPSLongitudeRef] = "E"
        place[ExifTags.GPS.GPSLongitude] = (38.0, 45.0, 10.0)
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif.tobytes(), quality=90)
    return out.getvalue()


def assert_bare(data: bytes) -> Image.Image:
    """A WebP with no EXIF, XMP or ICC profile: nothing but pixels."""
    image = Image.open(io.BytesIO(data))
    assert image.format == "WEBP"
    assert not {"exif", "xmp", "icc_profile"} & set(image.info), image.info
    assert dict(image.getexif()) == {}
    return image


def test_both_sizes_fit_their_budgets_even_for_the_worst_picture() -> None:
    picture = noisy_photo()
    thumb = render_webp(picture, longest_side=THUMB_SIDE, max_bytes=THUMB_MAX_BYTES)
    main = render_webp(picture, longest_side=MAIN_SIDE, max_bytes=MAIN_MAX_BYTES)
    assert len(thumb.data) <= 30_000
    assert len(main.data) <= 150_000
    assert max(thumb.width, thumb.height) <= 320
    assert max(main.width, main.height) <= 1200
    # The shape is kept.
    assert abs(main.width / main.height - 4 / 3) < 0.02
    for rendered in (thumb, main):
        image = assert_bare(rendered.data)
        assert image.size == (rendered.width, rendered.height)


def test_a_small_picture_is_never_enlarged() -> None:
    small = Image.new("RGB", (200, 100), "green")
    main = render_webp(small, longest_side=MAIN_SIDE, max_bytes=MAIN_MAX_BYTES)
    assert (main.width, main.height) == (200, 100)


def test_location_and_camera_data_never_survive_and_the_photo_is_upright() -> None:
    original = phone_jpeg()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(ExifTags.IFD.GPSInfo)
    clean, content_type = sanitize_image(original)
    assert content_type == "image/jpeg"
    cleaned = Image.open(io.BytesIO(clean))
    assert dict(cleaned.getexif()) == {}
    upright = decode_clean(clean)
    # Orientation 6 means "turn 90 degrees": 400 x 300 becomes 300 x 400.
    assert upright.size == (300, 400)
    main = render_webp(upright, longest_side=MAIN_SIDE, max_bytes=MAIN_MAX_BYTES)
    rendered = assert_bare(main.data).convert("RGB")
    # The red half is now on top, as the photographer saw it.
    red, green, blue = rendered.getpixel((150, 50))  # type: ignore[misc]
    assert red > 150
    assert green < 100
    assert blue < 100


def test_transparency_is_kept() -> None:
    clear = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    main = render_webp(decode_clean(_png(clear)), longest_side=MAIN_SIDE, max_bytes=MAIN_MAX_BYTES)
    assert assert_bare(main.data).mode == "RGBA"


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


@pytest.mark.parametrize(
    "data",
    [b"", b"not a picture", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, b"GIF89a" + b"\x00" * 64],
)
def test_anything_but_a_jpeg_png_or_webp_is_refused(data: bytes) -> None:
    with pytest.raises(NotAnImage):
        sanitize_image(data)
    with pytest.raises(NotAnImage):
        decode_clean(data)


def test_an_impossible_budget_is_reported_not_looped_forever() -> None:
    with pytest.raises(ImageTooComplex):
        render_webp(noisy_photo(800, 600), longest_side=800, max_bytes=50)
