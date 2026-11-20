import pytest

from markx.core.phone import InvalidPhoneNumber, is_valid_phone, mask_phone, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # every accepted form from blueprint P.1, for both operators
        ("0911234567", "+251911234567"),
        ("0711234567", "+251711234567"),
        ("911234567", "+251911234567"),
        ("711234567", "+251711234567"),
        ("+251911234567", "+251911234567"),
        ("+251711234567", "+251711234567"),
        ("251911234567", "+251911234567"),
        ("251711234567", "+251711234567"),
        ("00251911234567", "+251911234567"),
        ("00251711234567", "+251711234567"),
        # how people actually type them
        ("0911 23 45 67", "+251911234567"),
        ("+251 91 123 4567", "+251911234567"),
        ("(0911) 234-567", "+251911234567"),
        ("  0911234567  ", "+251911234567"),
    ],
)
def test_accepts_every_documented_form(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected
    assert is_valid_phone(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "0811234567",  # not a mobile prefix
        "0611234567",
        "091123456",  # too short
        "09112345678",  # too long
        "+2510911234567",  # country code followed by a trunk zero
        "+1 415 555 0100",  # foreign number
        "+441632960961",
        "0911-23-45-6a",  # letters
        "telegram",
        "+251",
        "25191123456",  # one digit short
        "++251911234567",
        "0911234567;drop table users",
    ],
)
def test_rejects_everything_else(raw: str) -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)
    assert not is_valid_phone(raw)


def test_rejects_non_text() -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(911234567)  # type: ignore[arg-type]


def test_mask_hides_the_middle() -> None:
    assert mask_phone("+251911234567") == "+2519••••4567"
    assert "1234" not in mask_phone("+251911234567")


# -- digits from other scripts (B-3, D-098) ---------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("٠٩١١٢٣٤٥٦٧", "+251911234567"),  # Arabic-Indic
        ("۰۹۱۱۲۳۴۵۶۷", "+251911234567"),  # Persian (extended Arabic-Indic)
        ("０９１１ ２３４ ５６７", "+251911234567"),  # full-width, with spaces
        ("०९११२३४५६७", "+251911234567"),  # Devanagari
        ("+٢٥١٧١١٢٣٤٥٦٧", "+251711234567"),  # with the country code
        ("09١١٢٣٤٥٦٧", "+251911234567"),  # mixed: this used to reach the database
        ("+2519１２３４５６７８", "+251912345678"),  # mixed full-width
    ],
)
def test_digits_from_other_scripts_are_read_as_0_to_9(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected
    assert normalize_phone(raw).isascii()


@pytest.mark.parametrize(
    "raw",
    [
        "፱፩፩፪፫፬፭፮፯",  # Ethiopic numerals: not decimal digits
        "09፩፩፪፫፬፭፮፯",
        "٠٩١١٢٣٤٥٦٧٨",  # too long, in another script
        "٠٨١١٢٣٤٥٦٧",  # not a mobile prefix, in another script
        "０９１１２３４５６",  # too short
        "²⁹¹¹²³⁴⁵⁶⁷",  # superscripts are not decimal digits
    ],
)
def test_other_characters_are_still_refused(raw: str) -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


def test_whatever_is_accepted_is_what_the_database_accepts() -> None:
    """The database allows only ^\\+251[79][0-9]{8}$ (ASCII digits)."""
    import re
    import unicodedata

    from markx.accounts.models import PHONE_PATTERN

    database = re.compile(PHONE_PATTERN, re.ASCII)
    zero_digits = [chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) == "Nd"
                   and unicodedata.decimal(chr(c)) == 0]  # fmt: skip
    for zero in zero_digits:
        digits = {str(n): chr(ord(zero) + n) for n in range(10)}
        typed = "".join(digits[d] for d in "0911234567")
        assert database.fullmatch(normalize_phone(typed)), typed
